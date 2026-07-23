"""Tests for retrieval-augmented scoring — what reaches the analyzer, and what must not.

Offline, no API key, no model: the index is built over fixture records with the deterministic
stand-in embedder from `core/test_retrieval.py`, so these run in milliseconds and assert on the
**assembled prompt**, which is the highest seam that still shows the whole behaviour.

The failure directions being guarded, in order of what they'd cost:

  * A precedent injected as authority. `Linda Werner — Project Coordinator III` is in the real corpus
    at 82 STRONG_FIT and `profile/rubric.md` says that score was wrong. It retrieves. The block has to hand
    it over as evidence *and* say in words that the goal profile outranks it.
  * A prefilter kill offered as judgment — telling the scorer it decided something a regex decided.
  * A job retrieved as its own precedent, which on the phase-3 re-analysis would anchor a score to
    the score being revised.
  * A broken index taking the morning run down with it.

Run:  .venv/bin/python -m pytest triage/ -q
"""
from __future__ import annotations

import pytest

from core.index import JobIndex, build_documents
from core.models import Job
from core.test_retrieval import FakeEmbedder     # a shared fixture, not a leaf reaching into a leaf
from . import config, precedent
from .analyze import user_message


def _rec(company, title, jd, **analysis):
    rec = {"company": company, "title": title, "fetched_jd": jd, "link": f"https://x/{title}"}
    if analysis:
        rec["analysis"] = {"verdict": "FIT", "fit_score": 70, "tier": "PRIMARY", **analysis}
    return rec


# The real mis-score, pinned: this record is in the corpus, it retrieves for agency/contract queries,
# and `profile/rubric.md`'s CALIBRATION block says of that exact job "-> LOW_FIT (was WRONGLY scored 82)".
COORDINATOR = _rec(
    "Linda Werner & Associates", "Project Coordinator III – AI Workflows and Vibe Coding",
    "Remote coordinator role. Status reporting, onboarding, weekly activity docs. Vibe coding, Claude Code.",
    verdict="STRONG_FIT", fit_score=82, why="Remote, AI-native, vibe-coding workflows.", is_agency=True,
    employment_type="contract", cadence="remote")

# Three near-identical agency postings of one client req — what MMR exists to collapse.
REACT_TRIO = [
    _rec("TEKsystems", "Senior React Developer",
         "Remote contract React TypeScript Node role for a financial client. 6 months, $70/hr.",
         verdict="FIT", fit_score=74, why="Remote React contract, rate clears the floor."),
    _rec("Insight Global", "Senior React Engineer",
         "Remote contract React TypeScript Node role for a financial client. 6 months, $70/hr.",
         verdict="FIT", fit_score=72, why="Same req under a second agency name."),
    _rec("Apex Systems", "React Developer - Remote",
         "Remote contract React TypeScript Node role for a financial client. 6 months, $70/hr.",
         verdict="FIT", fit_score=71, why="Remote React contract, known rate."),
]

NEXTJS = _rec(
    "TMS LLC", "Senior Full Stack Engineer – AI & Next.js",
    "Remote long-term. Next.js App Router required; React experience alone is insufficient. 10+ years.",
    verdict="LOW_FIT", fit_score=45, why="Mandatory Next.js gap plus a 10+yr bar; AI overlap doesn't rescue it.",
    employment_type="contract", cadence="remote")

FIXTURES = [COORDINATOR, NEXTJS] + REACT_TRIO


def _index(tmp_path, records=FIXTURES):
    idx = JobIndex(tmp_path / "index.json", embedder=FakeEmbedder())
    idx.add(build_documents(records))
    return idx


def _job(title="Senior React Developer", company="Robert Half", jd="Remote contract React TypeScript role."):
    return Job(link="https://x/new", title=title, company=company, fetched_jd=jd, jd_source="full")


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """`for_job` reads a process-wide index; point it at the fixtures."""
    monkeypatch.setattr(precedent, "_index", _index(tmp_path))
    monkeypatch.setattr(precedent, "_index_failed", False)


# --- what reaches the model ---------------------------------------------------------------------------

def test_precedents_reach_the_assembled_prompt(wired):
    job = _job()
    prompt = user_message(job, precedent.for_job(job))
    assert "PAST DECISIONS ON SIMILAR JOBS" in prompt
    assert "TEKsystems" in prompt or "Insight Global" in prompt or "Apex Systems" in prompt
    assert "JOB DESCRIPTION:\nRemote contract React TypeScript role." in prompt


def test_no_precedents_still_produces_a_valid_prompt():
    """Day one for a stranger with no history: byte-for-byte the message this tool sent before."""
    job = _job()
    assert user_message(job, "") == user_message(job)
    assert "PAST DECISIONS" not in user_message(job, "")
    assert "TITLE: Senior React Developer" in user_message(job, "")


def test_a_precedent_carries_the_verdict_and_the_reasoning_not_just_a_number(wired):
    """A bare score invites anchoring. The verdict plus the one-line why is what lets the model see
    that a precedent contradicts the rubric."""
    text = precedent.for_job(_job(title="Project Coordinator II", company="Werner",
                                  jd="Remote coordinator, status reporting and onboarding docs, vibe coding."))
    assert "STRONG_FIT 82/100" in text
    assert "why: Remote, AI-native, vibe-coding workflows." in text


