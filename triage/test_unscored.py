"""A job the analyzer failed on must not be recorded as judged.  Run:  .venv/bin/python -m pytest triage/test_unscored.py -q

`seen.json` means *judged*, and a seen job never surfaces again. Until 2026-07-29 an analysis that raised
returned a `fit_score=0, verdict=SKIP` stub and the job was recorded as seen anyway, so it was both
unscored and permanently invisible. A monthly spend cap tripped mid-run and 134 jobs went that way;
recovery meant deleting 274 keys from seen.json by hand.

Three rules are pinned here, and the second is the one that is easy to break while fixing the first:

  1. an ERRORED job contributes no `seen` key, in any of the three key forms;
  2. a PREFILTERED job still does — the cheap gate is a real verdict, and un-seeing it means re-fetching
     and re-screening it on every run forever;
  3. the flag is set by the code that knows the call failed, never inferred from the `why` string.
"""
from __future__ import annotations

import json
from argparse import Namespace

import pytest

from . import __main__ as m
from .test_config import needs_profile
from . import prefilter
from core.models import Analysis, Job, job_from_dict, job_to_dict

RUN = "2026-07-29-090000"


def _job(company="Acme", title="Full Stack Developer", link="https://example.com/j/1", **kw):
    j = Job(link=link, company=company, title=title)
    j.analysis = Analysis(tier="PRIMARY", fit_score=71, intensity=3, verdict="FIT", why="in lane",
                          role_summary="", meets_goals="")
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def _errored(**kw):
    j = _job(**kw)
    j.analysis = Analysis(tier="OPPORTUNISTIC", fit_score=0, intensity=3, verdict="SKIP",
                          why="analysis_error: overloaded", role_summary="", meets_goals="",
                          red_flags=["analysis error"])
    j.analysis_errored = True
    return j


# --- rule 1: an errored job is not seen -------------------------------------------------------------

def test_an_errored_job_contributes_no_seen_key():
    j = _errored()
    j.duplicates = [{"id": "globex|backend engineer|", "link": "https://example.com/j/2"}]
    assert m._seen_keys([j]) == set()


def test_a_scored_job_still_records_all_three_key_forms():
    """The regression guard on the fix itself — excluding errored jobs must not thin the normal path."""
    j = _job()
    j.duplicates = [{"id": "globex|backend engineer|", "link": "https://example.com/j/2"}]
    assert m._seen_keys([j]) == {j.id, "globex|backend engineer|", "url:https://example.com/j/1"}


def test_one_errored_job_does_not_suppress_its_neighbours():
    good, bad = _job(), _errored(company="Globex", title="Backend Engineer", link="https://x.test/2")
    assert m._seen_keys([good, bad]) == {good.id, "url:https://example.com/j/1"}


# --- rule 2: the trap. a prefiltered job IS judged --------------------------------------------------

def test_a_prefiltered_job_is_still_seen():
    """It carries the same fit_score=0/SKIP shape as an error stub but was genuinely judged by the gate.
    Marking it unseen would re-fetch and re-screen it on every future run, forever."""
    j = _job()
    j.analysis = prefilter.skip_analysis("hard_skip: 12+ years experience required")
    j.prefiltered = True
    assert j.analysis_errored is False
    assert j.id in m._seen_keys([j])


# --- rule 3: the flag is set by the analyzer, not read off a string ---------------------------------

