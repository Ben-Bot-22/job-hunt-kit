"""`python -m core.setup` — the front door for someone with a terminal and no coding agent.

There are two ways into a working configuration and they are for different readers. **`/setup`** is a
ten-step interview: it reads your résumé into a bullet bank, asks about everything the résumé cannot
back, and writes the rubric *with* you. It is the recommended path and it needs an agent. This module
is the other one — a short wizard for a reader who cloned the repo and has a shell.

**It is deliberately narrower than the skill rather than a reimplementation of it.** What it will not
do is the rubric. `profile/rubric.md` is the file that decides every score, it is prose, and writing
one worth having means a model reading a CV and arguing with its owner about a pay floor. A wizard
that asked six questions and pasted the answers into a template would produce something that *looks*
like a rubric, scores everything 70, and never gets rewritten because it already exists. So the
example rubric is what lands, and the wizard says in one line whose it is and where the manual is.

What it does own is the middle ground that neither existing path covered. Before this file the choice
was the full interview or `cp -r config/example/ …` and a text editor: no prompts, no idea which of
the six files matter, and nothing checking the result until an import three minutes into a run. Here
the questions are only the ones with no sensible default — who you are, which provider, which
channels, which boards — everything else takes the example's value, and **the settings file is
validated through the real schema before the command exits**, so a bad answer is named here rather
than in the first run.

**Every prompt has a flag and an environment variable, and `--yes` asks nothing.** That is not a
courtesy to power users: it is how CI and a scripted install configure the tool, and it is how this
module is tested — the suite runs it against a fake empty tree with no network, no model and no key.

Seeding is `core.example.seed()`, unchanged and unwrapped: it never overwrites a file that is already
there, and what it skipped is printed rather than silently swallowed. Re-running this command on a
configured clone is safe by construction.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable

from .example import DESTINATIONS, EXAMPLE_DIR, seed
from .llm import PROVIDERS, api_key_for
from .settings import REPO_ROOT, ConfigurationError, load, validate

# The channels a wizard may switch on. `gmail` is in `core/settings.py`'s schema and is deliberately
# absent here: it is a documented stub that *raises* when enabled, so offering it in a menu would be
# offering a first run that crashes. Asking for it by name is an error with the reason attached.
OFFERED_CHANNELS: dict[str, str] = {
    "paste": "URLs on the command line or in a file — no key, no OAuth, any OS",
    "boards": "public Greenhouse/Lever boards you name — keyless GETs, any OS",
    "agencies": "six staffing firms' boards, scraped — keyless, any OS, ~130 s, contract work",
    "mail": "your inbox through Apple Mail — macOS only, and it wants an Automation permission",
}

# Where the answers land. The wizard edits exactly these paths and nothing else; anything not listed
# keeps whatever the example gave it, which is the ticket's rule about sensible defaults made literal.
_PROFILE_NAME = ("identity", "name")
_PROFILE_CONTACT = ("identity", "contact")
_PROFILE_INBOX = ("inbox", "account")
_LLM_PROVIDER = ("llm", "provider")

RUN_COMMAND = ".venv/bin/python -m triage --paste <a job URL>"


class SetupError(RuntimeError):
    """A bad answer, phrased for whoever typed it. Printed as one line, never as a traceback."""


# --------------------------------------------------------------------------------------------------
# Editing YAML that has comments in it
#
# `config/example/settings.yaml` is 90 lines of which about 55 are commentary — which channel needs
# what, why the concurrency is low, what a board token is. A stranger reads that file *after* running
# this wizard, and `yaml.safe_dump` of a parsed tree would hand them back a config with every one of
# those sentences deleted. So the two setters below are line surgery on known key paths rather than a
# load-edit-dump: they change the value and leave the file, its ordering and its comments alone.
#
# The cost is that they only work on the shape they are given. A key path that isn't in the file is
# reported to the user by name rather than silently dropped — see `_apply`.
# --------------------------------------------------------------------------------------------------

_KEY = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w.-]*):(?P<rest>.*)$")
_ITEM = re.compile(r"^(?P<indent>\s*)- ")
_PLAIN = re.compile(r"^[A-Za-z0-9_.@/+-]+$")


def _scalar(value: object) -> str:
    """A YAML scalar. Plain where plain is unambiguous, double-quoted otherwise — the example's style."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text and _PLAIN.match(text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _walk(lines: list[str]) -> Iterable[tuple[int, tuple[str, ...], re.Match]]:
    """Every mapping line, with the dotted path it sits at. Indentation is the only structure YAML has."""
    stack: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _KEY.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        indent = len(m.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, m.group("key")))
        yield i, tuple(k for _, k in stack), m


