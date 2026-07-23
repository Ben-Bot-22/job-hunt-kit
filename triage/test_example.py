"""A fresh clone runs end to end against the shipped example, and produces a real worklist.
Run:  .venv/bin/python -m pytest triage/ -q

`core/test_example.py` asserts that `config/example/` is a complete, valid, fictional configuration.
This file asserts the thing that actually matters about it: **the pipeline runs on it**. Phase 1 in
full — the channel registry, the blocklist, the prefilter's regex gates, ranking, and the worklist
renderer — driven against `config/example/` exactly as `JOBSDB_CONFIG_HOME` would point it, with
nothing on disk from the repo owner's own configuration in the loop.

Four things are faked, all of them for the same reason — this test must run offline, with no key, on
a machine that has never downloaded an embedding model — and each of them has its own tests
elsewhere: the JD scrape and the paste backfill (`test_paste.py`), the Sonnet screen
(`test_prefilter.py`), the scorer (`test_analyze.py`), the semantic dedup gate (`test_dedup.py`), the
liveness check (`test_liveness.py`) and the precedent index (`test_precedent.py`). What is *not*
faked is everything the example is being asserted about: which channels ran, which config values they
ran on, which rubric the scorer would have been handed, and the file that comes out the far end.

The failure directions, in the order they cost something:

  * **The shipped demo not running at all.** This is a stranger's first five minutes, and there is
    nobody for them to ask. A config key renamed, a channel default flipped, a path constant moved —
    each of them breaks the demo silently, because nothing else in the suite runs the whole phase.
  * **The example reaching the repo owner's data.** The demo run must not read his inbox, his
    skiplist, his corpus or his rubric. `mail` being off is asserted here as behaviour (the channel is
    never called) rather than as a config value.
  * **A run that "succeeds" and writes nothing.** Producing real output is the acceptance criterion,
    so the worklist is read back and the jobs are found in it by name.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.models import Analysis, Job
from core.settings import REPO_ROOT
from core import settings as core_settings

from . import applied, channels, config, dedup, liveness, precedent, prefilter, store
from . import __main__ as main
from .channels import paste

EXAMPLE_DIR = REPO_ROOT / "config" / "example"

# Two postings on two different boards, standing in for whatever a stranger pastes first. Short JDs on
# purpose: this is a demo, not a scoring test, and the prefilter's regex gates must not fire on them.
_URLS = ["https://job-boards.greenhouse.io/northwind/jobs/1001",
         "https://jobs.lever.co/harborview/2f0a1b22-0000-4c31-9a20-0badc0ffee00"]

_JDS = {
    _URLS[0]: ("Northwind Analytics is hiring a Backend Engineer, Data Platform. Remote (US), "
               "permanent. $145,000-$165,000. Python, PostgreSQL, Airflow, AWS."),
    _URLS[1]: ("Harborview Logistics — Senior Data Analyst, Python & SQL. Remote (US). "
               "$120,000-$140,000. Dashboards, ad-hoc analysis, stakeholder reporting."),
}

_BACKFILLED = {
    _URLS[0]: ("Northwind Analytics", "Backend Engineer, Data Platform", "greenhouse"),
    _URLS[1]: ("Harborview Logistics", "Senior Data Analyst, Python & SQL", "lever"),
}

# What the example rubric says these two are — Northwind is its worked STRONG_FIT case and Harborview
# its worked LOW_FIT one, so the fake scorer returns the judgments the shipped anchor argues for.
_SCORES = {
    "Northwind Analytics": (90, "STRONG_FIT", "PRIMARY"),
    "Harborview Logistics": (35, "LOW_FIT", "OPPORTUNISTIC"),
}


@pytest.fixture(autouse=True)
def _dont_leak_the_example_into_the_rest_of_the_suite():
    """Three `lru_cache`s hold a parsed configuration, and `monkeypatch` can restore a path but not a
    cache. Without this, every test that runs after this file sees the example's settings — which is
    how `mail: enabled: false` silently switches a channel off in someone else's test."""
    yield
    core_settings.settings.cache_clear()
    config.profile.cache_clear()
    config.goal_profile.cache_clear()


