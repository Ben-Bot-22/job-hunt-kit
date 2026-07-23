"""Tests for the dated snapshots and the trend gate.  Run:  .venv/bin/python -m pytest research/ -q

Offline: no key, no network, no model. The disk half writes into `tmp_path`, and the gate is pure
arithmetic over hand-built snapshots.

Two failure directions are worth more than the rest of this file put together, and both are about
believing a number:

  * **history lost.** A run that overwrites last month's numbers cannot be noticed later — the file
    looks fine, it is just the only one. Every trend this feature will ever draw depends on files
    written before anyone wanted a trend.
  * **a trend that should not exist.** Fifteen days over six runs, or a line drawn across a rubric
    edit, is cheap to compute and confidently wrong. The rubric is the most-edited file in this repo,
    and both it and the deleted pipeline's own scorer emit `STRONG_FIT`, so nothing downstream would
    complain about the join.
"""
from __future__ import annotations

import json

from core.test_retrieval import FakeEmbedder

from .retrospective import build as build_retrospective
from .snapshots import (MIN_DAYS, MIN_SNAPSHOTS, PREFIX, Snapshot, fingerprint, load, snapshot,
                        trend, write)

RUBRIC = "Score contract-first, remote-only. A 10 is a remote contract at $100/hr."
OTHER_RUBRIC = "Score permanent roles first. A 10 is a staff role at a product company."


def _rec(n: int = 0, *, jd: str = "Pay: $90/hr", **analysis) -> dict:
    """One corpus-shaped record, matching `research/test_retrospective.py`'s fixture."""
    return {
        "link": f"https://example.test/jobs/{n}",
        "company": f"Company {n}",
        "title": "Senior Full Stack Developer",
        "fetched_jd": jd,
        "jd_source": "full",
        "_run": "2026-07-20-094851",
        "analysis": {"employment_type": "contract", "cadence": "remote", "is_agency": False,
                     "red_flags": ["Permanent role, not contract"], "resume_keywords": ["Python"],
                     **analysis},
    }


def _snap(as_of: str, rubric: str = "r1", **metrics) -> Snapshot:
    base = {"postings": 100.0, "jd_read": 90.0, "rate_share_all_postings": 0.30,
            "rate_median_all_postings": 75.0, "share_employment_type_permanent": 0.71}
    return Snapshot(as_of=as_of, rubric=rubric, postings=int(base["postings"]),
                    metrics={**base, **metrics})


# --- accumulation ---------------------------------------------------------------------------------

def test_each_run_writes_its_own_dated_file_and_leaves_the_earlier_ones_alone(tmp_path):
    """The load-bearing property of the whole ticket. A trend in October is made of files written in
    July by someone who had no trend section yet — one file overwritten every run is a feature that
    can never start."""
    write(_snap("2026-07-22"), tmp_path)
    write(_snap("2026-08-22", postings=140.0), tmp_path)

    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        f"{PREFIX}2026-07-22.json", f"{PREFIX}2026-08-22.json"]
    assert [s.as_of for s in load(tmp_path)] == ["2026-07-22", "2026-08-22"]
    assert load(tmp_path)[0].metrics["postings"] == 100.0


def test_rerunning_the_report_on_the_same_day_rewrites_that_day_only(tmp_path):
    """Same day, same numbers, one row — but July must survive an August re-run, and a second run in
    August must not leave two conflicting Augusts in the history."""
    write(_snap("2026-07-22"), tmp_path)
    write(_snap("2026-08-22", postings=140.0), tmp_path)
    write(_snap("2026-08-22", postings=145.0), tmp_path)

    loaded = load(tmp_path)
    assert [s.as_of for s in loaded] == ["2026-07-22", "2026-08-22"]
    assert loaded[-1].metrics["postings"] == 145.0


def test_an_unreadable_snapshot_is_skipped_rather_than_failing_the_report(tmp_path):
    """A truncated write or a hand-edit must not make the whole report a traceback. Skipping loses a
    row, which only makes the gate more likely to refuse — the safe direction."""
    write(_snap("2026-07-22"), tmp_path)
    (tmp_path / f"{PREFIX}2026-08-22.json").write_text("{not json", encoding="utf-8")
    (tmp_path / f"{PREFIX}2026-09-22.json").write_text(
        json.dumps({"version": 99, "as_of": "2026-09-22"}), encoding="utf-8")

    assert [s.as_of for s in load(tmp_path)] == ["2026-07-22"]


def test_other_files_in_the_reports_directory_are_not_read_as_snapshots(tmp_path):
    """`data/reports/` already holds benchmark output and will hold the rendered markdown. The prefix
    is what keeps a neighbour's file from arriving as a data point."""
    write(_snap("2026-07-22"), tmp_path)
    (tmp_path / "ba-analyze-after.json").write_text('{"version": 1, "as_of": "2026-01-01"}',
                                                    encoding="utf-8")
    (tmp_path / "market-report-2026-07-22.md").write_text("# Market report", encoding="utf-8")

    assert [s.as_of for s in load(tmp_path)] == ["2026-07-22"]


def test_a_snapshot_of_a_real_retrospective_round_trips_through_disk(tmp_path):
    """The seam ticket 08 will call: build -> snapshot -> write -> load, with the numbers intact."""
    r = build_retrospective([_rec(0), _rec(1, employment_type="permanent")], embedder=FakeEmbedder())
    write(snapshot(r, as_of="2026-07-22", rubric=fingerprint(RUBRIC)), tmp_path)

    back = load(tmp_path)[0]
    assert back.postings == 2 and back.jd_read == 2
    assert back.rubric == fingerprint(RUBRIC)
    assert back.metrics["share_employment_type_permanent"] == 0.5
    assert back.metrics["rate_median_all_postings"] == 90.0
    assert back.terms["resume_keywords"]["Python"] == 2


