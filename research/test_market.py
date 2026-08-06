"""Tests for the market-report command.  Run:  .venv/bin/python -m pytest research/ -q

Offline: no key, no network, no model. Everything writes into `tmp_path`, and the one test that
would otherwise reach `research/sources/` asserts that it *doesn't* by making the network path
explode if it is touched.

The failure directions this file is shaped around, in the order they would cost something:

  * **the daily run getting slower or noisier.** The report is a separate command precisely so that
    it can cost 11 seconds of clustering and a network round trip; a flag on `python -m triage` would
    put both into every morning. Asserted by reading the pipeline's own module list.
  * **a first-party run that quietly reaches the network.** The zero-key, zero-ToS path is what makes
    this feature a default rather than an "add a key to unlock" tier, and a run that needs a network
    to produce Part 1 would have lost that without anyone noticing.
  * **history not accumulating.** A trend in October is made of files written in July. If a run
    overwrites the previous month's numbers, or files them under the wrong name, the feature can
    never start — and nothing observable goes wrong today.
  * **the human narrative being overwritten.** `docs/knowledge-base/personal/market/market-insights.md` is the 10% a person
    had to write; this command writes only into `data/reports/`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.index import DEFAULT_MODEL, model_is_cached
from core.test_retrieval import FakeEmbedder

from . import market
from .report import Baseline
from .snapshots import PREFIX, fingerprint
from .sources import bls, calc
from .sources._baseline import RateBand

RUBRIC = "Score contract-first, remote-only. A 10 is a remote contract at $100/hr."

# Live on 2026-07-22, the same figures `research/test_report.py` pins.
CEILING = RateBand(
    source="calc", occupation="software engineer", scope="National", unit="hour", n=3934,
    period="MAS schedule prices, current", caveat=calc.CAVEAT, attribution=calc.ATTRIBUTION,
    is_ceiling=True, median=135.82)
WAGE = RateBand(
    source="bls", occupation="Software Developers", scope="National", unit="hour", n=0,
    period="OEWS 2025", caveat=bls.CAVEAT, attribution=bls.ATTRIBUTION, median=65.38)


def _rec(n: int = 0, *, jd: str = "Pay: $90/hr") -> dict:
    """One corpus-shaped record, matching `research/test_retrospective.py`'s fixture."""
    return {
        "link": f"https://example.test/jobs/{n}",
        "company": f"Company {n}",
        "title": "Senior Full Stack Developer",
        "fetched_jd": jd,
        "jd_source": "full",
        "_run": "2026-07-20-094851",
        "analysis": {"employment_type": "contract", "cadence": "remote", "is_agency": False,
                     "red_flags": ["Permanent role, not contract"], "resume_keywords": ["Python"]},
    }


def _corpus(tmp_path: Path, n: int = 4) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "state-2026-07-20-094851.json").write_text(
        json.dumps({"jobs": [_rec(i) for i in range(n)]}), encoding="utf-8")
    return corpus


def _run(tmp_path: Path, *, baseline=None, as_of: str = "2026-07-22", rubric: str = "r1",
         reports: Path | None = None, corpus: Path | None = None):
    return market.run(corpus_dir=corpus or _corpus(tmp_path),
                      reports_dir=reports or (tmp_path / "reports"),
                      as_of=as_of, baseline=baseline, rubric=rubric,
                      top_terms=5, top_employers=5, embedder=FakeEmbedder())


# --- a separate command, not a flag on the daily run ------------------------------------------------

def test_the_daily_run_does_not_import_the_report():
    """The whole argument for a separate command: different cadence. A `--report` flag on
    `python -m triage` would put ~11 s of clustering, and a network round trip, into every morning.

    Read as text rather than by importing, because `core/test_layering.py` scans test files too and a
    `import triage` here would be a layering failure in the package that forbids it."""
    source = (Path(__file__).resolve().parent.parent / "triage" / "__main__.py").read_text()
    assert "import triage" in source or "from ." in source        # non-vacuity: we read the real file
    for banned in ("research.market", "research.report", "market_report"):
        assert banned not in source


# --- the first-party half needs no network ----------------------------------------------------------

