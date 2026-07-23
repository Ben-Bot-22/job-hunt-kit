"""Tests for the report renderer.  Run:  .venv/bin/python -m pytest research/ -q

Offline, no key, no network, no model — the renderer is a pure function of numbers somebody else
computed, and a test that needed any of those would be testing the layer below it.

Everything here asserts on **what a reader would see**, because every acceptance criterion in this
ticket is about what the document says. The four load-bearing ones are the four ways a report can
mislead someone in a negotiation:

  * an external half that is missing and does not say so, read as a market report;
  * a federal ceiling bill rate printed as a wage (live on 2026-07-22, CALC+'s software-engineer
    median was $135.82/hr against BLS's $65.38/hr for the same occupation — 2.08x);
  * a model's predicted salary printed as an employer's offer;
  * third-party data printed without the attribution its terms require.

Band figures are verbatim from the live calls `research/test_baselines.py` pins.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.test_retrieval import FakeEmbedder

from .report import Baseline, build_report, render
from .retrospective import INBOX
from .snapshots import MIN_DAYS, MIN_SNAPSHOTS, Snapshot
from .sources import bls, calc, himalayas
from .sources._baseline import RateBand

# Live on 2026-07-22: 3,934 CALC+ rows for `software engineer`, and BLS SOC 15-1252 national.
CEILING = RateBand(
    source="calc", occupation="software engineer", scope="National", unit="hour", n=3934,
    period="MAS schedule prices, current", caveat=calc.CAVEAT, attribution=calc.ATTRIBUTION,
    is_ceiling=True, median=135.82, p25=107.60, p75=167.62, p90=207.39)

WAGE = RateBand(
    source="bls", occupation="Software Developers", scope="National", unit="hour", n=0,
    period="OEWS 2025", caveat=bls.CAVEAT, attribution=bls.ATTRIBUTION, median=65.38, p90=103.21)


def _rec(n: int = 0, *, jd: str = "Pay: $90/hr", company: str = "", **analysis) -> dict:
    """One corpus-shaped record, matching `research/test_retrospective.py`'s fixture."""
    return {
        "link": f"https://example.test/jobs/{n}",
        "company": company or f"Company {n}",
        "title": "Senior Full Stack Developer",
        "fetched_jd": jd,
        "jd_source": "full",
        "_run": "2026-07-20-094851",
        "analysis": {"employment_type": "contract", "cadence": "remote", "is_agency": False,
                     "red_flags": ["Permanent role, not contract"], "resume_keywords": ["Python"],
                     **analysis},
    }


def _report(baseline=None, records=None, **kwargs):
    return build_report(records if records is not None else [_rec(0), _rec(1, company="Alpha")],
                        baseline, embedder=FakeEmbedder(), **kwargs)


def _rendered(baseline=None, **kwargs) -> str:
    return render(_report(baseline, **kwargs))


# --- two halves, and the gap ---------------------------------------------------------------------

def test_the_document_has_two_explicitly_labelled_halves():
    """Conflating them is the trap the whole module is shaped around: one is a small sample drawn
    through channels this user chose, the other is a broad figure that knows nothing about them."""
    out = _rendered(Baseline(bands=[CEILING, WAGE], band_counts={"calc": 1, "bls": 1}))
    assert "## Part 1 — Your own inbox (first-party)" in out
    assert "## Part 2 — External baseline (third-party)" in out


def test_with_no_baseline_the_first_party_half_renders_whole_and_the_external_half_says_it_is_missing():
    """The acceptance criterion for a stranger with no keys and no network. Rendering nothing for the
    external half would leave a shorter document that reads as complete — the silent degradation that
    turns one inbox into 'the market'."""
    out = _rendered(None)

    assert "UNAVAILABLE" in out
    assert "no API key" in out                      # and says the upgrade needs only a network
    # ...while every first-party section is still there in full.
    for heading in ("Rate reality — all postings", "Rate reality — contract", "Supply shape",
                    "What the postings keep asking for", "Who's hiring — direct"):
        assert heading in out


