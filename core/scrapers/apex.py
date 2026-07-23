"""Apex Systems — scrape the search page for /job/ URLs, parse per-job JSON-LD.

Cloudflare-fronted (passes with a browser UA from a residential IP). LIMITATION: the GET search
page shows ~25 jobs/page and the keyword filter is AJAX-gated, so coverage is shallow and noisy
(Apex staffs lots of non-software roles). We dev-slug-filter and paginate via ?page=N where it works.
Deeper Apex coverage would need the token-gated AJAX search or a scraping API.
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
MAX_PAGES = 8
THROTTLE = 0.3
DEV_SLUG = (
    "developer", "software", "react", "full-stack", "fullstack", "frontend", "front-end",
    "-node", "node-", "python", "typescript", "web-develop", "programmer", "sdet",
    "data-eng", "devops", "machine-learning", "-ai-", "full-stack",
)


def fetch() -> list[Job]:
    hrefs: set[str] = set()
    for p in range(MAX_PAGES):
        url = f"{BASE}{SEARCH}?page={p}"
        try:
            html = requests.get(url, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("apex search page %d failed: %s", p, e)
            break
        found = HREF.findall(html)
        new = [h for h in found if h not in hrefs]
        hrefs.update(found)
        time.sleep(THROTTLE)
        if not new and p > 0:  # pagination exhausted (or AJAX-only)
            break

    dev = [h for h in hrefs if any(t in h.lower() for t in DEV_SLUG)]
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
