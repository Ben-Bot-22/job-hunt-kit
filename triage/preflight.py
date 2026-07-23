"""Preflight — say what didn't run, what it cost, and the one command that fixes it.

The tool degrades quietly. Every accessor in `config.py` except `goal_profile()` carries a default,
so a stranger who has seeded the example but configured nothing gets a full worklist of confident
scores against a *fictional person*, a missing contract lane, or silently degraded tier ranking — and
the only signal today is a bare count like `boards 0`, which is honest and useless: it names no
consequence and no fix.

This module is the single source of that judgment. `check()` reads the loaded config and returns a
list of `Finding`s; three call sites render the same list at the three moments a user actually looks:

  1. **before any fetch or spend** — `__main__._phase1` prints it first, so "your scores will be
     fiction" arrives *before* the Opus bill, not after. It warns and continues, always — blocking
     would break the tier-0 demo, whose whole point is that a seeded example runs.
  2. **the run summary** — a `⤷ preflight:` line beside the channel counts, so the consequence sits
     next to the count that caused it.
  3. **the worklist header** — a CRITICAL finding renders a banner *on the page*, because the worklist
     is read hours later when the terminal output is gone.

Pure: no model call, no network, no disk write. The one read it does — the rubric, to compare it to
the example's — is the same file `goal_profile()` already caches. That keeps it fully unit-testable,
which matters because a preflight that rots is worse than none: it would vouch for a broken config.
"""
from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from core.llm import api_key_for, resolve_provider
from core.settings import REPO_ROOT

from . import config

# The example rubric ships at a fixed path regardless of `JOBSDB_CONFIG_HOME` — it is the thing every
# unconfigured checkout is compared *against*, including the demo (whose PROFILE_DIR points here, so
# the demo correctly warns that its scores are the fictional seeker's).
_EXAMPLE_RUBRIC = REPO_ROOT / "config" / "example" / "rubric.md"


class Severity(Enum):
    """CRITICAL: the output is wrong, not merely thin. DEGRADED: a lane is missing. NOTE: self-resolving."""
    CRITICAL = "⚠ CRITICAL"
    DEGRADED = "⤷ degraded"
    NOTE = "⤷ note"


class Finding(NamedTuple):
    severity: Severity
    what: str   # what is missing or wrong
    cost: str   # what it costs this run
    fix: str    # the one thing to do about it

    def line(self) -> str:
        return f"{self.severity.value}: {self.what} — {self.cost}  → {self.fix}"


def _rubric_is_example() -> bool:
    """Is the scoring rubric still byte-identical to the shipped example's?

    The check that matters most: an unwritten rubric is not thin, it is *someone else's* — every score
    is calibrated to a fictional seeker. Compared by content, not by path, so it fires whether the user
    seeded the example into `profile/` or is running the demo via `JOBSDB_CONFIG_HOME`.
    """
    try:
        return config.RUBRIC_PATH.read_text(encoding="utf-8") == _EXAMPLE_RUBRIC.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A missing rubric is `goal_profile()`'s job to raise on, loudly, at scoring time. Missing is
        # not "still the example's", so this check stays quiet and lets that louder failure own it.
        return False


def _missing_provider_key() -> tuple[str, str] | None:
    """`(provider, env_var)` when the configured provider needs a key that is not set, else None.

    Resolved through `core.llm` rather than by reading an environment variable here, so the provider
    registry stays the single source of truth about which key a provider needs: a user who switches
    `llm.provider` to openai, google or a keyless local ollama gets the right answer without this
    file knowing anything about them.

    Never raises. A preflight that throws while explaining what is wrong is worse than no preflight,
    so an unknown provider name stays `resolve_provider`'s error to raise at the real call site.
    """
    try:
        provider = resolve_provider()
    except Exception:
        return None
    if provider.env_var is None:        # ollama, and anything else that needs no key
        return None
    try:
        api_key_for(provider)           # reads the repo-root `.env` too, so an unexported key counts
    except Exception:
        return provider.name, provider.env_var
    return None