def test_an_external_pull_that_returned_nothing_names_the_sources_that_failed():
    """Different from 'never collected', and the difference matters: this one is a source being
    down, and a report that printed the same sentence for both would hide a rotted source."""
    out = _rendered(Baseline(band_counts={"calc": 0, "bls": 0}))
    assert "UNAVAILABLE" in out
    assert "- `calc` — **nothing returned**" in out
    assert "- `bls` — **nothing returned**" in out


def test_one_baseline_source_failing_still_renders_the_other_and_says_which_is_missing():
    """The half-degraded case, which is the common one: BLS spends its 25-a-day quota and answers
    HTTP 200 with nothing. A heading that just vanished would read as an anchor nobody wanted."""
    out = _rendered(Baseline(bands=[CEILING], band_counts={"calc": 1, "bls": 0}))
    assert "$135.82/hr median of 3,934" in out
    assert "`bls` returned no data this run — this anchor is missing, not zero." in out


# --- the honest limits, rendered ------------------------------------------------------------------

def test_a_ceiling_rate_carries_its_caveat_next_to_the_figure_and_under_the_heading():
    """The most damaging thing this module could print is a federal ceiling bill rate as 'what the
    job pays' — it is fully burdened with the vendor's overhead, G&A, fringe and fee, and on
    2026-07-22 it was 2.08x the BLS wage for the same occupation."""
    out = _rendered(Baseline(bands=[CEILING], band_counts={"calc": 1}))

    figure_line = next(line for line in out.splitlines() if "135.82" in line)
    assert "CEILING" in figure_line and "not a wage" in figure_line
    assert calc.CAVEAT in out


def test_a_predicted_salary_is_labelled_as_predicted_wherever_it_is_printed():
    """Adzuna's salaries are a model's point estimate (100% `salary_is_predicted` on a live 50-row
    sample). Ticket 01 withholds them at the source; this is the second line of that defence, for any
    band that reaches a renderer flagged."""
    predicted = RateBand(
        source="adzuna", occupation="software engineer", scope="US", unit="year", n=50,
        period="last 3 days", median=150000.0,
        caveat="Adzuna salary figures are PREDICTED by Adzuna's own model, not posted by the employer.",
        attribution="Job data from Adzuna (https://www.adzuna.com)", is_predicted=True)

    out = render(_report(Baseline(bands=[predicted], band_counts={"adzuna": 1})))
    figure_line = next(line for line in out.splitlines() if "150,000" in line)
    assert "PREDICTED" in figure_line and "not a posted figure" in figure_line


def test_a_predicted_band_cannot_be_built_without_a_caveat_that_says_so():
    """Sibling to the ceiling validator, and for the same reason: the two ways a rate figure lies are
    'this is an upper bound' and 'this is a guess', and both have to travel with the number."""
    with pytest.raises(ValueError, match="predicted band"):
        RateBand(source="adzuna", occupation="x", scope="US", unit="year", n=1, period="now",
                 caveat="A salary figure.", attribution="Adzuna", is_predicted=True, median=1.0)


def test_attribution_appears_wherever_third_party_data_appears():
    """A terms-of-use obligation, so it is asserted rather than trusted. It is derived from the bands
    and the counts actually rendered — a caller cannot omit it by forgetting to pass it."""
    out = _rendered(Baseline(bands=[CEILING, WAGE], band_counts={"calc": 1, "bls": 1},
                             supply_counts={"himalayas": 97, "remotive": 0}))

    assert calc.ATTRIBUTION in out and bls.ATTRIBUTION in out
    assert himalayas.ATTRIBUTION in out
    # Remotive returned nothing, and crediting it would read as data this report does not have.
    assert "remotive.com" not in out