def _trailing_comment(rest: str) -> str:
    """The `  # …` after a value, kept. Naive about `#` inside a quoted scalar — none of ours have one."""
    hit = rest.find("#")
    return "  " + rest[hit:].rstrip() if hit >= 0 else ""


def set_scalar(text: str, path: tuple[str, ...], value: object) -> str | None:
    """`text` with `path` set to `value`, or `None` if the file has no such key."""
    lines = text.splitlines()
    for i, here, m in _walk(lines):
        if here == path:
            lines[i] = f"{m.group('indent')}{m.group('key')}: {_scalar(value)}{_trailing_comment(m.group('rest'))}"
            return "\n".join(lines) + "\n"
    return None


def set_list(text: str, path: tuple[str, ...], items: list[str]) -> str | None:
    """`text` with `path` set to a block list (or `[]`), or `None` if the file has no such key."""
    lines = text.splitlines()
    for i, here, m in _walk(lines):
        if here != path:
            continue
        indent = len(m.group("indent"))
        end = i + 1
        item_indent = indent + 2
        while end < len(lines):
            item = _ITEM.match(lines[end])
            if not item or len(item.group("indent")) <= indent:
                break
            item_indent = len(item.group("indent"))
            end += 1
        comment = _trailing_comment(m.group("rest"))
        head = f"{m.group('indent')}{m.group('key')}:"
        block = [head + (f" []{comment}" if not items else comment)]
        block += [f"{' ' * item_indent}- {_scalar(v)}" for v in items]
        return "\n".join(lines[:i] + block + lines[end:]) + "\n"
    return None


# --------------------------------------------------------------------------------------------------
# The questions
# --------------------------------------------------------------------------------------------------

def _split(raw: str | None) -> list[str]:
    """`"a, b ,c"` -> `["a", "b", "c"]`, and an empty string to `[]`. Also how `--channels` parses."""
    return [part.strip() for part in (raw or "").replace(",", " ").split() if part.strip()]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m core.setup",
        description="Take a fresh clone to a configuration that loads. Every prompt has a flag and an "
                    "environment variable; --yes asks nothing and takes the shipped example's value "
                    "for anything you did not give.",
        epilog="The rubric is not asked about here. Run /setup in a coding agent for that, or read "
               "docs/operating/rubric.md and write it yourself.")
    p.add_argument("--yes", "-y", action="store_true", help="unattended: ask nothing, take every default")
    p.add_argument("--name", help="the name on a rendered CV  [JOBSDB_SETUP_NAME]")
    p.add_argument("--email", help="your inbox address  [JOBSDB_SETUP_EMAIL]")
    p.add_argument("--provider", help=f"one of: {', '.join(sorted(PROVIDERS))}  [JOBSDB_SETUP_PROVIDER]")
    p.add_argument("--channels", help=f"comma-separated, exhaustive: {', '.join(OFFERED_CHANNELS)}  "
                                      f"[JOBSDB_SETUP_CHANNELS]")
    p.add_argument("--greenhouse", help="Greenhouse board tokens, comma-separated  [JOBSDB_SETUP_GREENHOUSE]")
    p.add_argument("--lever", help="Lever board tokens, comma-separated  [JOBSDB_SETUP_LEVER]")
    return p.parse_args(argv)


