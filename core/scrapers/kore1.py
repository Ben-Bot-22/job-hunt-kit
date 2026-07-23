"""KORE1 — SmartSearch (classic ASP) portal. List page gives jo_num + title; detail pages carry
JSON-LD JobPosting. Dev-filter titles on the list, then parse each detail's JSON-LD. No Cloudflare.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from urllib.parse import urljoin

import requests

from core.models import Job

from . import jsonld as _jsonld
from .posting import posting

log = logging.getLogger(__name__)

AGENCY = "KORE1"
BASE = "https://search10.smartsearchonline.com/koreone/jobs/"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
ITEM = re.compile(r"<h2[^>]*>([^<]+)</h2>.*?jobdetails\.asp\?jo_num=(\d+)", re.S | re.I)
MAX_JOBS = 60
THROTTLE = 0.3
# Software-specific (KORE1 is heavily NON-software engineering staffing — don't match bare "engineer").
DEV_TITLE = (
    "developer", "software engineer", "software develop", "full stack", "fullstack",
    "front end", "frontend", "back end", "backend", "react", "node", "python", "typescript",
    "javascript", "programmer", "sdet", "qa engineer", "data engineer", "data scien",
    "devops", "cloud engineer", "web develop", "machine learning", "ai engineer", "ml engineer",
    "application develop", ".net develop",
)


def fetch() -> list[Job]:
    try:
        html = requests.get(BASE, headers=UA, timeout=30).text
    except Exception as e:  # noqa: BLE001
        log.warning("kore1 list failed: %s", e)
        return []

    seen: set[str] = set()
    dev: list[tuple[str, str]] = []
    for title, jo in ITEM.findall(html):
        if jo in seen:
            continue
        seen.add(jo)
        t = " ".join(_html.unescape(title).split())
        if any(k in t.lower() for k in DEV_TITLE):
            dev.append((t, jo))

    dev = dev[:MAX_JOBS]

    jobs: list[Job] = []
    for title, jo in dev:
        u = urljoin(BASE, f"jobdetails.asp?jo_num={jo}")
        try:
            page = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("kore1 detail failed: %s", e)
            continue
        jps = _jsonld.jobpostings(page)
        jobs.append(_to_job(jps[0], u, title) if jps else _fallback(page, u, title))
        time.sleep(THROTTLE)

    log.info("kore1: %d jobs (from %d dev titles)", len(jobs), len(dev))
    return jobs


def _to_job(jp: dict, url: str, list_title: str) -> Job:
    metro, remote = _jsonld.location(jp)
    return posting(
        title=jp.get("title") or list_title,
        company=_jsonld.company(jp) or AGENCY,
        link=url,
        source="kore1",
        description=_jsonld.description(jp),
        employment_type=_jsonld.employment_type(jp),
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=_jsonld.salary(jp),
        posted=_jsonld.posted(jp),
    )


def _fallback(page: str, url: str, list_title: str) -> Job:
    text = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))
    return posting(title=list_title, company=AGENCY, link=url, source="kore1",
                   description=text[:6000])