# --- which rubric produced these numbers ------------------------------------------------------------

def test_a_snapshot_records_the_rubric_that_produced_it_and_never_the_rubric_itself():
    """The fingerprint is the comparability key. The rubric text is a personal scoring prompt and the
    numbers directory is the kind of thing a user pastes into a bug report."""
    s = snapshot(build_retrospective([_rec(0)], embedder=FakeEmbedder()),
                 as_of="2026-07-22", rubric=fingerprint(RUBRIC))
    assert s.rubric and s.rubric != RUBRIC
    assert RUBRIC not in json.dumps(s.to_dict())


def test_reflowing_the_rubric_does_not_reset_the_trend_but_changing_its_words_does():
    """The rubric is the file in this repo edited most. A fingerprint that reset on a rewrap would
    teach whoever maintains it to stop touching it, which is the opposite of the point."""
    assert fingerprint(RUBRIC) == fingerprint(RUBRIC.replace(". ", ".\n\n  "))
    assert fingerprint(RUBRIC) != fingerprint(OTHER_RUBRIC)
    assert fingerprint("") == ""


# --- the gate --------------------------------------------------------------------------------------

def test_below_the_threshold_there_is_no_trend_and_the_reason_names_both_numbers():
    """Six runs over fifteen days is the corpus as it stands. The refusal has to say what it is
    waiting for, or the section reads as broken rather than as deliberate."""
    t = trend([_snap("2026-07-06"), _snap("2026-07-20")])

    assert not t.ok
    assert t.snapshots == 2 and t.days == 15
    assert f"at least {MIN_SNAPSHOTS} snapshots" in t.reason
    assert f"at least {MIN_DAYS} days" in t.reason


def test_enough_snapshots_but_not_enough_elapsed_time_still_refuses():
    """Either threshold alone is gameable: three snapshots inside one week is a trend claim resting
    on one week."""
    t = trend([_snap("2026-01-02"), _snap("2026-02-01"), _snap("2026-03-01")])
    assert not t.ok and t.days == MIN_DAYS - 1


def test_no_snapshots_at_all_says_so_rather_than_pretending_to_a_flat_line():
    t = trend([])
    assert not t.ok and "No comparable dated snapshots yet" in t.reason


def test_the_gate_opens_once_the_history_is_long_enough_and_the_deltas_are_the_measured_ones():
    """The other half of the gate: it has to actually open, or the accumulation is pointless."""
    t = trend([_snap("2026-01-01"), _snap("2026-02-01"),
               _snap("2026-03-01", postings=150.0, rate_share_all_postings=0.42)])

    assert t.ok and t.snapshots == 3 and t.days == MIN_DAYS
    rows = {r.label: r for r in t.rows}
    assert rows["Postings scored"].change == 50.0
    assert round(rows["Share stating a rate"].change, 4) == 0.12


def test_a_metric_absent_from_one_endpoint_is_skipped_rather_than_read_as_zero():
    """A section added in February has not fallen to zero in January — it did not exist."""
    old = Snapshot(as_of="2026-01-01", rubric="r1", metrics={"postings": 100.0})
    t = trend([old, _snap("2026-02-01"), _snap("2026-03-01")])

    assert t.ok
    assert [r.label for r in t.rows] == ["Postings scored"]


# --- the rubric boundary ------------------------------------------------------------------------------

def test_snapshots_from_two_rubrics_are_never_joined_into_one_trend():
    """The failure this gate exists for. Five snapshots over five months look like plenty; three of
    them were scored by a different prompt, and the join would measure the prompt edit while reading
    as a market movement — both rubrics emit the same verdict labels, so nothing else objects."""
    old = [_snap(d, rubric="old", postings=60.0) for d in ("2026-01-01", "2026-02-01", "2026-03-01")]
    new = [_snap(d, rubric="new", postings=200.0) for d in ("2026-04-01", "2026-05-01")]

    t = trend(old + new)

    assert not t.ok
    assert t.snapshots == 2 and t.excluded == 3 and t.rubrics == 2
    assert "different rubric" in t.reason


def test_a_trend_under_the_newest_rubric_ignores_the_older_ones_but_says_it_did():
    """The recovery case: enough history has accumulated since the rubric changed. The older
    snapshots are still excluded, and the report says how many, so nobody reads a two-month window as
    the whole record."""
    old = [_snap("2025-01-01", rubric="old"), _snap("2025-02-01", rubric="old")]
    new = [_snap(d, rubric="new") for d in ("2026-01-01", "2026-02-01")]
    new.append(_snap("2026-03-01", rubric="new", postings=150.0))

    t = trend(old + new)

    assert t.ok and t.snapshots == 3 and t.excluded == 2
    assert t.first == "2026-01-01" and t.last == "2026-03-01"


def test_a_snapshot_that_cannot_name_its_rubric_is_never_compared_with_anything():
    """Including another one like it. A row that cannot say what scored it is exactly what this gate
    is for, and pairing two unknowns is a guess that they match."""
    t = trend([_snap(d, rubric="") for d in ("2026-01-01", "2026-02-01", "2026-03-01")])

    assert not t.ok and t.excluded == 3
    assert "no rubric fingerprint" in t.reason
