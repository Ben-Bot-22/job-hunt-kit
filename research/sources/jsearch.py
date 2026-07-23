"""JSearch (RapidAPI) — Google for Jobs aggregator (broad market, like Adzuna).

Bills PER REQUEST (not per job): each /search call = 1 request, ~10 jobs. One query per search
term with country=us (returns remote + onsite) = ~N requests/run. Free tier = 200 req/mo.
Filtering is coarse: JSearch has no exclude/NOT or description-keyword filter — role/location come
from the free-text query; the scorer handles lane. Throttled (config every_days) to protect quota.
"""
from __future__ import annotations

import logging
import time

import requests

from core.models import Job

from ._env import key
from core.scrapers.posting import posting
from ._query import TERMS

log = logging.getLogger(__name__)

BASE = "https://jsearch.p.rapidapi.com/search-v2"  # v1 /search was retired; v2 wraps jobs in data["jobs"]
HOST = "jsearch.p.rapidapi.com"
DATE_POSTED = "3days"  # one request per term is one of 200/month — buy freshness, not volume
THROTTLE = 0.5


def fetch() -> list[Job]:
    rapidapi_key = key("RAPIDAPI_KEY")
    if not rapidapi_key:
        log.info("jsearch: no RAPIDAPI_KEY, skipping")
        return []

    headers = {"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": HOST}
    seen: set[str] = set()
    jobs: list[Job] = []
    for term in TERMS:  # one request per term; country=us returns remote + onsite
        params = {"query": term, "page": "1", "num_pages": "1",
                  "country": "us", "date_posted": DATE_POSTED}
        try:
            r = requests.get(BASE, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            data = (r.json().get("data") or {}).get("jobs", []) or []
        except Exception as e:  # noqa: BLE001
            log.warning("jsearch query failed (%s): %s", term, e)
            time.sleep(THROTTLE)
            continue
        for item in data:
            link = item.get("job_apply_link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            jobs.append(_to_job(item))
        time.sleep(THROTTLE)

    log.info("jsearch: %d jobs (%d requests)", len(jobs), len(TERMS))
    return jobs


def _to_job(item: dict) -> Job:
    is_remote = item.get("job_is_remote")
    city, state = item.get("job_city") or "", item.get("job_state") or ""
    metro = "Remote" if is_remote else ", ".join(p for p in (city, state) if p)
    etype = item.get("job_employment_type") or ""
    smin, smax = item.get("job_min_salary"), item.get("job_max_salary")
    period = item.get("job_salary_period") or ""
    rate = f"{smin or '?'}-{smax or '?'} {period}".strip() if (smin or smax) else ""
    return posting(
        title=item.get("job_title") or "",
        company=item.get("employer_name") or "",
        link=item.get("job_apply_link", ""),
        source="jsearch",
        description=item.get("job_description", "") or "",
        employment_type=etype,
        metro=metro,
        cadence="remote" if is_remote else "onsite",
        rate=rate,
        posted=str(item.get("job_posted_at_datetime_utc") or "")[:10],
    )
