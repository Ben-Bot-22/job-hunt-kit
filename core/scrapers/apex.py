"""Apex Systems — pull the whole US board in one request, parse per-job JSON-LD.

Cloudflare-fronted (passes with a browser UA from a residential IP). The search is a Drupal form
(`awr_jobs_search_form`) that POSTs and then *redirects to a plain GET* carrying its state in the
query string — which is how the parameters below were found. There is no JSON/AJAX endpoint to call:
the results are server-rendered into a `<table>` and the front-end never issues an XHR for them.

Two things matter, and the old scraper had both wrong. **`rows=` sets the page size** and is not
capped anywhere we could find (`rows=3000` returns the entire ~2,600-job board in one response), so
pagination is unnecessary. That is just as well, because **`?page=N` alone does not work**: page 2+
renders an empty table unless the request carries the session cookie the search form sets, and
`page=0` and `page=1` are both page one — so the old loop refetched page one, saw no new URLs and
stopped, which is why this returned 3 jobs.

The board's **default order is newest-first**, so the `[:MAX_JOBS]` slice below is the freshest
postings rather than an arbitrary slice — document order is preserved for exactly that reason.

LIMITATION: Apex staffs far more non-software than software, so the dev filter is still a slug match
over the URL and will miss a software role whose title does not say so. On 2026-07-24 the board held
2,604 postings, 488 of them dev-slug; `MAX_JOBS` now covers all of them (~317 s, one detail page each
at the throttle below) and states its own justification where it is defined.
"""
from __future__ import annotations

import logging
import re
import time

import requests

from core.models import Job

from . import jsonld as _jsonld
from .posting import posting

log = logging.getLogger(__name__)

AGENCY = "Apex Systems"
BASE = "https://www.apexsystems.com"
SEARCH = "/search-results-usa"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
HREF = re.compile(r'href="(/job/[^"]+)"')
# The whole board in one response. `rows` is the page size; `catalogcode`/`radius` are what the
# search form's own redirect sends, and omitting `query` means "everything".
PARAMS = {"catalogcode": "USA", "radius": "50", "page": "1", "rows": "3000"}
# DEADLINE-DERIVED, and that is the whole justification — this is the one cap in `core/scrapers/` that
# is a real coverage decision rather than a runaway guard, so it says why in the number.
#
# The board carried 2,604 postings on 2026-07-24, 488 of them dev-slug, and each costs one detail
# fetch at THROTTLE plus latency (~0.65 s) — so the full 488 is ~317 s. The `agencies` channel abandons
# a source still running at `_DEADLINE` (triage/channels/agencies.py), which means an uncapped Apex
# would not return 488 jobs, it would return ZERO. A cap here buys the newest N instead of nothing.
# 600 covers the whole dev slice against a 600 s deadline with the board's newest-first order intact,
# so the cap only binds if Apex grows past ~900 dev postings — at which point the warning below fires
# and the number is a floor, not the board.
MAX_JOBS = 600
THROTTLE = 0.3
DEV_SLUG = (
    "developer", "software", "react", "full-stack", "fullstack", "frontend", "front-end",
    "backend", "back-end", "-node", "node-", "python", "typescript", "javascript",
    "web-develop", "application-develop", "programmer", "sdet", "data-eng", "devops",
    "cloud-engineer", "machine-learning", "ml-engineer", "ai-engineer", "-ai-",
)


def fetch() -> list[Job]:
    try:
        html = requests.get(BASE + SEARCH, params=PARAMS, headers=UA, timeout=90).text
    except Exception as e:  # noqa: BLE001
        log.warning("apex search failed: %s", e)
        return []

    hrefs = list(dict.fromkeys(HREF.findall(html)))  # dedupe, keep newest-first document order
    dev_all = [h for h in hrefs if any(t in h.lower() for t in DEV_SLUG)]
    dev = dev_all[:MAX_JOBS]
    if len(dev_all) > MAX_JOBS:
        log.warning("apex: %d dev postings on the board, fetching the newest %d — the count is a "
                    "floor, not the board", len(dev_all), MAX_JOBS)
    jobs: list[Job] = []
    for h in dev:
        u = BASE + h
        try:
            page = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("apex job fetch failed: %s", e)
            continue
        jps = _jsonld.jobpostings(page)
        if jps:
            jobs.append(_to_job(jps[0], u))
        time.sleep(THROTTLE)

    log.info("apex: %d jobs (from %d dev urls / %d total listing urls)", len(jobs), len(dev), len(hrefs))
    return jobs


def _to_job(jp: dict, url: str) -> Job:
    metro, remote = _jsonld.location(jp)
    et = _jsonld.employment_type(jp)
    company = _jsonld.company(jp)
    if company.lower() in ("confidential", ""):
        company = AGENCY
    return posting(
        title=jp.get("title") or "",
        company=company,
        link=url,
        source="apex",
        description=_jsonld.description(jp),
        employment_type=et,
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=_jsonld.salary(jp),
        posted=_jsonld.posted(jp),
    )
