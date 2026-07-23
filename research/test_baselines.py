"""Tests for the two keyless government rate sources.  Run:  .venv/bin/python -m pytest research/ -q

Offline, no key, no network. Unlike the nine job scrapers, these two *do* get fixtures, and the reason
is the difference between the shapes: a scraper's fixture pins last year's HTML and proves nothing,
while a JSON API's response shape is the contract, and every value below is verbatim from a live call
made on 2026-07-22. The BLS payload in particular is the whole point — SOC 15-1252's 2025 national
annual mean really is $148,100, and if that stops arriving under that series id the report's permanent
anchor has silently become empty.

The load-bearing test in this file is `test_a_ceiling_band_cannot_be_built_without_saying_ceiling`.
Everything else here is plumbing; that one is the difference between a rate baseline and a number that
walks into a negotiation inflated by the vendor's overhead, G&A, fringe and fee.
"""
from __future__ import annotations

import pytest

from . import sources
from .sources import bls, calc
from .sources._baseline import RateBand, percentiles

# --- fixtures, verbatim from live responses on 2026-07-22 ---------------------------------------

# Five `_source` rows from `keyword=full stack developer` (101 rows in total on the day). Kept whole
# rather than trimmed to the fields used, because the dimension filters below read three of them and a
# trimmed fixture would stop proving that they read the right keys.
CALC_ROWS = [
    {"labor_category": "Full Stack Developer Level III", "current_price": 48.87,
     "min_years_experience": 8, "education_level": "Bachelors", "worksite": "Virtual",
     "vendor_name": "STRALYNN CONSULTING SERVICES, INC", "schedule": "MAS"},
    {"labor_category": "Full Stack Developer I", "current_price": 57.07,
     "min_years_experience": 4, "education_level": "Bachelors", "worksite": "Customer_Facility",
     "vendor_name": "OPTIMUSS INC.", "schedule": "MAS"},
    {"labor_category": "Full Stack Developer II", "current_price": 69.16,
     "min_years_experience": 5, "education_level": "Bachelors", "worksite": "Customer_Facility",
     "vendor_name": "OPTIMUSS INC.", "schedule": "MAS"},
    {"labor_category": "UI/Full Stack Developer", "current_price": 69.52,
     "min_years_experience": 9, "education_level": "Bachelors", "worksite": "Contractor_Facility",
     "vendor_name": "ACROSS BORDERS MANAGEMENT CONSULTING GROUP LLC.", "schedule": "MAS"},
    {"labor_category": "Full Stack Developer -Cloud", "current_price": 71.5879,
     "min_years_experience": 4, "education_level": "Masters", "worksite": "Customer_Facility",
     "vendor_name": "SIMIS, INC.", "schedule": "MAS"},
]

# The real v1 payload for SOC 15-1252, abridged to national hourly median and annual mean plus the two
# Dallas-Fort Worth equivalents. Note `value` is a *string* and the annual one has no decimal point.
BLS_PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "responseTime": 143,
    "message": [],
    "Results": {"series": [
        {"seriesID": "OEUN000000000000015125208",
         "data": [{"year": "2025", "period": "A01", "periodName": "Annual", "value": "65.38"}]},
        {"seriesID": "OEUN000000000000015125204",
         "data": [{"year": "2025", "period": "A01", "periodName": "Annual", "value": "148100"}]},
        {"seriesID": "OEUM001910000000015125208",
         "data": [{"year": "2025", "period": "A01", "periodName": "Annual", "value": "64.08"}]},
        {"seriesID": "OEUM001910000000015125204",
         "data": [{"year": "2025", "period": "A01", "periodName": "Annual", "value": "138810"}]},
    ]},
}

# What BLS answers with when the 25-a-day allowance is gone. HTTP 200, like everything else it sends.
BLS_THRESHOLD = {
    "status": "REQUEST_NOT_PROCESSED",
    "responseTime": 0,
    "message": ["Daily threshold of 25 queries has been reached. Please register for an API key at "
                "https://data.bls.gov/registrationEngine/"],
    "Results": {},
}


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _hits(rows):
    return _Resp({"hits": {"hits": [{"_source": r} for r in rows]}})


