"""KORE1 — SmartSearch (classic ASP) portal. List page gives jo_num + title; detail pages carry
JSON-LD JobPosting. Dev-filter titles on the list, then parse each detail's JSON-LD. No Cloudflare.

We hit `process_jobsearch.asp?fromsearch=yes` — the unfiltered search — rather than the portal root.
The root renders the same jobs grouped under category headings and drops the odd one; the search
result is a flat superset (measured 2026-07-24: 64 vs 63) and, being flat, it can't be mis-parsed by
grouping. **There is no pagination**: SmartSearch emits the whole board in one page (no next link, no
record-offset parameter), so there is nothing to walk and no page-1 refetch to get wrong.

LIMITATION: the title filter is the only filter, and it is deliberately narrow — KORE1 is mostly
NON-software staffing (accounting, civil/electrical/mechanical engineering, sales, loan officers),
so a bare "engineer" match would flood the run. That means genuinely adjacent titles which name no
technology ("Principal Engineer", "Integration Engineer", "Enterprise Architect") are dropped. Of
64 live postings, 6 pass. Widening this is a rubric question, not a parsing one.
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
SEARCH = "process_jobsearch.asp?fromsearch=yes"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
# One row per posting: the bold link carries the real job title. Anchor on that class — an <h2>-based
# match instead picks up the category heading ("Software Engineer Roles", "Civil Engineer") and, being
# non-greedy, keeps only the first job under each, which is how this scraper came to return 2 of 64.
ITEM = re.compile(
    r'<a[^>]*class="coloredlink bold"[^>]*href="jobdetails\.asp\?jo_num=(\d+)[^"]*"[^>]*>(.*?)</a>',
    re.S | re.I)
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
        html = requests.get(urljoin(BASE, SEARCH), headers=UA, timeout=30).text
    except Exception as e:  # noqa: BLE001
        log.warning("kore1 list failed: %s", e)
        return []

    seen: set[str] = set()
    dev: list[tuple[str, str]] = []
    for jo, title in ITEM.findall(html):
        if jo in seen:
            continue
        seen.add(jo)
        t = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", title)).split())
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

    log.info("kore1: %d jobs (from %d dev titles / %d listed)", len(jobs), len(dev), len(seen))
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
