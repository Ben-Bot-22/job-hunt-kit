"""The config split: identity, operations, rubric, secrets — four homes, and the seams between them.
Run:  .venv/bin/python -m pytest triage/ -q

Everything here is offline and reads the repo's own shipped files. That is deliberate: this stage did
not write new logic so much as move 141 lines of one YAML file to three places, and the only thing
worth asserting about a move is that the values on the far side are the ones the pipeline has always
run on. The literals below are the live settings, pinned.

The failure directions, in the order they cost something:

  * **A silently changed rubric.** It is the anchor every job is scored against and it moved *whole*.
    A move that dropped a calibration case would not error — it would quietly re-open a mis-score Ben
    already corrected, and the only symptom is a worklist he stops trusting weeks later.
  * **A rubric edit taking the tool down.** This is the entire reason the rubric left YAML. It was a
    `>` folded block scalar in `triage/config.yaml`, so a typo in a *prompt* broke the load of the
    models, the window, the channel flags and the run. Nothing parses `profile/rubric.md`, and the
    test below writes bytes that are definitively invalid YAML into it to prove it.
  * **The folded-scalar defect surviving the move.** YAML folding was gluing six section headings onto
    the bullet beneath them, so the anchor Ben had written was not the anchor Opus was reading. The
    move fixes it, and the glued spellings are asserted absent by name so a future "tidy-up" that
    re-wraps the file can't quietly restore them.
  * **A settings key that reads as absent.** Every accessor carries an inline default, so a key that
    failed to make the move answers with a plausible number instead of an error. Stage 4 · 07 puts a
    schema over that; until then, pinning the live values is what catches it.
"""
from __future__ import annotations

import yaml

import pytest

from core.settings import ConfigurationError, is_example_profile, profile_exists

from . import config

# Two markers, because a clone that is not the owner's fails these for two different reasons — and a
# reader who runs `pytest -q` deserves to be told which. See docs/agents/tests.md for the whole policy;
# the short version is that a skip here is the suite working, not coverage quietly going missing.
#
#   needs_profile — nothing has been seeded yet, so `profile/` does not exist at all. The test reads
#                   profile.yaml or rubric.md directly and has no file to read.
#   owner_only    — this is not the owner's checkout. The assertions pin values only the owner has:
#                   the "$50/hr HARD FLOOR" rubric line, named mis-scores, a real inbox, and the
#                   operational numbers tuned against a year of real runs. Against Robin Doe they are
#                   not merely untrue, they are meaningless — there is nothing there to guard.
needs_profile = pytest.mark.skipif(
    not profile_exists(),
    reason="no profile/ yet — profile.yaml is your identity and rubric.md is the prose rubric every "
           "job is scored against. Seed them with `python -m core.example` (the demo seeker) or write "
           "your own with `python -m core.setup`.")
owner_only = pytest.mark.skipif(
    not profile_exists() or is_example_profile(),
    reason="pins the repo owner's tuned rubric/identity/settings; this clone carries the example "
           "profile, where those values do not exist. Runs on the owner's own checkout.")


# --------------------------------------------------------------------------------------------------
# Four homes, and nothing living in two of them
# --------------------------------------------------------------------------------------------------

def test_the_old_single_config_file_is_gone() -> None:
    """`triage/config.yaml` is not merely unused — it is absent, so nobody edits the dead copy."""
    assert not (config.TRIAGE_DIR / "config.yaml").exists()


@needs_profile
def test_identity_is_tracked_in_the_profile_directory() -> None:
    """Identity goes to `profile/`, which CLAUDE.md keeps in git — losing a tuned file is unrecoverable."""
    assert config.PROFILE_PATH.exists() and config.PROFILE_PATH.parent == config.PROFILE_DIR
    assert config.RUBRIC_PATH.exists() and config.RUBRIC_PATH.suffix == ".md"


