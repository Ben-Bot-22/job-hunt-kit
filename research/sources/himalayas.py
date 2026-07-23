"""Himalayas — the whole remote board as one keyless JSON feed, paged twenty rows at a time.

**Considered and rejected as a job-input channel, and kept here instead.** That distinction is what
`research/sources/` exists to make physical: this is *where market data comes from*, not *where my
jobs come from*. Measured live over 1,000 rows on 2026-07-22, the developer slice is **87 Full Time
to 6 Contractor** — near-useless for a contract search, and the best keyless picture of remote
*permanent* supply anyone found. The retrospective's own inbox is 71% permanent by accident; this is
the same shape on purpose, from a board with 95,456 live listings, which is what makes it a baseline
rather than an echo.

**The API ignores every filter parameter it accepts.** `category=software-development`,
`search=developer` and a `parentCategory` guess all answer HTTP 200 with the same unfiltered page-one
rows (verified live, identical `totalCount` and identical first three titles), and `limit` is capped
at 20 however much you ask for. Only `offset` does anything. So the developer cut is made here, over
`parentCategories`, and the cost of a pull is pages rather than queries: `MAX_PAGES` buys the newest
slice of the board, never the board.

Attribution is required and rides on every record — see `_posting.py` and the registry's drop guard.
Himalayas' own terms page sits behind a bot check and could not be retrieved verbatim, so the line
below is written to the stricter of the two standards this stage has in hand (Remotive's, which its
API states in the payload): name the source, and link back to its own URL. `applicationLink` is that
URL, which is also why this is a research source and not a channel — it is the board's page, not the
employer's apply link.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from core import rates
from core.models import Job

from core.scrapers.posting import posting, strip_html

log = logging.getLogger(__name__)

ATTRIBUTION = "Job data from Himalayas (https://himalayas.app)"

BASE = "https://himalayas.app/jobs/api"
UA = {"User-Agent": "jobs-db market research (https://github.com/)"}
PAGE = 20          # the API's hard cap; asking for 50 returns 20 and says `limit: 20`
MAX_PAGES = 50     # 1,000 rows in ~20 s. The board has 95,456 — this is the newest slice, not the board
THROTTLE = 0.2

# `parentCategories` is the API's own coarse grouping and the only usable dev filter. Over the 1,000-row
# sample: Developer 76, Data Science 31, Sales 147 — so this keeps ~10% of rows. `Data Science` is in
# because it is where LLM/ML engineering lands and that is in lane; dropping it is a one-word edit and
# costs ~30% of the sample.
DEV_CATEGORIES = ("Developer", "DevOps", "Data Science")


def fetch() -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    scanned = 0
    for page in range(MAX_PAGES):
        try:
            r = requests.get(BASE, params={"limit": PAGE, "offset": page * PAGE},
                             headers=UA, timeout=30)
            r.raise_for_status()
            rows = r.json().get("jobs") or []
        except Exception as e:  # noqa: BLE001 — a mid-pagination failure keeps what it has
            log.warning("himalayas page %d failed: %s", page, e)
            break
        if not rows:
            break
        scanned += len(rows)
        for item in rows:
            link = item.get("applicationLink") or item.get("guid") or ""
            if not link or link in seen or not _is_dev(item):
                continue
            seen.add(link)
            jobs.append(_to_job(item))
        time.sleep(THROTTLE)

    log.info("himalayas: %d dev jobs (from %d rows over %d pages)", len(jobs), scanned, MAX_PAGES)
    return jobs


def _is_dev(item: dict) -> bool:
    return bool(set(item.get("parentCategories") or []) & set(DEV_CATEGORIES))


def _to_job(item: dict) -> Job:
    return posting(
        title=item.get("title") or "",
        company=item.get("companyName") or "",
        link=item.get("applicationLink") or item.get("guid") or "",
        source="himalayas",
        description=strip_html(item.get("description") or ""),
        employment_type=item.get("employmentType") or "",
        metro=", ".join(item.get("locationRestrictions") or []),
        cadence="remote",  # the board is remote-only; that is the whole premise of it
        rate=_rate(item),
        posted=_posted(item),
        attribution=ATTRIBUTION,
    )


def _rate(item: dict) -> str:
    """A stated salary through `core.rates`, and only when currency and period say that is safe.

    **Non-USD is dropped rather than converted.** 500,000 MXN a year lands squarely inside the
    extractor's $10-600/hr sanity window as $240/hr, so a currency this module cannot convert is a
    *fabricated* rate and not a missing one — the direction `core/rates.py` exists to fail away from.
    Of 39 salaried dev rows in the live sample, 32 were USD. `monthly` is dropped for the same reason:
    the extractor has no unit to read off "$8,000" and infers annual, which is 12× wrong.
    """
    lo, hi = item.get("minSalary"), item.get("maxSalary")
    period = item.get("salaryPeriod")
    if not lo or item.get("currency") != "USD" or period not in ("annual", "hourly"):
        return ""
    unit = "per year" if period == "annual" else "per hour"
    text = f"${lo:,.0f} - ${hi:,.0f} {unit}" if hi and hi != lo else f"${lo:,.0f} {unit}"
    return rates.extract(text) or ""


def _posted(item: dict) -> str:
    """`pubDate` is a unix timestamp; everything downstream reads YYYY-MM-DD."""
    ts = item.get("pubDate")
    if not isinstance(ts, (int, float)):
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