def test_no_third_party_data_means_no_attribution_section():
    """Crediting sources a run never used is its own kind of dishonesty — it implies coverage."""
    assert "### Attribution" not in _rendered(None)


def test_every_section_states_its_sample_size_and_window_and_calls_the_corpus_an_inbox():
    """Asserted over every section at once, so a section added later cannot ship without one. The
    `INBOX` clause is what stops a channel-supply artefact being generalised into a market claim."""
    report = _report(Baseline(bands=[CEILING], band_counts={"calc": 1}))
    out = render(report)
    r = report.retrospective

    for section in [*r.rates, *r.terms, *r.splits, *r.employers]:
        assert section.sample.describe() in out
    assert out.count(INBOX) >= len([*r.rates, *r.terms, *r.splits, *r.employers])


def test_external_supply_counts_are_never_presented_as_market_volume():
    """Adzuna is filtered to its classified ads (663 of 9,550 for `software engineer`) and Himalayas
    is capped at the newest 1,000 rows of a 95,456-job board. A bare count would read as the market."""
    out = _rendered(Baseline(bands=[CEILING], band_counts={"calc": 1},
                             supply_counts={"himalayas": 97, "adzuna": 22}))
    assert "not market volume" in out
    assert "- `himalayas` — 97" in out


def test_a_key_gated_source_at_zero_says_how_to_enable_it_not_that_it_broke(monkeypatch):
    """The warn-the-user path. On a fresh clone adzuna/jsearch/theirstack return nothing because no key
    is set, and the supply caveat's 'a zero is a broken source' is wrong for exactly them. So a keyed
    source at zero, with its key absent, must render as 'skipped — set <VARS> in .env … see .env.example'
    — the context and the fix — while a keyless zero (a rotted scraper) still reads as nothing returned."""
    # Simulate no keys directly: `key()` reloads the repo `.env`, which on the owner's machine has them.
    monkeypatch.setattr("research.sources.key", lambda name: "")

    out = _rendered(Baseline(bands=[CEILING], band_counts={"calc": 1},
                             supply_counts={"himalayas": 97, "adzuna": 0, "insightglobal": 0}))
    assert "- `adzuna` — skipped — set ADZUNA_APP_ID + ADZUNA_APP_KEY in .env" in out
    assert ".env.example" in out
    assert "https://developer.adzuna.com" in out
    # a keyless scraper at zero is still rot, not an unconfigured key
    assert "- `insightglobal` — **nothing returned**" in out


# --- the first-party half's own honesty -----------------------------------------------------------

def test_a_cluster_prints_the_spellings_behind_its_count():
    """Stage 2 paid for the clustering to be inspectable — every member carries its similarity to the
    label it was filed under. Printing the total alone throws that away and turns a broad cluster into
    a number nobody can argue with."""
    recs = ([_rec(i, red_flags=["Permanent role, not contract"]) for i in range(3)]
            + [_rec(9, red_flags=["Permanent, not contract"])])
    # The fake embedder groups by shared words, which is enough to make one cluster of two spellings.
    out = render(build_report(recs, embedder=FakeEmbedder()))
    assert "_also: Permanent, not contract 1_" in out


def test_a_truncated_list_says_what_it_left_out():
    """A top-N with no total reads as the whole answer, and the corpus has 1,498 red-flag clusters
    behind a top 30."""
    recs = [_rec(i, company=c) for i, c in enumerate(["Alpha", "Beta", "Gamma"])]
    out = render(build_report(recs, embedder=FakeEmbedder(), top_employers=2))
    assert "Showing the top 2 of 3 employers" in out


def test_a_slice_with_no_stated_rate_says_so_rather_than_printing_an_empty_table():
    """`RateReality` for `contract` over a permanent-only corpus is `n=0 of 0`. An empty table reads
    as zeroes to a skimming eye, and a missing section reads as an oversight."""
    out = render(build_report([_rec(0, jd="No pay information here")], embedder=FakeEmbedder()))
    assert "No posting in this slice stated a rate" in out