def test_a_first_party_run_never_reaches_the_network(tmp_path, monkeypatch):
    """The zero-key, zero-network path is the default and the reason this feature isn't paywalled.
    A run that quietly needed a network to produce Part 1 would have lost that silently."""
    def explode(*a, **kw):                                        # noqa: ANN002 - a tripwire
        raise AssertionError("the first-party half reached the network")

    from . import sources
    monkeypatch.setattr(sources, "fetch_baselines", explode)
    monkeypatch.setattr(sources, "fetch_all", explode)

    markdown, numbers, document = _run(tmp_path)

    assert "Part 1 — Your own inbox (first-party)" in markdown
    assert "UNAVAILABLE" in markdown          # ...and the missing half says so rather than vanishing
    assert numbers.exists() and document.exists()


def test_offline_skips_the_collection_entirely(tmp_path, monkeypatch):
    """`--offline` must not even ask. A run that collected and discarded would still hit somebody
    else's API from a command whose whole promise is that it doesn't."""
    calls = []
    monkeypatch.setattr(market, "collect_baseline", lambda **kw: calls.append(kw))
    monkeypatch.setattr(market, "run", lambda **kw: ("", tmp_path / "n.json", tmp_path / "r.md"))
    monkeypatch.setattr(market, "_report_settings", lambda: {"external": True})

    assert market.main(["--offline", "--reports-dir", str(tmp_path)]) == 0
    assert calls == []


def test_external_false_in_the_settings_file_is_the_same_as_offline(tmp_path, monkeypatch):
    """Report configuration lives in the validated settings file, so this is a standing choice rather
    than something you have to remember to type."""
    calls = []
    monkeypatch.setattr(market, "collect_baseline", lambda **kw: calls.append(kw))
    monkeypatch.setattr(market, "run", lambda **kw: ("", tmp_path / "n.json", tmp_path / "r.md"))
    monkeypatch.setattr(market, "_report_settings", lambda: {"external": False})

    assert market.main(["--reports-dir", str(tmp_path)]) == 0
    assert calls == []


def test_the_settings_metro_reaches_the_wage_baseline(tmp_path, monkeypatch):
    """Ticket 03 shipped Dallas-Fort Worth as a default read off this repo's own profile. A stranger's
    metro has to be a settings edit; if the key silently didn't arrive, they would read a national
    figure believing it was theirs."""
    seen = {}
    from . import sources
    monkeypatch.setattr(sources, "fetch_baselines",
                        lambda options=None: (seen.update(options or {}), ([], {}))[1])
    monkeypatch.setattr(sources, "fetch_all", lambda: ([], {}))

    market.collect_baseline(supply=False, bls_areas={"Chicago-Naperville-Elgin, IL-IN-WI": "M0016980"})

    assert seen["bls"]["areas"] == {"Chicago-Naperville-Elgin, IL-IN-WI": ("M", "0016980")}


def test_no_configured_areas_leaves_the_baseline_on_its_own_default():
    """`None`, not `{}` — an empty dict would ask BLS for no areas at all and the wage anchor would
    disappear from the report with nothing to point at."""
    assert market._bls_areas(None) is None
    assert market._bls_areas({}) is None


# --- the dated numbers file -------------------------------------------------------------------------

def test_the_run_writes_a_dated_numbers_file_under_the_reports_directory(tmp_path):
    """Ticket 07 accumulates; this is the command that feeds it. The date is in the name, so an
    August run cannot touch July's numbers."""
    _, numbers, _ = _run(tmp_path, as_of="2026-07-22")

    assert numbers.name == f"{PREFIX}2026-07-22.json"
    assert numbers.parent == tmp_path / "reports"
    data = json.loads(numbers.read_text())
    assert data["as_of"] == "2026-07-22" and data["rubric"] == "r1"
    assert data["postings"] == 4


def test_a_second_month_leaves_the_first_alone(tmp_path):
    """The property every trend this feature will ever draw depends on."""
    corpus, reports = _corpus(tmp_path), tmp_path / "reports"
    _run(tmp_path, as_of="2026-07-22", corpus=corpus, reports=reports)
    _run(tmp_path, as_of="2026-08-22", corpus=corpus, reports=reports)

    assert sorted(p.name for p in reports.glob(f"{PREFIX}*.json")) == [
        f"{PREFIX}2026-07-22.json", f"{PREFIX}2026-08-22.json"]


def test_the_rendered_document_is_dated_and_filed_beside_the_numbers(tmp_path):
    markdown, numbers, document = _run(tmp_path, as_of="2026-07-22")

    assert document.name == "market-report-2026-07-22.md"
    assert document.parent == numbers.parent
    assert document.read_text(encoding="utf-8") == markdown
    assert markdown.startswith("# Market report — 2026-07-22")


