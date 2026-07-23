"""Motion Recruitment — paginate the tech-jobs listing, parse per-job JSON-LD.

Cloudflare-fronted but passes with a browser UA from a residential IP (the local-run advantage).
Covers both contract and direct-hire (wide net); dev-slug-filters the listing URLs.
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
LISTINGS = ["/tech-jobs/contract", "/tech-jobs/direct-hire"]
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
HREF = re.compile(r'href="(/tech-jobs/[^"]*?/\d+)"')
MAX_PAGES = 6
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
            if not new and p > 0:  # pagination exhausted
                break

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
