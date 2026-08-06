"""The terminal front door — `python -m core.setup`, driven end to end against a fake empty tree.
Run:  .venv/bin/python -m pytest core/test_setup.py -q

Offline, no model, no key, and nothing written outside `tmp_path`: every destination the wizard writes
is injected, exactly as `core/test_example.py` injects `seed()`'s.

The failure directions, in the order they cost something:

  * **Overwriting a configured clone.** Someone re-runs the wizard to change one answer and loses a
    month of rubric. `seed()` owns that behaviour and is tested there; what is tested *here* is that
    the wizard does not route round it, and that it says what it kept.
  * **A configuration that doesn't load.** The whole reason this beats `cp` and an editor is that the
    settings file is validated before the command exits, with the offending key named. A wizard that
    exits 0 on a file the first run rejects has moved the failure to the worst possible moment.
  * **Answering a question and having the answer discarded.** Every prompt has a flag and an
    environment variable; if the two tables drift, `--yes` silently ignores what CI passed it.
  * **A channel switched on that nobody asked for.** Selection is exhaustive, the same rule as
    `triage --channels`, because the additive reading is the one where a first run reads a mailbox.
  * **A rubric written by a form.** The wizard must ship the example's rubric untouched and say so.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from .example import DESTINATIONS, EXAMPLE_DIR
from .setup import ENV_FOR, OFFERED_CHANNELS, RUN_COMMAND, _parse_args, run, set_list, set_scalar


@pytest.fixture()
def tree(tmp_path: Path) -> dict[str, Path]:
    """An empty clone: the six destinations, under `tmp_path`, none of them existing yet."""
    return {name: tmp_path / target.parent.name / name for name, target in DESTINATIONS.items()}


def _run(tree: dict[str, Path], argv: list[str], **kw) -> tuple[int, str]:
    lines: list[str] = []
    code = run(argv, destinations=tree, key_present=kw.pop("key_present", lambda p: True),
               out=lines.append, env=kw.pop("env", {}), **kw)
    return code, "\n".join(lines)


def _settings(tree: dict[str, Path]) -> dict:
    return yaml.safe_load(tree["settings.yaml"].read_text())


# --------------------------------------------------------------------------------------------------
# An empty clone to a configuration that loads
# --------------------------------------------------------------------------------------------------

def test_yes_takes_an_empty_tree_to_a_configuration_that_validates(tree) -> None:
    """`--yes` is the unattended path — CI, a scripted install, and this test. It asks nothing.

    Everything not given takes the example's value, so the file that lands is the shipped
    configuration with the answers edited in, and it goes through the real schema before exit 0.
    """
    code, output = _run(tree, ["--yes"])

    assert code == 0
    assert all(path.exists() for path in tree.values())
    from .settings import Settings, load, validate
    data = load(tree["settings.yaml"])
    assert validate(data, tree["settings.yaml"]) == data
    # Complete, not whittled down to the answers — minus what the code owns (`core.settings.OWNED_BY_CODE`).
    from .settings import OWNED_BY_CODE
    assert set(data) == set(Settings.model_fields) - OWNED_BY_CODE
    assert "wrote" in output


def test_it_never_overwrites_and_says_what_it_kept(tree) -> None:
    """The one behaviour that cannot be got wrong, checked at the wizard's own seam.

    `seed()` skips by default and `core/test_example.py` pins that. This asserts the wizard did not
    reach past it — a tuned rubric survives a second run, and the run *tells* you it survived rather
    than leaving you to diff.
    """
    tree["rubric.md"].parent.mkdir(parents=True, exist_ok=True)
    tuned = "IDEAL ROLE: the one I spent a month tuning\n"
    tree["rubric.md"].write_text(tuned)

    code, output = _run(tree, ["--yes"])

    assert code == 0
    assert tree["rubric.md"].read_text() == tuned
    assert "kept" in output and "rubric.md" in output


def test_the_rubric_that_lands_is_the_example_s_untouched(tree) -> None:
    """The wizard writes no rubric of its own, and points at the two paths that do it properly.

    Failure direction: a six-question form producing a plausible-looking rubric. It would score
    everything 70 and never be rewritten, because a file that exists does not ask to be written.
    """
    code, output = _run(tree, ["--yes"])

    assert code == 0
    assert tree["rubric.md"].read_text() == (EXAMPLE_DIR / "rubric.md").read_text()
    assert "docs/operating/rubric.md" in output and "/setup" in output


def test_it_ends_by_naming_the_command_that_produces_output(tree) -> None:
    """A setup that ends in a config file has not finished. This one ends in a run."""
    _, output = _run(tree, ["--yes"])
    assert RUN_COMMAND in output
    assert output.rstrip().endswith(RUN_COMMAND)


# --------------------------------------------------------------------------------------------------
# The answers, and where they land
# --------------------------------------------------------------------------------------------------

def test_the_answers_reach_both_halves_of_the_config(tree) -> None:
    """Identity to `profile.yaml`, operations to `settings.yaml` — the stage-4 split, kept."""
    code, _ = _run(tree, ["--yes", "--name", "Alex Kim", "--email", "alex@example.invalid",
                          "--provider", "openai", "--channels", "boards,paste",
                          "--greenhouse", "stripe, ramp", "--lever", "netflix"])

    assert code == 0
    profile = yaml.safe_load(tree["profile.yaml"].read_text())
    assert profile["identity"]["name"] == "Alex Kim"
    assert profile["inbox"]["account"] == "alex@example.invalid"
    settings = _settings(tree)
    assert settings["llm"]["provider"] == "openai"
    assert settings["channels"]["boards"]["greenhouse"] == ["stripe", "ramp"]
    assert settings["channels"]["boards"]["lever"] == ["netflix"]


def test_channel_selection_is_exhaustive(tree) -> None:
    """`--channels agencies` runs agencies and nothing else, matching `triage --channels`.

    Failure direction if it were additive: someone asks for contract supply on a first run and the
    `paste`/`boards` defaults come along, or worse, `mail` reads and re-archives a real inbox.
    """
    code, _ = _run(tree, ["--yes", "--channels", "agencies"])

    assert code == 0
    channels = _settings(tree)["channels"]
    assert channels["agencies"]["enabled"] is True
    assert [c for c in OFFERED_CHANNELS if channels[c]["enabled"]] == ["agencies"]


def test_gmail_is_never_offered_and_asking_for_it_says_why(tree) -> None:
    """It is a documented stub that *raises* when enabled — offering it would offer a crash.

    Named separately from the generic unknown-name error because someone who types `gmail` has read
    the schema and needs the reason, not a valid-values list.
    """
    assert "gmail" not in OFFERED_CHANNELS
    code, output = _run(tree, ["--yes", "--channels", "gmail"])
    assert code == 2
    assert "gmail" in output and "stub" in output
    assert _settings(tree)["channels"]["gmail"]["enabled"] is False


@pytest.mark.parametrize("argv, expected", [
    (["--channels", "agences"], "agences"),
    (["--channels", ""], "nothing to read"),
    (["--provider", "claude"], "claude"),
])
def test_a_bad_answer_is_one_line_naming_it_not_a_traceback(tree, argv, expected) -> None:
    """Exit 2, the offender quoted, and the valid set listed — how `config/settings.yaml` validates.

    Failure direction for the empty case specifically: all four channels off renders identically to a
    quiet morning, which is the confusion the per-channel health line exists to remove.
    """
    code, output = _run(tree, ["--yes", *argv])
    assert code == 2
    assert expected in output
    assert "Traceback" not in output


def test_the_provider_key_is_reported_and_never_demanded(tree) -> None:
    """A stranger who has not signed up yet still finishes the wizard, holding the exact next step.

    Failure direction: refusing to write a configuration until a key exists, which means the reader
    goes off to a signup page with nothing on disk and does not come back.
    """
    code, output = _run(tree, ["--yes"], key_present=lambda p: False)
    assert code == 0
    assert "ANTHROPIC_API_KEY" in output and ".env" in output

    code, output = _run(tree, ["--yes"], key_present=lambda p: None)   # ollama: no key exists to find
    assert code == 0 and "NO KEY" not in output


# --------------------------------------------------------------------------------------------------
# Non-interactive parity — the thing CI depends on
# --------------------------------------------------------------------------------------------------

def test_every_prompt_has_a_flag_and_an_environment_variable() -> None:
    """"Every prompt is skippable" is only true while the two tables agree.

    Failure direction: a question added with a flag and no env var, so a container that can pass
    environment but not argv silently takes a default for it.
    """
    flags = {name for name, _ in vars(_parse_args([])).items()}
    assert flags - {"yes"} == set(ENV_FOR)
    assert all(name.startswith("JOBSDB_SETUP_") for name in ENV_FOR.values())


def test_an_environment_variable_answers_a_prompt_and_a_flag_beats_it(tree) -> None:
    code, _ = _run(tree, ["--yes"], env={"JOBSDB_SETUP_NAME": "Env Person",
                                         "JOBSDB_SETUP_PROVIDER": "google"})
    assert code == 0
    assert yaml.safe_load(tree["profile.yaml"].read_text())["identity"]["name"] == "Env Person"
    assert _settings(tree)["llm"]["provider"] == "google"

    code, _ = _run(tree, ["--yes", "--name", "Flag Person"], env={"JOBSDB_SETUP_NAME": "Env Person"})
    assert yaml.safe_load(tree["profile.yaml"].read_text())["identity"]["name"] == "Flag Person"


def test_typed_answers_and_an_empty_line_taking_the_default(tree) -> None:
    """Interactive, with the reader's terminal faked: return `""` and you get the example's value."""
    answers = {"Your name": "Sam Rivera", "Channels": "paste"}
    code, _ = _run(tree, [], ask=lambda q, default: answers.get(q.strip(), ""))

    assert code == 0
    assert yaml.safe_load(tree["profile.yaml"].read_text())["identity"]["name"] == "Sam Rivera"
    channels = _settings(tree)["channels"]
    assert [c for c in OFFERED_CHANNELS if channels[c]["enabled"]] == ["paste"]
    # Untouched answers keep the example's, which is what "asks only what has no sensible default" means.
    assert _settings(tree)["llm"]["provider"] == "anthropic"


# --------------------------------------------------------------------------------------------------
# Validation, and the file surgery underneath it
# --------------------------------------------------------------------------------------------------

def test_a_settings_file_that_does_not_validate_exits_naming_the_key(tree) -> None:
    """The wizard's whole claim over `cp`. A pre-existing broken file is kept — and then rejected.

    Failure direction: exit 0 on a config the first run refuses, three minutes and one model call
    later, with the error attributed to whatever imported it.
    """
    tree["settings.yaml"].parent.mkdir(parents=True, exist_ok=True)
    tree["settings.yaml"].write_text("llm:\n  provider: anthropic\nmax_worker: 12\n")

    code, output = _run(tree, ["--yes"])

    assert code == 1
    assert "max_worker" in output and "max_workers" in output      # the did-you-mean line
    assert "not valid" in output


def test_the_comments_survive_the_edit(tree) -> None:
    """`config/example/settings.yaml` is more explanation than settings, and the explanation is the point.

    Failure direction: a load-edit-dump, which is one line of PyYAML and deletes all 55 comment lines —
    handing a reader who has just run the wizard a config with no documentation in it at all.
    """
    _run(tree, ["--yes", "--channels", "paste", "--provider", "ollama"])
    written = tree["settings.yaml"].read_text()
    original = (EXAMPLE_DIR / "settings.yaml").read_text()

    comments = [line for line in original.splitlines() if line.strip().startswith("#")]
    assert len(comments) > 40
    for line in comments:
        assert line in written


@pytest.mark.parametrize("path, value, expected", [
    (("llm", "provider"), "openai", "  provider: openai"),
    (("channels", "mail", "enabled"), True, "    enabled: true"),
])
def test_the_scalar_setter_edits_the_right_nesting_level(path, value, expected) -> None:
    """`enabled:` appears five times in the file; only the one under the named channel may move."""
    text = (EXAMPLE_DIR / "settings.yaml").read_text()
    out = set_scalar(text, path, value)
    assert out is not None and expected in out.splitlines()
    assert yaml.safe_load(out)["channels"]["gmail"]["enabled"] is False    # the others left alone


def test_a_key_the_file_does_not_have_is_reported_rather_than_invented(tree) -> None:
    """A clone whose settings have been restructured by hand gets told which line to edit.

    Both setters return `None` rather than appending, because a key appended at the wrong nesting
    level is a config that loads and does something else.
    """
    assert set_scalar("llm:\n  provider: anthropic\n", ("llm", "base_url"), "x") is None
    assert set_list("channels:\n  boards:\n    enabled: true\n",
                    ("channels", "boards", "greenhouse"), ["a"]) is None

    tree["settings.yaml"].parent.mkdir(parents=True, exist_ok=True)
    tree["settings.yaml"].write_text("llm:\n  provider: anthropic\n")
    code, output = _run(tree, ["--yes", "--channels", "paste"])
    assert code == 0
    assert "channels.paste.enabled" in output and "by hand" in output


def test_an_emptied_list_becomes_a_flow_empty_not_a_dangling_key(tree) -> None:
    """`lever:` with nothing under it parses as `None`, which the schema rejects as not-a-list."""
    out = set_list((EXAMPLE_DIR / "settings.yaml").read_text(), ("channels", "boards", "lever"), [])
    assert out is not None
    assert yaml.safe_load(out)["channels"]["boards"]["lever"] == []
