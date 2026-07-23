"""Mondo — discover jobs via SnapHop XML sitemaps, parse per-job JSON-LD. No Cloudflare.

Mondo is a broad-discipline board, so we cheaply pre-filter the sitemap URLs to tech/dev slugs
(to avoid scoring marketing/ops roles), then keep ALL employment types (contract + permanent).
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

AGENCY = "Mondo"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
INDEX = "https://mondo.gosnaphop.com/sitemap.xml"
LOC = re.compile(r"<loc>(.*?)</loc>")
MAX_JOBS = 200
THROTTLE = 0.3

# Cheap slug pre-filter (broad board) — keep tech/dev roles, drop marketing/ops/sales noise.
# Software-specific (NOT bare "engineer"). "software" catches "Software Engineer".
DEV_SLUG = (
    "developer", "software", "react", "-node-", "python", "typescript", "javascript",
    "full-stack", "fullstack", "front-end", "frontend", "back-end", "backend", "web-develop",
    "programmer", "sdet", "data-eng", "data-engineer", "machine-learning", "ml-engineer",
    "ai-engineer", "devops", "cloud-engineer", "application-develop",
)


def fetch() -> list[Job]:
    try:
        idx = requests.get(INDEX, headers=UA, timeout=30).text
    except Exception as e:  # noqa: BLE001
        log.warning("mondo sitemap index failed: %s", e)
        return []

    subs = [u for u in LOC.findall(idx) if "job_sitemap" in u]
    urls: list[str] = []
    for s in subs:
        try:
            urls += LOC.findall(requests.get(s, headers=UA, timeout=30).text)
        except Exception as e:  # noqa: BLE001
            log.warning("mondo sub-sitemap %s failed: %s", s, e)
    urls = [u for u in urls if any(t in u.lower() for t in DEV_SLUG)][:MAX_JOBS]

    jobs: list[Job] = []
    for u in urls:
        try:
            page = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("mondo job fetch failed: %s", e)
            continue
        jps = _jsonld.jobpostings(page)
        if jps:  # all employment types — wide net
            jobs.append(_to_job(jps[0], u))
        time.sleep(THROTTLE)

    log.info("mondo: %d tech jobs (from %d dev-slug urls)", len(jobs), len(urls))
    return jobs


def _to_job(jp: dict, url: str) -> Job:
    metro, remote = _jsonld.location(jp)
    return posting(
        title=jp.get("title") or "",
        company=_jsonld.company(jp) or AGENCY,
        link=url,
        source="mondo",
        description=_jsonld.description(jp),
        employment_type=_jsonld.employment_type(jp),
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=_jsonld.salary(jp),
        posted=_jsonld.posted(jp),
    )