# --- the caveat is a field, and it is checked -----------------------------------------------------


def test_a_ceiling_band_cannot_be_built_without_saying_ceiling():
    """The one that matters. A GSA MAS rate is the maximum a vendor may bill the government, fully
    burdened with overhead, G&A, fringe and fee — printed as "what the job pays" it inflates a rate
    expectation by roughly a factor of two, in the direction that ends a negotiation. Validating the
    word in the caveat means a later edit that softens the wording fails here instead of shipping."""
    with pytest.raises(ValueError, match="ceiling"):
        RateBand(source="calc", occupation="software engineer", scope="US federal schedule",
                 unit="hour", n=1, period="now", caveat="Rates from GSA.", attribution="GSA.",
                 is_ceiling=True, median=135.54)


def test_no_band_of_any_kind_may_ship_without_a_caveat_or_attribution():
    """Attribution is a terms-of-use obligation and a caveat is a correctness one; neither survives
    living in a render template, because the next template edit deletes it and nothing notices."""
    common = dict(source="bls", occupation="Software Developers", scope="National", unit="year",
                  n=0, period="OEWS 2025 annual estimates", median=135980.0)
    with pytest.raises(ValueError, match="caveat"):
        RateBand(**common, caveat="   ", attribution="BLS.")
    with pytest.raises(ValueError, match="attribution"):
        RateBand(**common, caveat="A survey of employee wages.", attribution="")


def test_the_figure_and_the_warning_come_out_of_one_call():
    """`describe()` exists so a renderer that wants a number has the caveat handed to it in the same
    string. It can still reach for `.median` and print it bare — what it cannot do is not be told."""
    band = calc._band("software engineer", CALC_ROWS)
    assert band.describe().startswith(band.headline())
    assert "CEILING BILL RATES" in band.describe()
    assert "not take-home pay" in band.describe()


# --- CALC+: the dimension filters are applied here because the API ignores them -------------------


def test_calc_percentiles_are_computed_from_the_rows_not_read_off_the_api():
    """CALC+'s own `histogram_percentiles` is Elasticsearch's t-digest approximation and it drifts —
    the same query a second apart returned 135.54, 135.57, 135.61, 135.66 and 135.71. A report built
    for month-over-month comparison cannot have its baseline move for no reason, so the rows are pulled
    and the quantiles taken exactly. Pinned to the five real rows above."""
    band = calc._band("full stack developer", CALC_ROWS)
    assert band.n == 5
    assert band.median == 69.16
    assert band.mean == 63.24
    assert (band.p10, band.p25, band.p75, band.p90) == (52.15, 57.07, 69.52, 70.76)
    assert band.unit == "hour"


def test_calc_filters_by_experience_education_and_worksite():
    """The API accepts `experience_range`, `education_level` and `worksite`, returns HTTP 200, and
    silently ignores all three — measured, identical `n` every time. So the filters live here, which is
    also the only way a caller can know they were applied at all."""
    assert calc._band("t", CALC_ROWS, min_experience=8).n == 2          # the 8- and 9-year rows
    assert calc._band("t", CALC_ROWS, education="Masters").n == 1
    assert calc._band("t", CALC_ROWS, worksite="Customer_Facility").n == 3
    assert calc._band("t", CALC_ROWS, min_experience=5, worksite="Virtual").n == 1


def test_a_filter_that_empties_the_sample_still_produces_a_band():
    """"I asked and it came back thin" and "I never asked" are different report sections. A missing
    band reads as the second when it was the first."""
    band = calc._band("t", CALC_ROWS, education="PhD")
    assert band.n == 0 and band.median is None
    assert "no data" in band.headline()


def test_a_truncated_calc_pull_says_so_in_its_own_caveat():
    """Rows arrive sorted by price ascending, so a partial pull is not a thin sample — it is the cheap
    end of the schedule. A median over that is a wrong number, not a missing one, so the warning rides
    on the band rather than in a log line nobody reads."""
    honest = calc._band("t", CALC_ROWS)
    cut = calc._band("t", CALC_ROWS, truncated=True)
    assert "cheapest-first" in cut.caveat and "understates" in cut.caveat
    assert "cheapest-first" not in honest.caveat


