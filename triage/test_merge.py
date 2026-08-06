"""Phase 3 (`--merge`) persistence.  Run:  .venv/bin/python -m pytest triage/test_merge.py -q

`--merge` exists to replace a thin-JD judgment with one made on the real JD, pulled through the browser.
Until 2026-07-29 it wrote only the worklist: `worklist-2026-07-29-144502.md` correctly re-scored an
Insight Global req to SKIP 8 on its actual .NET JD while `state-2026-07-29-144502.json` still held
`jd_source='title_only'`, an empty `fetched_jd` and the old LOW_FIT 52. The corpus therefore kept the
exact judgment the browser step was run to replace — and since `core/index.py` builds the precedent
index from that file, the better judgment never became precedent either.

These tests assert the round trip: what Phase 3 re-scored survives being written and re-read.
"""
from __future__ import annotations

import json
from argparse import Namespace

from . import __main__ as m
from core.models import Analysis, job_from_dict, job_to_dict, Job

RUN = "2026-07-29-144502"


def _analysis(verdict="LOW_FIT", score=52, why="thin JD"):
    return Analysis(tier="PRIMARY", fit_score=score, intensity=3, verdict=verdict, why=why,
                    role_summary="", meets_goals="")


def _wire(tmp_path, monkeypatch, jobs, jds, scored=None):
    """Point both phases' directories at tmp_path and stub the two things that cost money/downloads."""
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir(); runs.mkdir()
    monkeypatch.setattr(m.config, "CORPUS_DIR", corpus)
    monkeypatch.setattr(m.config, "RUNS_DIR", runs)
    monkeypatch.setattr(m, "_LATEST", runs / "latest-run.txt")
    # The index is a cache and needs a real embedding model; the analyzer is a paid call.
    monkeypatch.setattr(m.precedent, "refresh", lambda: 0)
    monkeypatch.setattr(m, "analyze", scored or (lambda job: _analysis("SKIP", 8, "primary stack .NET")))

    p = m._paths(RUN)
    p["state"].write_text(json.dumps({"days": 3, "skipped_pre": 11,
                                      "jobs": [job_to_dict(j) for j in jobs]}))
    p["browser_jds"].write_text(json.dumps(jds))
    return p


def _reload(p):
    return [job_from_dict(d) for d in json.loads(p["state"].read_text())["jobs"]]


def test_merge_persists_the_rescored_judgment_and_the_fetched_jd(tmp_path, monkeypatch):
    """The Insight Global case, end to end: the state file must hold the merge's result, not phase 1's."""
    job = Job(link="https://example.com/j/1", company="Insight Global", title="Software Engineer")
    job.analysis = _analysis()
    jd = "Senior .NET engineer. C#, ASP.NET, SQL Server. " * 5      # >= the 120-char merge threshold
    p = _wire(tmp_path, monkeypatch, [job], {job.id: jd})

    m._phase3_merge(Namespace(out=None), RUN)

    (reloaded,) = _reload(p)
    assert reloaded.jd_source == "full"
    assert reloaded.fetched_jd == jd.strip()
    assert reloaded.analysis.verdict == "SKIP" and reloaded.analysis.fit_score == 8


def test_merge_preserves_the_run_header_so_a_second_merge_is_not_a_downgrade(tmp_path, monkeypatch):
    """`days`/`skipped_pre` are the run's own metadata — rewriting state must not reset them to defaults."""
    job = Job(link="https://example.com/j/1", company="Acme", title="Full Stack Developer")
    job.analysis = _analysis()
    p = _wire(tmp_path, monkeypatch, [job], {job.id: "x" * 200})

    m._phase3_merge(Namespace(out=None), RUN)

    state = json.loads(p["state"].read_text())
    assert state["days"] == 3 and state["skipped_pre"] == 11


def test_merge_leaves_untouched_jobs_alone(tmp_path, monkeypatch):
    """A job with no browser JD keeps phase 1's judgment — the merge is additive, never a rewrite."""
    merged = Job(link="https://example.com/j/1", company="Acme", title="Full Stack Developer")
    merged.analysis = _analysis()
    other = Job(link="https://example.com/j/2", company="Globex", title="Backend Engineer")
    other.analysis = _analysis("FIT", 71, "solid but perm")
    p = _wire(tmp_path, monkeypatch, [merged, other], {merged.id: "y" * 200})

    m._phase3_merge(Namespace(out=None), RUN)

    by_id = {j.id: j for j in _reload(p)}
    assert by_id[other.id].analysis.fit_score == 71
    assert by_id[other.id].jd_source == "title_only" and not by_id[other.id].fetched_jd
    assert by_id[merged.id].analysis.fit_score == 8


def test_merge_with_no_browser_jds_still_round_trips_the_state_file(tmp_path, monkeypatch):
    """The no-op merge must not truncate or drop the corpus it just read."""
    job = Job(link="https://example.com/j/1", company="Acme", title="Full Stack Developer")
    job.analysis = _analysis()
    p = _wire(tmp_path, monkeypatch, [job], {})

    m._phase3_merge(Namespace(out=None), RUN)

    (reloaded,) = _reload(p)
    assert reloaded.analysis.fit_score == 52 and reloaded.company == "Acme"


def test_merge_ignores_a_jd_too_thin_to_be_a_jd(tmp_path, monkeypatch):
    """Below the 120-char floor the browser fetched a wall or a spinner, not a JD. Don't spend a call."""
    job = Job(link="https://example.com/j/1", company="Acme", title="Full Stack Developer")
    job.analysis = _analysis()
    p = _wire(tmp_path, monkeypatch, [job], {job.id: "Sign in to continue"})

    m._phase3_merge(Namespace(out=None), RUN)

    (reloaded,) = _reload(p)
    assert reloaded.jd_source == "title_only" and reloaded.analysis.fit_score == 52


def test_merge_reapplies_the_archive_plan_phase_1_computed(tmp_path, monkeypatch):
    """Phase 1 computes which mail was held back from archiving (a human-named sender) and renders it
    in the worklist, but until 2026-07-31 only `archive-<run>.txt` (the archivable list) was persisted
    — the held-back list lived only in that one rendered file. `--merge` rewrites the worklist from
    the state file alone, so every merge silently dropped the HELD BACK section, with no error and no
    trace. Phase 1 now also writes `archive-plan-<run>.json`; merge must reload it and pass it through."""
    job = Job(link="https://example.com/j/1", company="Acme", title="Full Stack Developer")
    job.analysis = _analysis()
    p = _wire(tmp_path, monkeypatch, [job], {})
    p["archive_plan"].write_text(json.dumps({
        "rows": [],
        "held": [{"mid": "abc", "sender": "Jane Recruiter <jane@agency.test>",
                  "subject": "Following up", "n_jobs": 1, "context": "Acme — Full Stack Developer",
                  "reason": "sender names a person: Jane Recruiter"}],
    }))

    m._phase3_merge(Namespace(out=None), RUN)

    rendered = p["worklist"].read_text()
    assert "HELD BACK" in rendered and "Jane Recruiter" in rendered
