"""TEKsystems — discover /job/ URLs from the daily sitemaps, parse per-job JSON-LD. No Cloudflare.

The board is ~1,600 jobs across 4 sitemaps; we dev-slug-filter the URLs (TEK runs many non-dev
roles) and cap with config `max_jobs`, then parse each detail page's schema.org JobPosting.
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

AGENCY = "TEKsystems"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
SITEMAP_INDEX = "https://careers.teksystems.com/sitemap.xml"
LOC = re.compile(r"<loc>(.*?)</loc>")
MAX_JOBS = 150
THROTTLE = 0.25
# Software-specific (NOT bare "engineer" — TEK staffs Network/Electrical/Field engineers too).
# "software" still catches "Software Engineer"; data-eng/ml/devops keep the stretch roles.
DEV_SLUG = (
    "developer", "software", "react", "-node", "node-", "python", "typescript", "javascript",
    "full-stack", "fullstack", "front-end", "frontend", "back-end", "backend", "web-develop",
    "programmer", "sdet", "data-eng", "data-engineer", "machine-learning", "ml-engineer",
    "ai-engineer", "devops", "cloud-engineer", "application-develop",
)


def fetch() -> list[Job]:
    try:
        idx = requests.get(SITEMAP_INDEX, headers=UA, timeout=30).text
    except Exception as e:  # noqa: BLE001
        log.warning("teksystems sitemap index failed: %s", e)
        return []

    job_urls: list[str] = []
    for sm in LOC.findall(idx):
        try:
            urls = LOC.findall(requests.get(sm, headers=UA, timeout=30).text)
        except Exception as e:  # noqa: BLE001
            log.warning("teksystems sub-sitemap %s failed: %s", sm, e)
            continue
        job_urls += [u for u in urls if "/job/" in u]

    dev = [u for u in job_urls if any(t in u.lower() for t in DEV_SLUG)][:MAX_JOBS]

    jobs: list[Job] = []
    for u in dev:
        try:
            page = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("teksystems job fetch failed: %s", e)
            continue
        jps = _jsonld.jobpostings(page)
        if jps:  # all employment types — wide net
            jobs.append(_to_job(jps[0], u))
        time.sleep(THROTTLE)

    log.info("teksystems: %d jobs (from %d dev /job/ urls)", len(jobs), len(dev))
    return jobs


def _to_job(jp: dict, url: str) -> Job:
    metro, remote = _jsonld.location(jp)
    return posting(
        title=jp.get("title") or "",
        company=_jsonld.company(jp) or AGENCY,
        link=url,
        source="teksystems",
        description=_jsonld.description(jp),
        employment_type=_jsonld.employment_type(jp),
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=_jsonld.salary(jp),
        posted=_jsonld.posted(jp),
    )
