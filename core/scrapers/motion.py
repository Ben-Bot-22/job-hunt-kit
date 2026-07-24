"""Motion Recruitment — paginate the tech-jobs listing, parse per-job JSON-LD.

Cloudflare-fronted but passes with a browser UA from a residential IP (the local-run advantage).
Pagination is `?start=N` in steps of 20, and the walk stops when a page yields **no new hrefs** —
not after a fixed page count, so the next pagination change shows up as a wrong count rather than a
silent truncation. `MAX_PAGES` is only a runaway guard and logs a warning when it is hit.

Known limitations, probed live 2026-07-24:

- **One combined listing, because the split ones are gone.** `/tech-jobs/direct-hire` now 404s, and
  so do `/tech-jobs/permanent`, `/tech-jobs/full-time`, `/tech-jobs/perm` and `/tech-jobs/
  contract-to-hire`; the `?type=`/`?job_type=`/`?employment_type=` query params are accepted and then
  ignored (identical results to no filter). There is no perm-only listing left to wire, so both
  halves come from `/tech-jobs`, which carries contract and direct-hire together (797 postings,
  41 pages). `/tech-jobs/contract` still works but is a strict subset of it and is not fetched.
- **The dev filter is a URL-slug heuristic** (`DEV_SLUG`), so it is shallow by construction: a
  posting whose title names no technology ("Senior Consultant", "Technical Lead") is dropped before
  its JSON-LD is ever read. 275 of the 797 postings survive it.
- One request per surviving posting, so a full run is 41 listing pages plus 275 detail pages — 316
  throttled requests, measured end to end at 197 s for 275 jobs on 2026-07-24. That is the slowest of
  the six scrapers, and it is the price of covering perm at all.
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

AGENCY = "Motion"
BASE = "https://motionrecruitment.com"
# The combined listing. The per-type ones (contract / direct-hire) are either a subset of it or
# 404 — see the module docstring.
LISTINGS = ["/tech-jobs"]
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
HREF = re.compile(r'href="(/tech-jobs/[^"]*?/\d+)"')
MAX_PAGES = 80  # runaway guard only — the walk stops on "no new hrefs". 41 pages is the live depth.
THROTTLE = 0.3
# Software-specific (NOT bare "engineer"). "software" catches "Software Engineer".
DEV_SLUG = (
    "developer", "software", "react", "-node", "node-", "python", "typescript", "javascript",
    "full-stack", "fullstack", "front-end", "frontend", "back-end", "backend", "web-develop",
    "programmer", "sdet", "data-eng", "data-engineer", "machine-learning", "ml-engineer",
    "ai-engineer", "devops", "cloud-engineer", "application-develop",
)


def fetch() -> list[Job]:
    hrefs: set[str] = set()
    for listing in LISTINGS:
        for p in range(MAX_PAGES):
            url = f"{BASE}{listing}?start={p * 20}"
            try:
                html = requests.get(url, headers=UA, timeout=30).text
            except Exception as e:  # noqa: BLE001
                log.warning("motion listing %s failed: %s", url, e)
                break
            found = [h for h in HREF.findall(html) if "/contract/" in h or "/direct-hire/" in h]
            new = [h for h in found if h not in hrefs]
            hrefs.update(found)
            time.sleep(THROTTLE)
            if not new:  # exhausted — or, on the first page, the listing path is dead
                if p == 0:
                    log.warning("motion listing %s yielded no postings — path dead or markup "
                                "changed", listing)
                break
        else:
            # Never reached while the site paginates as it does; if it is, the stop condition has
            # stopped working and the count below is a floor, not a total.
            log.warning("motion listing %s hit MAX_PAGES=%d — pagination may have changed",
                        listing, MAX_PAGES)

    dev = [h for h in hrefs if any(t in h.lower() for t in DEV_SLUG)]
    jobs: list[Job] = []
    for h in dev:
        u = BASE + h
        try:
            page = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("motion job fetch failed: %s", e)
            continue
        jps = _jsonld.jobpostings(page)
        if jps:
            jobs.append(_to_job(jps[0], u))
        time.sleep(THROTTLE)

    log.info("motion: %d jobs (from %d dev listing urls)", len(jobs), len(dev))
    return jobs


def _to_job(jp: dict, url: str) -> Job:
    metro, remote = _jsonld.location(jp)
    return posting(
        title=jp.get("title") or "",
        company=_jsonld.company(jp) or AGENCY,
        link=url,
        source="motion",
        description=_jsonld.description(jp),
        employment_type=_jsonld.employment_type(jp),
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=_jsonld.salary(jp),
        posted=_jsonld.posted(jp),
    )