# flag name -> environment variable. The parity between the two is asserted in `core/test_setup.py`,
# because "every prompt is skippable" is only true while the table is complete.
ENV_FOR: dict[str, str] = {
    "name": "JOBSDB_SETUP_NAME",
    "email": "JOBSDB_SETUP_EMAIL",
    "provider": "JOBSDB_SETUP_PROVIDER",
    "channels": "JOBSDB_SETUP_CHANNELS",
    "greenhouse": "JOBSDB_SETUP_GREENHOUSE",
    "lever": "JOBSDB_SETUP_LEVER",
}


def _given(args: argparse.Namespace, field: str, env: dict[str, str]) -> str | None:
    """The flag, then the environment variable, then nothing. A flag beats an exported value."""
    flag = getattr(args, field, None)
    return flag if flag is not None else env.get(ENV_FOR[field]) or None


def _channel_choice(names: list[str], current: dict[str, bool]) -> dict[str, bool]:
    """Named channels on, every other channel off — exhaustive, matching `triage --channels`.

    Additive would be friendlier to type and wrong here for the same reason it was wrong there: the
    answer to "which channels" is the complete set someone wants, and a channel left on by a default
    they never saw is the one that reads their mailbox on a first run.
    """
    unknown = [n for n in names if n not in OFFERED_CHANNELS]
    if unknown:
        why = ("  `gmail` is an unbuilt stub that raises when enabled — see triage/channels/gmail_api.py.\n"
               if "gmail" in unknown else "")
        raise SetupError(f"unknown channel {unknown[0]!r}.\n{why}"
                         f"  Valid: {', '.join(OFFERED_CHANNELS)}")
    if not names:
        raise SetupError("no channels selected — with all four off the run has nothing to read.\n"
                         f"  Valid: {', '.join(OFFERED_CHANNELS)}")
    return {name: name in names for name in current}


# --------------------------------------------------------------------------------------------------
# The wizard
# --------------------------------------------------------------------------------------------------

def _key_present(provider_name: str) -> bool | None:
    """`True` / `False` for a provider that needs a key, `None` for one that doesn't (a local model).

    Goes through `core.llm.api_key_for`, which is the code the first run will use — including its
    `.env` read — so a "key found" here means the same thing it will mean then.
    """
    provider = PROVIDERS[provider_name]
    if provider.env_var is None:
        return None
    try:
        return bool(api_key_for(provider))
    except ConfigurationError:
        return False


