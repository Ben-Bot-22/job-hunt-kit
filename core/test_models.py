"""`Analysis.held_back_reason` — the field the apply doc groups by.
Run:  .venv/bin/python -m pytest core/test_models.py -q

Added 2026-07-30 with work-life balance promoted to priority #2. It exists because `why` is one honest
free-text sentence per job and a page cannot group free text: "show me everything rejected because of
X" is the question `triage/worklist.py` now answers, and it can only answer it off a fixed vocabulary.

Three properties, each guarding a failure that is silent rather than loud:

  * it **defaults to empty**, so a scorer that ignores it, or a state file written before it existed,
    still loads — an added required field would have made every stored analysis unreadable;
  * it **round-trips through the state file**, because `--merge` re-renders the apply doc from disk
    and a reason lost there is a job that quietly leaves its group;
  * **all three copies** name the same tokens, exactly, in both directions — the schema description,
    `triage/analyze.py`'s HELD_BACK_REASON block, and `profile/rubric.md`, which is injected whole into
    the same prompt and is the authoritative one. Drift there is the nastiest failure: the model writes
    a word nobody grouped, the job lands in the catch-all, and nothing errors. Exact tokens rather than
    substring containment, because every token is a common English fragment ("rate" is inside
    "separate") and containment cannot see a token INVENTED in one copy either.

Vocabulary and reasoning: `profile/rubric.md` §THREE TIERS OF "NO",
`docs/knowledge-base/decision-work-life-balance-priority.md`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from .models import Analysis, Job, job_from_dict, job_to_dict
from .settings import is_example_profile, profile_exists

ROOT = Path(__file__).resolve().parent.parent
#: Read as text, not imported: `core/` may not import a leaf (`core/test_layering.py`).
ANALYZER = ROOT / "triage" / "analyze.py"
#: The third copy, and the authoritative one — it is what the scorer is actually handed. Owner-only:
#: no clone has a rubric until it is seeded, and the example seeker's does not carry this vocabulary.
RUBRIC = ROOT / "profile" / "rubric.md"

#: `travel` joined on 2026-08-04, when intensity stopped removing jobs and started sorting them.
#: It is the one hours criterion that is CHECKABLE — a stated percentage over 40 — which is why it
#: earns a token of its own rather than living under `intensity` with the inferred judgments.
VOCABULARY = {"intensity", "travel", "rate", "stack-gap", "role-shape", "years-bar", "non-us",
              "clearance", "no-content"}

owner_only = pytest.mark.skipif(
    not profile_exists() or is_example_profile(),
    reason="reads the owner's profile/rubric.md, which no clone carries and the example seeker's "
           "rubric does not define. Runs on the owner's own checkout.")


def _piped(text: str) -> set[str]:
    """The tokens of a `a | b | c` run — exact, so `rate` cannot pass by sitting inside `separate`.

    Substring containment was the original check and it was worthless in both directions: every token
    is a common English fragment, and a set that merely *contains* the vocabulary can also contain
    six invented ones nothing groups by.
    """
    runs = re.findall(r"[a-z][a-z-]+(?:\s*\|\s*[a-z][a-z-]+)+", text)
    return {t.strip() for run in runs for t in run.split("|")}


def _analysis(**kw) -> Analysis:
    base = dict(tier="PRIMARY", fit_score=72, intensity=3, verdict="FIT", why="in lane",
                role_summary="", meets_goals="")
    base.update(kw)
    return Analysis(**base)


def test_not_held_back_is_the_default():
    """The common case is the empty string, so nothing has to opt out of being held back."""
    assert _analysis().held_back_reason == ""


def test_an_analysis_stored_before_the_field_existed_still_loads():
    """Every judgment in `data/corpus/` predates this field. A required one would have made a month of
    accumulated scores unreadable — which is the state the whole precedent system runs on."""
    stored = _analysis().model_dump()
    del stored["held_back_reason"]
    assert Analysis(**stored).held_back_reason == ""


def test_the_reason_survives_the_state_file():
    """`--merge` re-renders the apply doc from disk, so a reason that does not round-trip is a job
    that silently moves to the catch-all between one render of the page and the next."""
    j = Job(link="https://x.test/1", company="Startupco", title="Founding Engineer")
    j.analysis = _analysis(intensity=5, held_back_reason="intensity")
    assert job_from_dict(job_to_dict(j)).analysis.held_back_reason == "intensity"


def test_it_is_part_of_the_scorers_output_schema():
    """Unlike `analysis_errored`, this one belongs on `Analysis`: naming the gate that fired is a
    judgment about the JD, and the scorer is the only thing that read the JD."""
    assert "held_back_reason" in Analysis.model_json_schema()["properties"]


def test_the_schema_and_the_analyzer_prompt_offer_the_same_vocabulary():
    """The drift that fails soft, checked in BOTH directions and on exact tokens.

    The prompt tells the model which tokens to choose from and the schema description is what reaches
    it alongside; a token in one and not the other produces a reason nothing groups by, with no error
    anywhere. Equality rather than containment because containment misses the direction that actually
    bites — a token invented in the prompt and unknown to `triage/worklist.py`'s grouping. Unmarked:
    both copies are checked-in code, so this is a rule about the repo and runs on any clone.
    """
    assert _piped(Analysis.model_fields["held_back_reason"].description) == VOCABULARY

    prompt = ANALYZER.read_text(encoding="utf-8")
    instruction = prompt.split("HELD_BACK_REASON")[1].split("RED FLAGS")[0]
    assert _piped(instruction) == VOCABULARY, (
        "triage/analyze.py's HELD_BACK_REASON block and Analysis.held_back_reason disagree about the "
        "vocabulary the apply doc groups by")


@owner_only
def test_the_rubric_offers_the_same_vocabulary_as_the_schema():
    """The third copy, and the one the model is most likely to believe.

    `profile/rubric.md` is injected whole into the same system prompt as the hardcoded HELD_BACK_REASON
    block, so the two are read together and a token in one and not the other is not staleness — it is
    two instructions arguing inside one prompt. The rubric is authoritative over anything an agent
    remembers (AGENTS.md), so if this goes red the rubric is right and the schema is wrong.
    """
    tiers = RUBRIC.read_text(encoding="utf-8").split('THREE TIERS OF "NO"')[1].split("CALIBRATION")[0]
    #: Backticked because that is how the rubric spells them; `""` is the not-held-back sentinel and
    #: is deliberately not a vocabulary member — nothing groups under it.
    listed = {t for t in re.findall(r"`([a-z][a-z-]+)`", tiers)}
    assert listed == VOCABULARY, (
        "profile/rubric.md §THREE TIERS OF \"NO\" and core/models.py disagree about the vocabulary "
        "the apply doc groups by — the rubric is authoritative, so fix the schema and the prompt")