def _fake_fetch(job: Job) -> Job:
    job.fetched_jd, job.jd_source = _JDS[job.link], "full"
    return job


def _fake_backfill(job: Job) -> Job:
    job.company, job.title, job.source_platform = _BACKFILLED[job.link]
    return job


def _fake_analyze(job: Job) -> Analysis:
    score, verdict, tier = _SCORES[job.company]
    return Analysis(tier=tier, fit_score=score, intensity=2, verdict=verdict,
                    why=f"example run — {job.title}", role_summary=job.title,
                    meets_goals="remote, permanent, band posted", employment_type="permanent",
                    cadence="remote")


class _Args:
    """`argparse.Namespace` as `_phase1` reads it, with the example's own paste URLs on argv."""
    days = None
    limit = None
    sample = None
    paste = _URLS
    paste_file = None
    channels = None          # no `--channels`, so the example's own config enables decide
    out = None
    no_archive = False
    no_browser = False


def _run_example_phase1(tmp_path: Path, monkeypatch) -> tuple[Path, list]:
    """Phase 1, against `config/example/`, writing everything into `tmp_path`. Returns (worklist, calls).

    `calls` records every channel the registry actually invoked, which is how "mail is off" is checked
    as behaviour rather than as a line of YAML.
    """
    # --- point the whole tool at the example, both halves, the way JOBSDB_CONFIG_HOME does ----------
    monkeypatch.setattr(core_settings, "SETTINGS_PATH", EXAMPLE_DIR / "settings.yaml")
    monkeypatch.setattr(config, "PROFILE_PATH", EXAMPLE_DIR / "profile.yaml")
    monkeypatch.setattr(config, "RUBRIC_PATH", EXAMPLE_DIR / "rubric.md")
    monkeypatch.setattr(store, "SKIPLIST", EXAMPLE_DIR / "skiplist.md")
    core_settings.settings.cache_clear()
    config.profile.cache_clear()
    config.goal_profile.cache_clear()

    # --- a fresh clone's empty working memory, not this machine's month of judgments ---------------
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "CORPUS_DIR", tmp_path / "corpus")
    monkeypatch.setattr(store, "SEEN", tmp_path / "corpus" / "seen.json")
    monkeypatch.setattr(applied, "APPLIED", tmp_path / "corpus" / "applied.json")
    monkeypatch.setattr(main, "_LATEST", tmp_path / "runs" / "latest-run.txt")
    (tmp_path / "runs").mkdir()
    (tmp_path / "corpus").mkdir()

    # --- the four things that would touch the network, a key, or a downloaded model ----------------
    calls: list[str] = []
    real_paste = paste.fetch

    def _paste(days, sample=None):
        calls.append("paste")
        return real_paste(days, sample, fetch_jd=_fake_fetch, backfill=_fake_backfill)

    def _boards(days, sample=None):
        # The real channel would make two keyless HTTP calls to the boards named in the example. It is
        # exercised live in test_boards.py; here it stands in as an enabled channel that returns
        # nothing, which is the `boards 0` case the counts line has to tell apart from `off`.
        calls.append("boards")
        return []

    def _mail(days, sample=None):
        calls.append("mail")
        raise AssertionError("the example must never read a mailbox")

    monkeypatch.setitem(channels.ALL, "paste", _paste)
    monkeypatch.setitem(channels.ALL, "boards", _boards)
    monkeypatch.setitem(channels.ALL, "mail", _mail)
    monkeypatch.setattr(prefilter, "cheap_screen", lambda job: (True, ""))
    monkeypatch.setattr(main, "analyze", _fake_analyze)
    monkeypatch.setattr(dedup, "collapse", lambda jobs: jobs)
    monkeypatch.setattr(liveness, "annotate", lambda jobs: {})
    monkeypatch.setattr(precedent, "refresh", lambda: 0)

    main._phase1(_Args(), "2026-01-15-090000")
    return tmp_path / "runs" / "worklist-2026-01-15-090000.md", calls


# --------------------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------------------