def test_calc_pages_to_exhaustion_and_reads_the_keyword_parameter(monkeypatch):
    """`q=` is accepted, returns 200, and answers over all 281,084 rows of every federal labor
    category including food service workers. `keyword=` is the one that filters. Pinning the parameter
    name is pinning the difference between this source and a number with no meaning."""
    seen: list[dict] = []
    pages = [CALC_ROWS * 200, CALC_ROWS[:2]]      # 1000 then a short page = the last one

    def fake_get(url, params=None, timeout=None):
        seen.append(params)
        return _hits(pages[params["page"] - 1])

    monkeypatch.setattr(calc.requests, "get", fake_get)
    monkeypatch.setattr(calc, "THROTTLE", 0)
    rows, truncated = calc._rows("full stack developer")

    assert [p["page"] for p in seen] == [1, 2]
    assert all(p["keyword"] == "full stack developer" for p in seen)
    assert all("q" not in p for p in seen)
    assert len(rows) == 1002 and not truncated


def test_an_unreachable_calc_costs_that_term_and_not_the_report(monkeypatch):
    """Degrading to absent, never to silent: the band is missing and the caller's count says so."""
    def boom(*a, **kw):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(calc.requests, "get", boom)
    assert calc.fetch_bands(terms=("software engineer",)) == []


# --- BLS: the permanent anchor, per metro ---------------------------------------------------------


def test_bls_reads_the_real_wire_format_including_per_metro_series(monkeypatch):
    """Pinned to the live 2026-07-22 payload. The values are strings, the annual ones carry no decimal
    point, and the metro series differs from the national one by four characters — all three are ways
    this could silently return nothing. Dallas-Fort Worth's $138,810 mean against the national $148,100
    is the 6.3% gap a national-only baseline hides, which is why per-MSA is supported at all — a metro
    is passed explicitly (the code default is national-only), exactly as `bls_areas` in settings does."""
    monkeypatch.setattr(bls.requests, "post", lambda *a, **kw: _Resp(BLS_PAYLOAD))

    bands = {(b.scope, b.unit): b for b in bls.fetch_bands(
        areas={"National": ("N", "0000000"), "Dallas-Fort Worth-Arlington, TX": ("M", "0019100")})}

    assert bands[("National", "hour")].median == 65.38
    assert bands[("National", "year")].mean == 148100.0
    assert bands[("Dallas-Fort Worth-Arlington, TX", "hour")].median == 64.08
    assert bands[("Dallas-Fort Worth-Arlington, TX", "year")].mean == 138810.0
    assert bands[("National", "year")].period == "OEWS 2025 annual estimates"


def test_a_bls_band_is_a_wage_and_is_not_labelled_a_ceiling():
    """The two sources answer opposite questions and the report leans on the difference: CALC+ is what
    the government will pay a contractor, BLS is what employers pay employees. Mixing the labels would
    make the perm anchor read as an upper bound and the contract anchor as a wage."""
    band = RateBand(source="bls", occupation="Software Developers", scope="National", unit="year",
                    n=0, period="OEWS 2025 annual estimates", caveat=bls.CAVEAT,
                    attribution=bls.ATTRIBUTION, median=135980.0)
    assert not band.is_ceiling
    assert "EMPLOYEE wages" in band.caveat
    assert "Bureau of Labor Statistics" in band.attribution


def test_a_spent_daily_quota_degrades_rather_than_crashing(monkeypatch):
    """BLS answers a threshold breach with HTTP 200 and REQUEST_NOT_PROCESSED, so the status code says
    nothing at all. Reading the payload's own `status` is the only way to tell a refusal from an empty
    answer, and getting it wrong means a run that reports "no wage data" as if that were the finding."""
    monkeypatch.setattr(bls.requests, "post", lambda *a, **kw: _Resp(BLS_THRESHOLD))
    assert bls.fetch_bands() == []