def test_the_block_says_the_rubric_outranks_the_precedent(wired):
    """The decision this whole ticket turns on. Without this sentence the block hands the scorer its
    own worst call with the authority of experience — the 82 above is a mistake the rubric corrects."""
    text = precedent.for_job(_job(title="Project Coordinator II", company="Werner",
                                  jd="Remote coordinator, status reporting, vibe coding."))
    assert "GOAL PROFILE ABOVE OUTRANKS EVERY PRECEDENT" in text
    assert "THE RULE WINS" in text
    assert "not to copy a score" in text


def test_the_block_carries_no_jd_text(wired):
    """Precedent is for consistency of reasoning. Three JDs would be ~4k un-cached tokens per job."""
    text = precedent.for_job(_job())
    assert "6 months, $70/hr" not in text


# --- diversity: three views of one req is not three precedents ----------------------------------------

def test_precedents_are_mutually_different(tmp_path):
    """The trio is one client req wearing three agency names. Returned whole, it reads as
    corroboration for a score that rests on a single job."""
    hits = precedent.find(_job(), idx=_index(tmp_path, REACT_TRIO + [COORDINATOR, NEXTJS]), k=3)
    agencies = {d.metadata["company"] for d in hits} & {"TEKsystems", "Insight Global", "Apex Systems"}
    assert len(agencies) < 3


# --- what must never be offered as precedent ----------------------------------------------------------

def test_the_job_is_not_its_own_precedent(tmp_path):
    """Phase 3 re-analyzes with the browser-fetched JD, and by then the job is in the index with its
    phase-1 score. Retrieving itself would anchor the revision to the number being revised."""
    same = _job(title="Senior React Developer", company="TEKsystems")
    hits = precedent.find(same, idx=_index(tmp_path), k=3)
    assert "TEKsystems" not in {d.metadata["company"] for d in hits}


def test_a_prefilter_kill_is_not_offered_as_a_judgment(tmp_path):
    """It carries an `analysis`, but a regex decided it. Handing it back as "how you judged this"
    teaches the scorer a judgment it never made."""
    killed = {**_rec("Dice", "Sr .NET Developer", "C# and .NET Core, onsite Dallas.",
                     verdict="SKIP", fit_score=0, why="prefilter: off-lane title"),
              "prefiltered": True}
    hits = precedent.find(_job(title="Sr .NET Developer", company="Insight Global", jd="C# .NET Core onsite"),
                          idx=_index(tmp_path, [killed, NEXTJS]), k=3)
    assert "Dice" not in {d.metadata["company"] for d in hits}


def test_a_legacy_prefilter_kill_without_the_flag_is_still_excluded(tmp_path):
    """Documents indexed before `prefiltered` was carried in metadata. The index is not rebuilt on a
    metadata-only change, so the `why` prefix is the check that covers them."""
    legacy = _rec("Dice", "Sr .NET Developer", "C# and .NET Core, onsite Dallas.",
                  verdict="SKIP", fit_score=0, why="prefilter: off-lane title")
    hits = precedent.find(_job(title="Sr .NET Developer", company="Insight Global", jd="C# .NET Core onsite"),
                          idx=_index(tmp_path, [legacy, NEXTJS]), k=3)
    assert "Dice" not in {d.metadata["company"] for d in hits}


def test_a_failed_analysis_is_not_offered_as_precedent(tmp_path):
    failed = _rec("Motion Recruitment", "Platform Engineer", "Remote contract Go and Kubernetes.",
                  verdict="SKIP", fit_score=0, why="analysis_error: overloaded_error")
    hits = precedent.find(_job(title="Platform Engineer", company="Apex", jd="Remote contract Go Kubernetes"),
                          idx=_index(tmp_path, [failed, NEXTJS]), k=3)
    assert "Motion Recruitment" not in {d.metadata["company"] for d in hits}


def test_an_unscored_record_is_not_offered_as_precedent(tmp_path):
    """A posting fetched but never judged has no verdict to be precedent for."""
    unscored = _rec("Robert Half", "React Developer", "Remote contract React TypeScript.")
    hits = precedent.find(_job(), idx=_index(tmp_path, [unscored, NEXTJS]), k=3)
    assert "Robert Half" not in {d.metadata["company"] for d in hits}


# --- memory is an enhancement, never a blocker --------------------------------------------------------

def test_an_empty_index_yields_no_block_and_does_not_raise(tmp_path):
    empty = JobIndex(tmp_path / "index.json", embedder=FakeEmbedder())
    assert precedent.find(_job(), idx=empty) == []
    assert precedent.block([]) == ""


def test_a_missing_index_scores_the_job_anyway(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(precedent, "_index", None)
    monkeypatch.setattr(precedent, "_index_failed", False)
    assert precedent.for_job(_job()) == ""


def test_a_retrieval_failure_scores_the_job_anyway(monkeypatch):
    """The whole daily run must not go down because a cache did. Proved by making it fail."""
    def boom(*a, **kw):
        raise RuntimeError("index is on fire")

    monkeypatch.setattr(precedent, "find", boom)
    assert precedent.for_job(_job()) == ""


def test_precedent_can_be_switched_off(wired, monkeypatch):
    """`precedent.enabled: false` restores pre-stage-2 scoring exactly, with no retrieval at all."""
    monkeypatch.setattr(config, "precedent_enabled", lambda: False)
    assert precedent.for_job(_job()) == ""