@needs_profile
def test_neither_config_file_holds_the_other_halfs_keys() -> None:
    """The split has to be real, not nominal: one key in two files is one key that drifts.

    Failure direction: `max_workers` left behind in the profile file keeps answering after someone
    raises it in settings, and the run stays slow for a reason nothing prints.
    """
    identity = yaml.safe_load(config.PROFILE_PATH.read_text())
    operations = yaml.safe_load((config.REPO_ROOT / "config" / "settings.yaml").read_text())
    assert not set(identity) & set(operations)
    # `identity:` — the name, title and contact line on a rendered document — joined in ticket 05,
    # when `cv/scripts/make_cover_letter.py` stopped carrying one person's name as a module constant.
    assert set(identity) == {"identity", "inbox", "archive_mailbox", "applied_sheet",
                             "primary_agencies", "secondary_platforms"}
    assert "goal_profile" not in identity and "goal_profile" not in operations


@needs_profile
def test_no_secret_reaches_a_tracked_config_file() -> None:
    """Secrets stay in `.env`. Both config files are tracked, so a key pasted into one is published.

    Checked by shape rather than by key name, because the thing that gets committed by accident is a
    value someone pasted, not a field somebody designed.
    """
    for path in (config.PROFILE_PATH, config.REPO_ROOT / "config" / "settings.yaml"):
        text = path.read_text()
        assert "sk-ant-" not in text and "sk-proj-" not in text
        assert "API_KEY" not in text.replace("ANTHROPIC_API_KEY", "").replace(
            "OPENAI_API_KEY", "").replace("GOOGLE_API_KEY", "")   # the README's provider table, not a key


# --------------------------------------------------------------------------------------------------
# The values the pipeline runs on, pinned
# --------------------------------------------------------------------------------------------------

@owner_only
def test_operational_values_survived_the_move() -> None:
    """Every number `triage/config.yaml` supplied, from `config/settings.yaml` instead.

    Owner-only because these are the owner's tuned numbers, not the tool's defaults: the public
    snapshot ships the example's settings (a 7-day window, 5 workers — first-run values), so pinning
    3 and 12 here would fail on every clone but this one and say nothing true about the tool.
    """
    assert config.window_days() == 3
    assert config.model("analyze") == "claude-opus-4-8"
    assert config.model("extract") == "claude-sonnet-5"
    assert config.model("prefilter") == "claude-sonnet-5"
    assert config.max_workers() == 12
    assert (config.prefilter_enabled(), config.prefilter_screen_enabled()) == (True, True)
    assert (config.precedent_enabled(), config.precedent_k()) == (True, 3)
    assert (config.dedup_enabled(), config.dedup_similarity(),
            config.dedup_overlap(), config.dedup_min_jd_chars()) == (True, 0.95, 0.80, 500)
    assert (config.liveness_enabled(), config.liveness_max_check(),
            config.liveness_workers()) == (True, 60, 16)


def test_gmail_stays_off() -> None:
    """`gmail` is off in every shipped config — 05's stub raises, and an enabled stub prints
    `gmail CRASHED` every morning.

    Deliberately NOT owner-only, and deliberately the only channel this file asserts on. It is a rule
    about the code (the stub is unfinished and throws), so it holds for every user and every config.
    The four assertions that used to sit here — mail on, boards on, paste on, no board tokens — were a
    photograph of one person's settings: they stated no rule, and they failed the moment anybody
    configured anything, which is the first thing a new user does.
    """
    assert config.channel_enabled("gmail") is False


@owner_only
def test_identity_values_survived_the_move() -> None:
    """Every accessor answers with what is actually in `profile/profile.yaml`, and nothing defaults.

    **Read out of the file rather than spelled here**, which is the one change ticket 05 made to this
    test: it used to assert the inbox address and the applied-sheet id as literals, and this file
    ships — so the test protecting the identity split was itself two of the twelve leaks the standing
    scan found (`scripts/test_leaks.py`). Comparing against the file still catches the failure that
    matters, which is an accessor reading the wrong key and answering with its inline default: every
    one of these has a default, and every default fails one of the assertions below.
    """
    identity = yaml.safe_load((config.PROFILE_PATH).read_text(encoding="utf-8"))

    assert config.inbox() == identity["inbox"]
    assert "@" in config.inbox()["account"]           # not the `{}` default
    assert config.archive_mailbox() == identity["archive_mailbox"] != ""
    assert config.applied_sheet() == identity["applied_sheet"] != ""
    assert len(config.primary_agencies()) == len(identity["primary_agencies"]) > 0
    assert "teksystems" in config.primary_agencies()  # lower-cased on the way out, unlike the file
    assert "braintrust" in config.secondary_platforms()