@needs_profile
def test_analyze_stamps_the_flag_on_failure_and_clears_it_on_success(monkeypatch):
    """`analyze` is the only writer, because it is the only code that knows whether the call worked.

    Needs a seeded profile: the model call is stubbed, but `analyze()` still builds its prompt, and
    the rubric is injected whole into it — with no `profile/rubric.md` the call takes the error path
    and returns the `fit_score=0` stub this test is asserting against. It passed on the owner's
    checkout from the day it was written (2026-07-30) and failed on every fresh clone until
    2026-08-06, which is exactly the gap the marker policy exists to close (docs/agents/tests.md).
    """
    from . import analyze as az

    j = _job()
    j.analysis_errored = True                       # a previous run's failure, still on the record

    monkeypatch.setattr(az.precedent, "for_job", lambda job: "")
    ok = Analysis(tier="PRIMARY", fit_score=80, intensity=2, verdict="STRONG_FIT", why="good",
                  role_summary="", meets_goals="")
    monkeypatch.setattr(az, "_analyze_model", lambda: type("M", (), {"invoke": lambda self, msgs: ok})())
    assert az.analyze(j).fit_score == 80
    assert j.analysis_errored is False              # a successful re-score is no longer errored

    def boom():
        raise RuntimeError("credit balance too low")
    monkeypatch.setattr(az, "_analyze_model", boom)
    a = az.analyze(j)
    assert j.analysis_errored is True
    assert a.verdict == "SKIP" and a.why.startswith("analysis_error:")


def test_the_flag_survives_the_state_file():
    """It has to round-trip, or `--merge` cannot tell which jobs to pick up."""
    j = _errored()
    assert job_from_dict(job_to_dict(j)).analysis_errored is True
    assert job_from_dict(job_to_dict(_job())).analysis_errored is False


def test_errored_is_not_part_of_the_scorers_output_schema():
    """The failure flag must never be a field the model fills in — it cannot know whether the call died,
    and putting it on `Analysis` would put it in the structured-output schema of every scoring call."""
    assert "errored" not in Analysis.model_json_schema()["properties"]


# --- the worklist says so, because nothing else will ------------------------------------------------

def test_the_worklist_separates_unscored_jobs_from_rejected_ones():
    from .worklist import render

    text = render([_job(company="Globex", title="Backend Engineer", link="https://x.test/2"),
                   _errored(company="Insight Global", title="Software Engineer")],
                  days=3, skipped_pre=0)
    assert "NOT SCORED" in text
    assert "Insight Global" in text.split("NOT SCORED")[1]
    # and it is NOT presented as a rejection — that would be a judgment nobody made. Named off the
    # constant since 2026-07-30, when the two refusal sections merged into one: a literal here went
    # green by matching a heading that no longer exists.
    from .worklist import REVIEW_HEADING
    assert REVIEW_HEADING not in text


# --- item 3: --merge is the resume path, and there is no --resume flag ------------------------------

def _wire(tmp_path, monkeypatch, jobs, jds=None, scored=None):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir(); runs.mkdir()
    monkeypatch.setattr(m.config, "CORPUS_DIR", corpus)
    monkeypatch.setattr(m.config, "RUNS_DIR", runs)
    monkeypatch.setattr(m, "_LATEST", runs / "latest-run.txt")
    monkeypatch.setattr(m.precedent, "refresh", lambda: 0)

    def _default(job):
        job.analysis_errored = False
        return Analysis(tier="PRIMARY", fit_score=64, intensity=3, verdict="FIT",
                        why="scored on the retry", role_summary="", meets_goals="")
    monkeypatch.setattr(m, "analyze", scored or _default)

    p = m._paths(RUN)
    p["state"].write_text(json.dumps({"days": 3, "skipped_pre": 0,
                                      "jobs": [job_to_dict(j) for j in jobs]}))
    p["browser_jds"].write_text(json.dumps(jds or {}))
    return p


def test_merge_picks_up_a_job_whose_analysis_errored(tmp_path, monkeypatch):
    """No new flag: 'pick up where the run left off' is a predicate on the phase that already re-scores."""
    j = _errored()
    p = _wire(tmp_path, monkeypatch, [j])

    m._phase3_merge(Namespace(out=None), RUN)

    (reloaded,) = [job_from_dict(d) for d in json.loads(p["state"].read_text())["jobs"]]
    assert reloaded.analysis_errored is False
    assert reloaded.analysis.fit_score == 64
    # and only NOW is it seen — phase 1 deliberately left it out
    assert reloaded.id in set(json.loads(m.store.seen_path().read_text()))


