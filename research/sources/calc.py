"""GSA CALC+ — federal contract **ceiling** bill rates. No key, no account, refreshed nightly.

This is the find of the stage: the only authoritative source of US *hourly contract* rates anyone
located that a stranger can query with nothing but a URL. It is the awarded price list off GSA's
Multiple Award Schedule — 281,084 labor-category rows on 2026-07-22, re-indexed every night
(`_index: ceilingrates-2026-07-22_02-00-04` came back in the response).

**Every figure here is a ceiling and the module refuses to emit one that doesn't say so.** A MAS rate
is the maximum a vendor may bill the government for an hour of that labor category. It is fully
burdened — overhead, G&A, fringe, fee — so it is an upper bound on a *bill* rate, not a wage, and not
what a contractor takes home. The median for `software engineer` is $135.54/hr; quoting that in a
negotiation as "the market" would be a factor-of-two error in the direction that ends conversations.
`_baseline.RateBand` validates the caveat rather than trusting this file to remember it.

**Two things about the endpoint that are not obvious and cost an afternoon each.**

`q=` does not filter. It is accepted, returns HTTP 200, and quietly answers over the whole 281k index —
so a query that looks like it asked for software engineers reports the median of every federal labor
category including food service workers. The parameter that filters is `keyword=`. Nor do
`experience_range`, `education_level`, `worksite`, `business_size` or `price_range` do anything over
GET, alone or alongside the app's full default parameter set (all measured: identical `n` every time).
So **the dimension filters are applied here, over the rows**, which is also the only way to know they
were applied at all.

And the result set is sorted by `current_price` ascending, which makes a partial pull actively
misleading rather than merely incomplete — the first 1,000 of 3,934 software-engineer rows are the
cheapest 1,000. Pages are therefore pulled to exhaustion, and `MAX_ROWS` truncation appends a sentence
to the band's own caveat rather than being logged where nobody looks.
"""
from __future__ import annotations

import logging
import time

import requests

from ._baseline import RateBand, percentiles

log = logging.getLogger(__name__)

API = "https://buy.gsa.gov/pricing/api/v3/search/ceilingrates/"

# CALC+ indexes federal *labor categories*, not job-board titles, so it does not share `_query.TERMS`:
# measured on 2026-07-22, `TypeScript developer` and `Node developer` return 0 rows and `React
# developer` returns 6. These five are the vocabulary the schedule actually uses — 8,373 rows between
# them (software engineer 3,934, software developer 2,205, web developer 1,158, application developer
# 975, full stack developer 101).
TERMS: tuple[str, ...] = (
    "software engineer",
    "software developer",
    "full stack developer",
    "web developer",
    "application developer",
)

PAGE_SIZE = 1000      # ~0.9 MB and ~0.8 s per page; the API accepts it without complaint
MAX_ROWS = 6000       # a stop, not a sample: hitting it is written into the caveat
THROTTLE = 0.5        # a public .gov endpoint being paged to exhaustion; be visibly polite
TIMEOUT = 60

CAVEAT = ("GSA CALC+ figures are federal contract CEILING BILL RATES — the maximum a vendor may bill "
          "the government under its MAS schedule, fully burdened with overhead, G&A, fringe and fee. "
          "They are an upper bound on a bill rate, not a market wage and not take-home pay.")

ATTRIBUTION = ("Source: GSA CALC+ / Contract-Awarded Labor Category (buy.gsa.gov/pricing), "
               "US Government public-domain data.")


def fetch_bands(terms: tuple[str, ...] = TERMS, *, min_experience: int | None = None,
                education: str | None = None, worksite: str | None = None) -> list[RateBand]:
    """One `RateBand` per term, filtered by the dimensions the report asks about.

    `min_experience` is a floor on the schedule's `min_years_experience`; `education` matches CALC's own
    labels (`Bachelors`, `Masters`, `Associates`, `High School`, `PhD`); `worksite` is one of
    `Customer_Facility`, `Contractor_Facility`, `Virtual`. A filter that empties the sample yields a
    band with `n=0` and no median rather than a missing band — the report should be able to say the
    question was asked and came back thin.

    Never raises. An unreachable endpoint costs that term's band and is logged.
    """
    bands: list[RateBand] = []
    for term in terms:
        rows, truncated = _rows(term)
        if rows is None:
            continue
        bands.append(_band(term, rows, truncated=truncated, min_experience=min_experience,
                           education=education, worksite=worksite))
    return bands


def _rows(term: str) -> tuple[list[dict] | None, bool]:
    """Every `_source` row for a keyword, or `(None, False)` if the endpoint could not be read.

    `None` and `[]` are different answers and the caller needs both: an empty index for a term is a
    finding, an unreachable API is a gap.
    """
    rows: list[dict] = []
    page = 1
    while len(rows) < MAX_ROWS:
        params = {"keyword": term, "page": page, "page_size": PAGE_SIZE}
        try:
            r = requests.get(API, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            hits = r.json()["hits"]["hits"]
        except Exception as e:  # noqa: BLE001 — one term must not cost the baseline
            log.warning("calc: %r page %d failed: %s", term, page, e)
            return (rows or None), False
        rows += [h.get("_source", {}) for h in hits]
        if len(hits) < PAGE_SIZE:
            return rows, False
        page += 1
        time.sleep(THROTTLE)
    return rows[:MAX_ROWS], True


def _band(term: str, rows: list[dict], *, truncated: bool = False, min_experience: int | None = None,
          education: str | None = None, worksite: str | None = None) -> RateBand:
    kept = [r for r in rows if _matches(r, min_experience, education, worksite)]
    prices = [float(r["current_price"]) for r in kept if r.get("current_price") is not None]
    caveat = CAVEAT
    if truncated:
        # Rows arrive price-ascending, so a truncated pull is not a random sample of the schedule —
        # it is the cheap end of it. Saying "median" over that without this sentence is a wrong number
        # rather than a thin one, which is the failure this whole module is built to avoid.
        caveat += (f" This band was truncated at {MAX_ROWS:,} of the schedule's rows, which arrive "
                   f"cheapest-first, so it understates the true median.")
    return RateBand(
        source="calc",
        occupation=term,
        scope="US federal schedule",
        unit="hour",
        n=len(prices),
        period="GSA MAS awarded prices, current schedule",
        caveat=caveat,
        attribution=ATTRIBUTION,
        is_ceiling=True,
        query={"keyword": term, "min_experience": min_experience,
               "education": education, "worksite": worksite},
        **percentiles(prices),
    )


def _matches(row: dict, min_experience: int | None, education: str | None, worksite: str | None) -> bool:
    """The dimension filters, applied here because the API accepts them and ignores them."""
    if min_experience is not None and int(row.get("min_years_experience") or 0) < min_experience:
        return False
    if education is not None and (row.get("education_level") or "") != education:
        return False
    if worksite is not None and (row.get("worksite") or "") != worksite:
        return False
    return True
