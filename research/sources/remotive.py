"""Remotive — small, keyless, and the only source found that posts hourly contract rates as strings.

**Considered and rejected as a job-input channel, and kept here instead**, same as Himalayas: this is
market data, not supply. Remotive's own API terms (returned in the payload, under `0-legal-notice`)
say it plainly — *"Please do not submit Remotive jobs to third Party websites"*, and *"link back to
the URL found on Remotive AND mention Remotive as a source"*. A research aggregate over the feed is
what that permits; piping its rows into a daily apply list is not.

**Why it earns its place despite the size.** The whole feed is one page of ~41 jobs, of which ~10 are
software. But measured live on 2026-07-22, four of them carried an **hourly** pay string —
`$90 - $150 /hour`, `$120 - $170 /hour`, `$50-$75 /hour`, `$18 - $22/hr` — and every one of those was
a `contract` or `freelance` row. Nothing else keyless in this registry hands back an hourly contract
rate as text: Adzuna's is a model's annualised point estimate, Himalayas is 39-of-39 annual, and CALC+
is a federal ceiling rather than an offer. Four rows a month is a thin distribution, and it is real
posted money in the unit a contract is negotiated in, so `core.rates` reads it directly.

**The API ignores every parameter.** `category`, `search` and `limit` all return the same 41 rows
(verified live: `limit=5` and `limit=100` gave identical counts, and `category=software-development`
still returned Medical and Sales). So the fetch is one unparameterised GET and the dev cut is made
here. That also keeps us inside Remotive's stated rate limit, which is a request budget rather than a
throttle: *"you only need to GET Remotive job data ... a couple of times a day (we advise max. 4
times a day)"*. One request per pull, and the report is monthly.
"""
from __future__ import annotations

import logging

import requests

from core import rates
from core.models import Job

from core.scrapers.posting import posting, strip_html

log = logging.getLogger(__name__)

ATTRIBUTION = "Job data from Remotive (https://remotive.com), linked back to its Remotive listing"

BASE = "https://remotive.com/api/remote-jobs"
UA = {"User-Agent": "jobs-db market research (https://github.com/)"}

# Remotive's own `category` strings, matched exactly. The feed is broad (Medical, Sales, Writing) and
# the report is about developer pay, so this is the cut. `Information Technology` is deliberately out:
# on this board it is helpdesk and sysadmin support, which is a different market.
DEV_CATEGORIES = ("Software Development", "Devops", "Artificial Intelligence",
                  "Data and Analytics", "Quality Assurance")


def fetch() -> list[Job]:
    try:
        r = requests.get(BASE, headers=UA, timeout=30)
        r.raise_for_status()
        rows = r.json().get("jobs") or []
    except Exception as e:  # noqa: BLE001 — an unreachable feed is a gap in one section, not a crash
        log.warning("remotive feed failed: %s", e)
        return []

    jobs = [_to_job(item) for item in rows if item.get("category") in DEV_CATEGORIES]
    log.info("remotive: %d dev jobs (from %d rows, one request)", len(jobs), len(rows))
    return jobs


def _to_job(item: dict) -> Job:
    return posting(
        title=item.get("title") or "",
        company=item.get("company_name") or "",
        # Remotive's own URL, not the employer's — their terms require the link back, and it is the
        # other half of why this is a research source rather than a channel: you cannot apply from it.
        link=item.get("url") or "",
        source="remotive",
        description=strip_html(item.get("description") or ""),
        employment_type=item.get("job_type") or "",
        metro=item.get("candidate_required_location") or "",
        cadence="remote",
        # The point of this source. `salary` is free text an employer typed — "$90 - $150 /hour",
        # "$150k - $230k" — so the shared extractor is the thing that reads it, not a parser here.
        rate=rates.extract(item.get("salary") or "") or "",
        posted=str(item.get("publication_date") or "")[:10],
        attribution=ATTRIBUTION,
    )