def test_the_shipped_example_produces_a_real_worklist(tmp_path, monkeypatch) -> None:
    """**The acceptance criterion, as a test.** Clone, point at the example, get scored jobs.

    Not "it didn't raise": the worklist is read back and both postings are found in it, ranked, with
    the verdicts the example rubric's own worked cases argue for. A phase that wrote an empty file
    would pass a smoke test and fail a stranger.
    """
    worklist, _ = _run_example_phase1(tmp_path, monkeypatch)

    assert worklist.exists()
    text = worklist.read_text()
    assert "Northwind Analytics" in text and "Harborview Logistics" in text
    # Ranked, not merely listed: the STRONG_FIT case comes first.
    assert text.index("Northwind Analytics") < text.index("Harborview Logistics")

    state = json.loads((tmp_path / "corpus" / "state-2026-01-15-090000.json").read_text())
    assert [j["company"] for j in state["jobs"]] == ["Northwind Analytics", "Harborview Logistics"]
    assert state["days"] == 7                       # window_days from the example, not the real config


def test_the_example_run_never_reaches_a_mailbox(tmp_path, monkeypatch) -> None:
    """`mail` is macOS-only and wants a configured Apple Mail account. A stranger has neither.

    Asserted as behaviour — the channel function is never called — because `enabled: false` in a YAML
    file is a claim about config and this is a claim about the run. `channel_enabled` defaults to ON
    for an unconfigured channel, so the example carrying the flag is load-bearing.
    """
    _, calls = _run_example_phase1(tmp_path, monkeypatch)
    assert "mail" not in calls
    assert calls == ["boards", "paste"]             # registry order, and gmail never runs either


def test_the_counts_line_tells_off_from_supplied_nothing(tmp_path, monkeypatch) -> None:
    """The health line a first-time user reads. `mail off` and `boards 0` must not look the same.

    Failure direction: a stranger who turned a channel off seeing the same `0` as a stranger whose
    channel ran and rotted, and having no way to tell which of the two they are looking at.
    """
    _run_example_phase1(tmp_path, monkeypatch)
    line = channels.counts_line(channels.LAST_RUN)
    assert "mail off" in line and "gmail off" in line
    assert "boards 0" in line and "paste 2" in line


def test_the_example_settings_are_the_ones_in_force(tmp_path, monkeypatch) -> None:
    """The values the run actually used, pinned — the example is config, and config is what it teaches.

    `max_workers` is deliberately below the repo owner's 12: a stranger's first afternoon earning 429s
    from a provider they signed up to an hour ago is a worse first run than a slower one.
    """
    _run_example_phase1(tmp_path, monkeypatch)
    assert config.window_days() == 7
    assert config.max_workers() == 5
    assert config.channel_enabled("mail") is False
    assert config.channel_enabled("gmail") is False
    assert config.board_tokens() == {
        "greenhouse": ["stripe", "databricks", "mongodb", "gitlab", "cloudflare", "anthropic"],
        "lever": ["gopuff"]}
    assert config.applied_sheet() == "" and config.archive_mailbox() == ""


def test_the_scorer_would_have_been_handed_the_example_rubric(tmp_path, monkeypatch) -> None:
    """The anchor is the whole product. A demo run scored against the repo owner's rubric would rank
    a fictional seeker's jobs by a real person's priorities and look entirely plausible doing it."""
    _run_example_phase1(tmp_path, monkeypatch)
    rubric = config.goal_profile()
    assert rubric == (EXAMPLE_DIR / "rubric.md").read_text(encoding="utf-8")
    assert "PERMANENT, salaried" in rubric and "$50/hr HARD FLOOR" not in rubric


def test_the_example_skiplist_is_the_one_that_blocks(tmp_path, monkeypatch) -> None:
    """A fresh clone's dedup state is the example's, and it is read: Tessellate Labs is on Robin's
    skiplist, so a paste of it is dropped before any fetch or model call.

    Failure direction: the demo reading the repo owner's skiplist, which is a list of jobs *he*
    rejected and has nothing to do with the run being demonstrated.
    """
    monkeypatch.setattr(store, "SKIPLIST", EXAMPLE_DIR / "skiplist.md")
    blocked = store.load_skiplist()
    assert "tessellate labs|staff platform engineer|" in blocked
    assert not any("toptal" in b for b in blocked)