# --------------------------------------------------------------------------------------------------
# The rubric
# --------------------------------------------------------------------------------------------------

@owner_only
def test_the_rubric_moved_whole() -> None:
    """The parts of the anchor that were tuned after a named mis-score, verbatim.

    Each of these is a line Ben wrote in response to a specific job the tool got wrong. A move that
    dropped one costs a correction, and nothing errors when it happens.
    """
    rubric = config.goal_profile()
    assert "$50/hr HARD FLOOR" in rubric
    assert "Linda Werner" in rubric and "was WRONGLY scored 82" in rubric
    assert "TMS LLC" in rubric and "React experience alone is insufficient" in rubric
    assert "Genesis10" in rubric and "THIS is the bar for 80+." in rubric
    for heading in ("IDEAL ROLE", "DOWNRANK", "SCORING DISCIPLINE", "CALIBRATION",
                    "HARD FILTERS", "CANDIDATE"):
        assert heading in rubric


@owner_only
def test_the_whole_file_is_the_prompt() -> None:
    """No front matter, no header to strip: what is on disk is what the analyzer is handed.

    Failure direction: someone adds a `# Rubric` title for GitHub's sake and the model reads it as an
    instruction, or someone adds a stripping step and the first real line goes with it.
    """
    assert config.goal_profile() == config.RUBRIC_PATH.read_text(encoding="utf-8")
    assert config.goal_profile().startswith("IDEAL ROLE (the 10/10 Ben is optimizing for):\n")


@owner_only
def test_the_folded_scalar_no_longer_glues_headings_to_bullets() -> None:
    """The bad indent, resolved by the move — pinned as the six exact strings it produced.

    In `triage/config.yaml` the rubric was a `>` folded block scalar, so any line at the base indent
    was folded onto the one before it with a space. Six section headings therefore arrived at the
    model as `CALIBRATION — ... SHOULD have been scored): - Genesis10, "Senior Full Stack ...`, and
    `- Permanent -> logged, below an equivalent contract.` was glued to the NON-ENGINEERING rule. The
    words were always right; the structure was not, and structure is what a heading is for.
    """
    rubric = config.goal_profile()
    assert "):\n- " in rubric                       # a heading, then its first bullet, on two lines
    assert "): - " not in rubric                    # the folded spelling
    assert "\n- Permanent -> logged, below an equivalent contract.\n- NON-ENGINEERING" in rubric
    assert "contract. - NON-ENGINEERING" not in rubric


def test_a_malformed_rubric_does_not_stop_the_tool_loading_its_config(tmp_path, monkeypatch) -> None:
    """**The whole reason the rubric left YAML.**

    The bytes below are not valid YAML by any reading — an unterminated quote, a tab indent, a stray
    `:` in a bare scalar. In the old file that content was a `goal_profile:` block and it would have
    taken `models:`, `window_days:`, `channels:` and the entire run down with it. Here it is text: the
    settings still load, the channels still answer, and the analyzer gets the rubric exactly as typed.
    """
    broken = 'IDEAL ROLE: "unterminated\n\tkey: [value\n  - and: a: bare: colon\n'
    path = tmp_path / "rubric.md"
    path.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(config, "RUBRIC_PATH", path)
    config.goal_profile.cache_clear()

    assert config.goal_profile() == broken
    # The operational half is untouched. WHICH model and WHICH channels is configuration — asserting
    # the values here would photograph one clone's settings; asserting that they still answer is the
    # rule this test exists for.
    assert config.model("analyze")
    assert isinstance(config.channel_enabled("mail"), bool)

    config.goal_profile.cache_clear()


def test_a_missing_rubric_is_loud(tmp_path, monkeypatch) -> None:
    """Missing is the one rubric failure that must not be tolerated.

    An empty anchor doesn't error anywhere downstream — it produces a full worklist of confidently
    wrong verdicts, which is worse than not running. The error names the path and the way out.
    """
    monkeypatch.setattr(config, "RUBRIC_PATH", tmp_path / "gone.md")
    config.goal_profile.cache_clear()
    with pytest.raises(ConfigurationError, match="scoring rubric"):
        config.goal_profile()
    config.goal_profile.cache_clear()