def check() -> list[Finding]:
    """Everything wrong with the loaded config, worst first. Reads config only — no I/O beyond the rubric."""
    out: list[Finding] = []

    # First, because it is the likeliest thing to be missing on a first run and the tool used to report
    # it in the worst available way: without a key every job was fetched and screened before scoring
    # failed, printing this same paragraph once per job — 63 times in a measured run, after the wait.
    # One line, before anything is fetched.
    if (missing := _missing_provider_key()):
        provider, env_var = missing
        out.append(Finding(
            Severity.CRITICAL,
            f"{env_var} is not set (llm.provider is '{provider}')",
            "every job is fetched and screened, then fails to score — the run writes no usable verdicts",
            f"put `{env_var}=...` in .env at the repo root (copy .env.example), or export it — or set "
            "llm.provider in config/settings.yaml to a provider whose key you have",
        ))

    if _rubric_is_example():
        out.append(Finding(
            Severity.CRITICAL,
            "the scoring rubric is still the example seeker's",
            "every fit score is calibrated to a fictional person, not to you",
            "run /setup (it writes the rubric with you), or edit profile/rubric.md — see docs/operating/rubric.md",
        ))

    # A "standing" source produces jobs on a bare run with no per-run arguments. `paste` needs URLs on
    # argv and `mail` is macOS-only, so the two that a stranger on any OS can rely on are `boards`
    # (needs tokens) and `agencies` (needs enabling). With neither, an unattended run finds nothing and
    # nothing says why.
    tokens = config.board_tokens()
    boards_live = config.channel_enabled("boards") and (tokens["greenhouse"] or tokens["lever"])
    agencies_live = config.channel_enabled("agencies")
    if not boards_live and not agencies_live:
        out.append(Finding(
            Severity.DEGRADED,
            "no standing job source (boards has no tokens, agencies is off)",
            "a run with nothing pasted finds nothing — mail is macOS-only, paste needs URLs",
            "name boards in config/settings.yaml (see starter-boards.md), or enable the agencies channel",
        ))

    if not config.primary_agencies() and not config.secondary_platforms():
        out.append(Finding(
            Severity.DEGRADED,
            "no primary_agencies or secondary_platforms in profile.yaml",
            "channel-tier ranking falls back to the model's guess — agency/platform tiers degrade",
            "list the agencies and platforms you rate in profile/profile.yaml",
        ))

    if config.channel_enabled("mail") and not config.archive_mailbox():
        out.append(Finding(
            Severity.NOTE,
            "mail is on but archive_mailbox is unset",
            "processed job mail archives to the default 'jobs-triage' label",
            "set archive_mailbox in profile/profile.yaml to choose the label",
        ))

    if not (config.CORPUS_DIR / "seen.json").exists():
        out.append(Finding(
            Severity.NOTE,
            "no corpus yet (first run)",
            "precedent scoring contributes nothing until this run is recorded — it self-resolves next run",
            "nothing to do — run the tool",
        ))

    return out


def format_block(findings: list[Finding]) -> str:
    """The pre-run stdout block. Empty string when the config is clean, so the caller prints nothing."""
    if not findings:
        return ""
    lines = ["", "PREFLIGHT — what is missing before this run, and how to fix it:"]
    lines += [f"  {f.line()}" for f in findings]
    return "\n".join(lines)


def summary_line(findings: list[Finding]) -> str | None:
    """The one-line count for the run summary, or None when clean.

        preflight: 1 critical · 2 degraded (see the block above)
    """
    if not findings:
        return None
    counts = {sev: sum(1 for f in findings if f.severity is sev) for sev in Severity}
    parts = [f"{counts[sev]} {sev.name.lower()}" for sev in Severity if counts[sev]]
    return "preflight: " + " · ".join(parts)


def worklist_banner(findings: list[Finding]) -> str | None:
    """A banner for the worklist page — CRITICAL findings only, because the page outlives the terminal.

    DEGRADED/NOTE are operational and belong in the run summary; a worklist banner is reserved for the
    one thing that makes the scores on the page untrustworthy — the rubric not being the reader's.
    """
    critical = [f for f in findings if f.severity is Severity.CRITICAL]
    if not critical:
        return None
    body = "\n".join(f"- {f.what} — {f.cost}. {f.fix}" for f in critical)
    return ("> **⚠ These scores may not be about you.**\n>\n"
            + "\n".join(f"> {ln}" for ln in body.splitlines()))