def test_todays_snapshot_is_in_the_history_the_trend_reads(tmp_path):
    """The ordering decision in `run`: written, then read back. A trend table whose newest point were
    last month's run, under a Part 1 showing this month's numbers, would read as a bug — and the
    refusal below the gate has to count today's snapshot or it under-reports the history."""
    markdown, _, _ = _run(tmp_path, as_of="2026-07-22")

    assert "1 comparable snapshot spanning 1 day (2026-07-22 → 2026-07-22)" in markdown


def test_a_missing_rubric_still_produces_a_report(tmp_path):
    """A snapshot that cannot name its rubric is incomparable with everything, which is the safe
    direction — but it must not stop the report being written."""
    assert market.rubric_fingerprint(tmp_path / "nope.md") == ""

    markdown, numbers, _ = _run(tmp_path, rubric="")
    assert json.loads(numbers.read_text())["rubric"] == ""
    assert "No trend is claimed." in markdown


def test_the_rubric_fingerprint_is_the_hash_and_not_the_rubric_text(tmp_path):
    """The numbers directory is exactly what a user pastes into a bug report, and their scoring prompt
    is theirs."""
    path = tmp_path / "rubric.md"
    path.write_text(RUBRIC, encoding="utf-8")

    assert market.rubric_fingerprint(path) == fingerprint(RUBRIC)
    _, numbers, _ = _run(tmp_path, rubric=market.rubric_fingerprint(path))
    assert RUBRIC not in numbers.read_text(encoding="utf-8")


# --- the external half, when it is there ------------------------------------------------------------

def test_an_external_baseline_renders_with_its_caveat_and_its_attribution(tmp_path):
    """End of the wire the command owns: what `collect_baseline` returns has to arrive in the
    document with the CEILING label still attached — $135.82/hr from CALC+ against $65.38/hr from BLS
    is the same occupation 2.08x apart."""
    markdown, _, _ = _run(tmp_path, baseline=Baseline(bands=[CEILING, WAGE],
                                                      band_counts={"calc": 1, "bls": 1}))

    assert "UNAVAILABLE" not in markdown
    assert "$135.82/hr" in markdown and "CEILING" in markdown
    assert calc.ATTRIBUTION in markdown


# --- what it must never touch -----------------------------------------------------------------------

def test_the_command_writes_only_into_the_reports_directory(tmp_path):
    """The human-authored narrative is never overwritten: the 10% that needed a person stays a
    person's. This command's whole output is two files under `data/reports/`."""
    reports = tmp_path / "reports"
    corpus = _corpus(tmp_path)
    before = sorted(p.name for p in corpus.iterdir())

    _run(tmp_path, corpus=corpus, reports=reports)

    assert sorted(p.name for p in corpus.iterdir()) == before
    assert sorted(p.name for p in reports.iterdir()) == [
        f"{PREFIX}2026-07-22.json", "market-report-2026-07-22.md"]


def test_the_report_module_does_not_write_the_market_narrative():
    """Asserted rather than trusted, because "nothing overwrites Ben's prose" is the promise that
    makes the generated file safe to cite at all."""
    source = (Path(__file__).resolve().parent / "market.py").read_text()
    assert "market-insights" not in source.split('"""', 2)[2]     # prose in the docstring is fine


# --- one end-to-end run, with the real embedder -----------------------------------------------------

needs_model = pytest.mark.skipif(
    not model_is_cached(), reason=f"{DEFAULT_MODEL} weights are not cached")


@needs_model
def test_the_command_end_to_end_with_no_network_and_no_key(tmp_path, monkeypatch):
    """The stranger's run: a corpus, no key, no network, a whole document."""
    monkeypatch.setattr(market, "_report_settings", lambda: {"external": False, "top_terms": 3,
                                                             "top_employers": 3})
    corpus, reports = _corpus(tmp_path), tmp_path / "reports"

    assert market.main(["--corpus-dir", str(corpus), "--reports-dir", str(reports),
                        "--as-of", "2026-07-22"]) == 0

    document = (reports / "market-report-2026-07-22.md").read_text(encoding="utf-8")
    assert "Part 1 — Your own inbox (first-party)" in document
    assert "UNAVAILABLE" in document
    assert (reports / f"{PREFIX}2026-07-22.json").exists()