def test_an_empty_corpus_renders_a_document_rather_than_crashing():
    """A first run with nothing scored yet. Dividing by a zero denominator here would make the first
    thing a new user sees a traceback."""
    out = render(build_report([], embedder=FakeEmbedder()))
    assert "0 postings" in out and "UNAVAILABLE" in out


# --- the trend gate, as a reader sees it ------------------------------------------------------------

def _snap(as_of: str, rubric: str = "r1", **metrics) -> Snapshot:
    return Snapshot(as_of=as_of, rubric=rubric,
                    metrics={"postings": 100.0, "share_employment_type_permanent": 0.71, **metrics})


def test_below_the_snapshot_threshold_the_trend_section_refuses_and_says_why():
    """The corpus as it stands is 15 days over 6 runs. A section that simply vanished below the gate
    would be indistinguishable from a report with no trend section at all, and the reader would never
    learn that one is coming or what it is waiting for."""
    out = _rendered(None, snapshots=[_snap("2026-07-06"), _snap("2026-07-20")])

    assert "## Part 3 — Month over month" in out
    assert "**No trend is claimed.**" in out
    assert f"at least {MIN_SNAPSHOTS} snapshots" in out and f"at least {MIN_DAYS} days" in out
    assert "2 comparable snapshots spanning 15 days" in out


def test_a_report_with_no_snapshots_at_all_still_renders_the_trend_section():
    """The first run ever. Nothing has accumulated, and the honest output says so rather than
    omitting a heading the next report will grow."""
    out = _rendered(None)
    assert "## Part 3 — Month over month" in out
    assert "No comparable dated snapshots yet" in out


def test_snapshots_from_two_rubrics_are_never_joined_into_one_trend():
    """Five snapshots across five months, three of them scored by a different prompt. Both rubrics
    emit the same verdict labels, so nothing downstream would object to the join — the resulting line
    would measure a prompt edit and read as a market movement."""
    snaps = ([_snap(d, "old", postings=60.0) for d in ("2026-01-01", "2026-02-01", "2026-03-01")]
             + [_snap(d, "new", postings=200.0) for d in ("2026-04-01", "2026-05-01")])
    out = _rendered(None, snapshots=snaps)

    assert "**No trend is claimed.**" in out
    assert "3 snapshots were set aside" in out and "different rubric" in out
    assert "| metric |" not in out          # and no table was drawn anyway


def test_once_the_gate_opens_the_trend_prints_the_movement_in_the_right_units():
    """A share moving 71% -> 60% is 11 points, not -15%. Calling it a percentage change is true of a
    different quantity and makes a modest movement read as a large one."""
    out = _rendered(None, snapshots=[
        _snap("2026-01-01"), _snap("2026-02-01"),
        _snap("2026-03-01", postings=150.0, share_employment_type_permanent=0.60)])

    assert "**No trend is claimed.**" not in out
    assert "| Postings scored | 100 | 150 | +50 |" in out
    assert "| Permanent share of the inbox | 71% | 60% | -11 pts |" in out
    assert INBOX in out.split("## Part 3")[1]     # a movement in one inbox, still not the market


# --- purity -----------------------------------------------------------------------------------------

def test_rendering_is_a_pure_function_of_the_numbers():
    """No clock, no file, no request. The report exists to be compared month over month, and output
    that moved on its own would make every comparison meaningless — which is also why `as_of` is
    passed in rather than read from `date.today()`."""
    report = _report(Baseline(bands=[CEILING, WAGE], band_counts={"calc": 1, "bls": 1},
                              supply_counts={"himalayas": 97}))
    assert render(report) == render(report)
    assert date.today().isoformat() not in render(report)


def test_the_date_in_the_heading_is_the_one_the_caller_passed():
    out = render(_report(None, as_of="2026-07-22"))
    assert out.startswith("# Market report — 2026-07-22")