def test_a_resumed_job_that_fails_again_stays_unseen(tmp_path, monkeypatch):
    """The retry is idempotent: a spend cap that is still in force must not consume the second chance."""
    def still_broken(job):
        job.analysis_errored = True
        return Analysis(tier="OPPORTUNISTIC", fit_score=0, intensity=3, verdict="SKIP",
                        why="analysis_error: credit balance too low", role_summary="", meets_goals="")

    j = _errored()
    p = _wire(tmp_path, monkeypatch, [j], scored=still_broken)

    m._phase3_merge(Namespace(out=None), RUN)

    (reloaded,) = [job_from_dict(d) for d in json.loads(p["state"].read_text())["jobs"]]
    assert reloaded.analysis_errored is True
    assert not m.store.seen_path().exists() or reloaded.id not in set(json.loads(m.store.seen_path().read_text()))


def test_merge_does_not_re_score_a_job_that_already_has_a_judgment(tmp_path, monkeypatch):
    """Resume means resume. A successfully scored job is not re-billed by running `--merge` again."""
    calls = []

    def counting(job):
        calls.append(job.id)
        return job.analysis
    _wire(tmp_path, monkeypatch, [_job()], scored=counting)

    m._phase3_merge(Namespace(out=None), RUN)
    assert calls == []


def test_there_is_no_resume_flag(monkeypatch):
    """Explicitly decided: resume is a predicate on `--merge`, not a second interface to maintain.

    The owner asked to resume by *asking* — one path that re-scores whatever has no judgment yet, whether
    the reason was a walled JD or a failed call. A `--resume` flag would be a second resume mechanism to
    keep in step with the first.
    """
    monkeypatch.setattr("sys.argv", ["triage", "--resume"])
    with pytest.raises(SystemExit):
        m._args()


# --- item 4: checkpoints ----------------------------------------------------------------------------

def test_scoring_persists_before_it_finishes(tmp_path, monkeypatch):
    """A crash at job 300 of 358 used to lose 300 judgments. Now they are already on disk."""
    monkeypatch.setattr(m.config, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(m.config, "max_workers", lambda: 1)
    monkeypatch.setattr(m, "_CHECKPOINT_EVERY", 2)

    jobs = [_job(company=f"Co{i}", title="Full Stack Developer", link=f"https://x.test/{i}")
            for i in range(5)]
    state = tmp_path / "state-test.json"

    def _process(job):
        if job.company == "Co4":
            raise RuntimeError("spend cap")
        return job
    monkeypatch.setattr(m, "_process", _process)

    with pytest.raises(RuntimeError):
        m._score_all(jobs, state, days=3, skipped_pre=0)

    survived = [job_from_dict(d) for d in json.loads(state.read_text())["jobs"]]
    assert [j.company for j in survived] == ["Co0", "Co1", "Co2", "Co3"]
    assert {j.id for j in survived} <= set(json.loads(m.store.seen_path().read_text()))


def test_a_checkpoint_does_not_mark_an_errored_job_seen(tmp_path, monkeypatch):
    """Items 2 and 4 interact: flushing early must not flush the exclusion away with it."""
    monkeypatch.setattr(m.config, "CORPUS_DIR", tmp_path)
    monkeypatch.setattr(m.config, "max_workers", lambda: 1)
    monkeypatch.setattr(m, "_CHECKPOINT_EVERY", 1)
    monkeypatch.setattr(m, "_process", lambda job: job)

    bad = _errored(company="Insight Global", link="https://x.test/9")
    m._score_all([_job(), bad], tmp_path / "state-test.json", days=3, skipped_pre=0)

    keys = set(json.loads(m.store.seen_path().read_text()))
    assert bad.id not in keys and "url:https://x.test/9" not in keys