def run(argv: list[str] | None = None, *,
        destinations: dict[str, Path] | None = None,
        example_dir: Path = EXAMPLE_DIR,
        ask: Callable[[str, str], str] | None = None,
        env: dict[str, str] | None = None,
        key_present: Callable[[str], bool | None] = _key_present,
        out: Callable[[str], None] = print) -> int:
    """The whole command. Returns a process exit code: 0 fine, 1 the config didn't validate, 2 bad answer.

    Everything the wizard touches is injectable — where it writes, what it asks, what the environment
    says, whether a key exists — so the suite drives it end to end against a temp directory with no
    network, no model and no key. `run()` with no arguments is what `python -m core.setup` does.
    """
    args = _parse_args(argv)
    env = dict(os.environ) if env is None else env
    dest = DESTINATIONS if destinations is None else destinations
    settings_path, profile_path = dest["settings.yaml"], dest["profile.yaml"]

    def prompt(field: str, question: str, default: str) -> str:
        """A flag or an env var, or the question, or the default. `--yes` never asks."""
        given = _given(args, field, env)
        if given is not None:
            return given.strip()
        if args.yes or ask is None and not sys.stdin.isatty():
            return default
        try:
            typed = (ask or _readline)(question, default).strip()
        except EOFError:                      # piped stdin that ran out: unattended, take the default
            return default
        return typed or default

    try:
        out("Setting up jobs-db. Nothing here is overwritten, and nothing is fetched.\n")

        # 1 — seed. The example is a complete configuration, so from here on every question is an edit
        # to a file that already loads rather than a field in a file being built up.
        out("1/4  Seeding from config/example/ — a complete configuration for a job seeker who does not exist:")
        written, skipped = seed(example_dir=example_dir, destinations=dest)
        for path in written:
            out(f"       wrote  {_rel(path)}")
        for path in skipped:
            out(f"       kept   {_rel(path)}  (already there — not overwritten)")
        out("")

        settings_text = settings_path.read_text(encoding="utf-8")
        profile_text = profile_path.read_text(encoding="utf-8")
        current = _read(settings_text, profile_text)

        # 2 — identity. Two values, and only because there is no defensible default for either.
        out("2/4  Who you are")
        name = prompt("name", "Your name", current["name"])
        email = prompt("email", "Your email address", current["email"])

        # 3 — the provider. Its key is *reported*, never demanded: a stranger who has not signed up
        # yet should still finish the wizard and read the line telling them what is missing.
        out("\n3/4  Which model provider  "
            f"({', '.join(f'{n} ({p.tier})' for n, p in sorted(PROVIDERS.items()))})")
        provider = prompt("provider", "Provider", current["provider"]).lower()
        if provider not in PROVIDERS:
            raise SetupError(f"unknown provider {provider!r}.\n  Valid: {', '.join(sorted(PROVIDERS))}")

        # 4 — channels, exhaustive, then the board tokens if `boards` survived.
        out("\n4/4  Which channels (comma-separated, and the list is exhaustive — anything you leave "
            "out is switched off)")
        for cname, blurb in OFFERED_CHANNELS.items():
            out(f"       {cname:<10} {blurb}")
        on_now = [c for c, on in current["channels"].items() if on and c in OFFERED_CHANNELS]
        chosen = _channel_choice(_split(prompt("channels", "Channels", ",".join(on_now))),
                                 current["channels"])
        greenhouse, lever = current["greenhouse"], current["lever"]
        if chosen.get("boards"):
            out("\n       Board tokens are the slug in the URL: job-boards.greenhouse.io/<token>, "
                "jobs.lever.co/<token>.")
            greenhouse = _split(prompt("greenhouse", "       Greenhouse tokens", ",".join(greenhouse)))
            lever = _split(prompt("lever", "       Lever tokens", ",".join(lever)))
    except SetupError as e:
        out(f"\nSetup stopped: {e}")
        return 2

    # Write. Every failure to place a value is reported by key rather than swallowed — the wizard's
    # setters only understand the shape the example ships, and a clone whose settings file has been
    # restructured by hand should be told which line to edit, not left believing it was answered.
    unplaced: list[str] = []
    profile_text = _apply(profile_text, unplaced, [
        (_PROFILE_NAME, name),
        (_PROFILE_CONTACT, email),
        (_PROFILE_INBOX, email),
    ])
    edits: list[tuple[tuple[str, ...], object]] = [(_LLM_PROVIDER, provider)]
    edits += [(("channels", c, "enabled"), on) for c, on in chosen.items()]
    settings_text = _apply(settings_text, unplaced, edits)
    settings_text = _apply(settings_text, unplaced, [
        (("channels", "boards", "greenhouse"), greenhouse),
        (("channels", "boards", "lever"), lever),
    ], lists=True)
    profile_path.write_text(profile_text, encoding="utf-8")
    settings_path.write_text(settings_text, encoding="utf-8")

    # Validate what was just written, through the same schema the first run will use. This is the
    # whole reason the wizard beats `cp` and an editor: a wrong value is named here, by key, now.
    try:
        validate(load(settings_path), settings_path)
    except ConfigurationError as e:
        out(f"\nThe settings file this wizard wrote does not validate. Nothing else was changed.\n{e}")
        return 1

    out(_summary(name=name, provider=provider, key=key_present(provider), chosen=chosen,
                 greenhouse=greenhouse, lever=lever, unplaced=unplaced,
                 settings_path=settings_path, profile_path=profile_path, rubric_path=dest["rubric.md"]))
    return 0