def test_an_unreachable_bls_returns_no_bands_rather_than_raising(monkeypatch):
    def boom(*a, **kw):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(bls.requests, "post", boom)
    assert bls.fetch_bands() == []


def test_the_default_ask_is_one_request_of_eight_series(monkeypatch):
    """Quota is respected by construction rather than by counting: the national-only default baseline
    is 8 series (6 hourly + 2 annual) in a single call, 2% of the daily allowance. A configured metro
    doubles it to 16; if a later edit adds occupations without watching the multiplication, this is
    where it shows up."""
    posted: list[list[str]] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posted.append(json["seriesid"])
        return _Resp(BLS_PAYLOAD)

    monkeypatch.setattr(bls.requests, "post", fake_post)
    bls.fetch_bands()

    assert len(posted) == 1
    assert len(posted[0]) == 8
    assert all(len(sid) == 25 for sid in posted[0])
    assert "OEUN000000000000015125204" in posted[0]      # national annual mean, verified live


def test_more_series_than_the_query_cap_allows_are_dropped_out_loud(monkeypatch, caplog):
    """A silent cap reads as full coverage. Asking for 30 metros must not quietly become 25 queries
    against a 25-a-day allowance, and the metros that fell off have to be findable."""
    monkeypatch.setattr(bls.requests, "post", lambda *a, **kw: _Resp(BLS_PAYLOAD))
    areas = {f"Metro {i}": ("M", f"00{i:05d}") for i in range(30)}

    with caplog.at_level("WARNING"):
        bls.fetch_bands(areas=areas)

    assert "capping" in caplog.text
    assert str(bls.MAX_QUERIES) in caplog.text


# --- the registry -------------------------------------------------------------------------------


def test_both_baselines_are_registered_and_are_not_job_sources():
    """Two shapes, one file. `fetch() -> list[Job]` answers *what is advertised*; `fetch_bands() ->
    list[RateBand]` answers *what this work pays*. Folding CALC+ into `ALL` would mean inventing a fake
    posting per percentile, which is the mistake ticket 01 flagged on the way out."""
    assert set(sources.BASELINES) == {"calc", "bls"}
    assert not set(sources.BASELINES) & set(sources.ALL)


def test_neither_baseline_is_key_gated():
    """The whole reason the external half can be a default rather than an "add a key to unlock" tier.
    A baseline that grew a key would move the zero-key line without anyone deciding to."""
    assert not set(sources.BASELINES) & set(sources.KEYED)
    for mod in (calc, bls):
        assert "_env" not in (mod.__dict__.keys() | set(dir(mod)))


def test_a_crashing_baseline_costs_that_baseline_and_nothing_else(monkeypatch):
    """The external half must degrade to a *labelled* gap. The per-source count is the label."""
    monkeypatch.setitem(sources.BASELINES, "calc", lambda: (_ for _ in ()).throw(RuntimeError("503")))
    monkeypatch.setitem(sources.BASELINES, "bls", lambda: [
        RateBand(source="bls", occupation="Software Developers", scope="National", unit="year",
                 n=0, period="OEWS 2025 annual estimates", caveat=bls.CAVEAT,
                 attribution=bls.ATTRIBUTION, median=135980.0)])

    bands, counts = sources.fetch_baselines()

    assert counts == {"calc": 0, "bls": 1}
    assert len(bands) == 1


def test_an_unknown_baseline_name_is_logged_and_skipped():
    assert sources.fetch_baselines(names=("nosuchbaseline",)) == ([], {})


# --- the shared percentile helper ------------------------------------------------------------------


def test_percentiles_of_an_empty_or_single_sample_are_none_not_zero():
    """Zero is a rate. `None` is the absence of one, and the report renders them differently — a
    fabricated $0.00 median would read as a real figure from a real source."""
    assert percentiles([]) == {"median": None, "mean": None, "p10": None,
                              "p25": None, "p75": None, "p90": None}
    one = percentiles([88.0])
    assert one["median"] == 88.0 and one["p10"] is None