def _readline(question: str, default: str) -> str:
    return input(f"       {question} [{default}]: " if default else f"       {question}: ")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read(settings_text: str, profile_text: str) -> dict:
    """The seeded files' current answers, which are every question's default."""
    import yaml
    settings = yaml.safe_load(settings_text) or {}
    profile = yaml.safe_load(profile_text) or {}
    channels = settings.get("channels") or {}
    boards = channels.get("boards") or {}
    return {
        "name": str((profile.get("identity") or {}).get("name") or ""),
        "email": str((profile.get("inbox") or {}).get("account") or ""),
        "provider": str((settings.get("llm") or {}).get("provider") or "anthropic"),
        # An omitted channel block, or an omitted `enabled:`, means ON — the same reading
        # `triage/config.py` has always had. Deriving the default from `.get("enabled")` instead would
        # make the wizard offer "all off" to anyone whose settings file predates the channels block.
        "channels": {c: bool((channels.get(c) or {}).get("enabled", True)) for c in OFFERED_CHANNELS},
        "greenhouse": [str(t) for t in (boards.get("greenhouse") or [])],
        "lever": [str(t) for t in (boards.get("lever") or [])],
    }


def _apply(text: str, unplaced: list[str], edits: list, *, lists: bool = False) -> str:
    setter = set_list if lists else set_scalar
    for path, value in edits:
        updated = setter(text, tuple(path), value)
        if updated is None:
            unplaced.append(".".join(path))
        else:
            text = updated
    return text


def _summary(*, name: str, provider: str, key: bool | None, chosen: dict[str, bool],
             greenhouse: list[str], lever: list[str], unplaced: list[str],
             settings_path: Path, profile_path: Path, rubric_path: Path) -> str:
    on = [c for c, is_on in chosen.items() if is_on]
    lines = ["", "Done. Your configuration:", "",
             f"  you          {name}",
             f"  provider     {provider}" + ("" if key is None else
                                             "  — key found" if key else
                                             f"  — NO KEY: put {PROVIDERS[provider].env_var}=… in "
                                             f"{_rel(REPO_ROOT / '.env')} before the first run"),
             f"  channels     {', '.join(on)}"]
    if chosen.get("boards"):
        lines.append(f"  boards       greenhouse: {', '.join(greenhouse) or '(none)'} · "
                     f"lever: {', '.join(lever) or '(none)'}")
    lines += [f"  settings     {_rel(settings_path)}  (validated)",
              f"  identity     {_rel(profile_path)}"]
    if unplaced:
        lines += ["", "  Could not place these — your files are not the shape the example ships, so set",
                  "  them by hand: " + ", ".join(unplaced)]

    lines += [
        "",
        # The one thing the wizard refuses to fake, said where it cannot be missed. A rubric written
        # by a six-question form is worse than an honest borrowed one, because it looks finished.
        f"THE RUBRIC IS STILL THE EXAMPLE'S. {_rel(rubric_path)} is the file that decides every score,",
        "and right now it holds a fictional seeker's priorities, not yours. Two ways to fix that:",
        "",
        "  · run /setup in a coding agent — it reads your résumé and writes the rubric with you",
        "  · read docs/operating/rubric.md and edit the file — nothing parses it, so you cannot",
        "    break the tool by getting it wrong",
        "",
        "Not asked here, and worth a minute in " + _rel(profile_path) + ": your CV title, the",
        "agencies you rate (the shipped ones are invented), and your applied-jobs sheet.",
        "",
        "Now run something. This produces a scored worklist in matches/ and needs nothing else:",
        "",
        f"    {RUN_COMMAND}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":   # pragma: no cover - `run()` is what the tests drive
    raise SystemExit(run())
