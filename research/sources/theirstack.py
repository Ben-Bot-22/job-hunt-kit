"""TheirStack — recruiting-agency job search via the v1/jobs/search API.

PAID: 1 credit per job *returned* (blur off). Throttled weekly (config every_days) + capped
(max_jobs) to protect credits. Filters confirmed from Ben's app cURL; auth uses THEIRSTACK_KEY
(.env API key, not the app session token). Field names confirmed via a free blur-preview.
"""
from __future__ import annotations

import logging
import time

import requests

from core.models import Job

from ._env import key
from core.scrapers.posting import posting

log = logging.getLogger(__name__)

ENDPOINT = "https://api.theirstack.com/v1/jobs/search"

# Confirmed filter body (remote-only, US, recruiting agency, contract/freelance/temp).
FILTERS = {
    "company_type": "recruiting_agency",
    "remote": True,
    "job_location_or": [{"id": 6252001}],  # United States
    "job_title_or": ["Developer", "Software Engineer"],
    # Tightened 2026-06-23 to cut BI/CRM/reporting noise (TheirStack ran 24% actionable).
    # Deliberately NO bare-"Developer" phrases (avoid any chance of clipping real software roles);
    # the scorer SKIPs BI/DB roles anyway. To REVERSE: restore ["intern", "Java", ".Net", "Salesforce"].
    "job_title_not": ["intern", "Java", ".Net", "Salesforce",
                      "Business Intelligence", "Power BI", "Tableau", "Qualtrics", "Twilio",
                      "ServiceNow", "SharePoint", "Workday", "Informatica",
                      "Oracle", "SAP", "Mainframe", "COBOL"],
    "job_description_contains_or": ["developer", "software engineer", "full stack", "react",
                                    "TypeScript", "JavaScript", "Node", "Python"],
    "employment_statuses_or": ["temporary", "contract", "freelance"],
}
PER_PAGE = 25    # free plan caps results-per-page at 25 (error E-020 above this)
POSTED_DAYS = 3  # query window
MAX_JOBS = 160   # a hard credit cap: TheirStack bills 1 credit per job RETURNED, not per match


def fetch() -> list[Job]:
    api_key = key("THEIRSTACK_KEY")
    if not api_key:
        log.info("theirstack: no THEIRSTACK_KEY, skipping")
        return []

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "Accept": "application/json"}
    body = {
        **FILTERS,
        "posted_at_max_age_days": POSTED_DAYS,
        "blur_company_data": False,        # real data — consumes 1 credit/job returned
        "include_total_results": False,
    }

    jobs: list[Job] = []
    page = 0
    while len(jobs) < MAX_JOBS:
        body["page"] = page
        body["limit"] = min(PER_PAGE, MAX_JOBS - len(jobs))
        try:
            r = requests.post(ENDPOINT, headers=headers, json=body, timeout=60)
            r.raise_for_status()
            data = r.json().get("data", [])
        except Exception as e:  # noqa: BLE001
            log.warning("theirstack page %d failed: %s", page, e)
            break
        if not data:
            break
        jobs += [_to_job(x) for x in data]
        if len(data) < body["limit"]:
            break
        page += 1
        time.sleep(0.5)

    log.info("theirstack: %d jobs", len(jobs))
    return jobs[:MAX_JOBS]


def _to_job(item: dict) -> Job:
    remote = bool(item.get("remote"))
    hybrid = bool(item.get("hybrid"))
    cadence = "remote" if remote else ("hybrid" if hybrid else "onsite")
    metro = "Remote" if remote else (item.get("short_location") or item.get("location") or "")

    smin = item.get("min_annual_salary_usd") or item.get("min_annual_salary")
    smax = item.get("max_annual_salary_usd") or item.get("max_annual_salary")
    if item.get("salary_string"):
        rate = item["salary_string"]
    elif smin or smax:
        rate = f"${int(smin or 0)}-{int(smax or 0)} /yr"
    else:
        rate = ""

    seniority = (item.get("seniority") or "").replace("_", " ")
    desc = (f"Seniority: {seniority}. " if seniority else "") + (item.get("description") or "")

    return posting(
        # company_type=recruiting_agency, so the company IS the agency.
        title=item.get("job_title") or "",
        company=(item.get("company") or "").strip() or "TheirStack agency",
        link=item.get("url") or item.get("final_url") or item.get("source_url") or "",
        source="theirstack",
        description=desc[:6000],
        employment_type=",".join(item.get("employment_statuses") or []),
        metro=metro,
        cadence=cadence,
        rate=rate,
        tech=", ".join((item.get("technology_slugs") or [])[:12]),
        posted=str(item.get("date_posted") or "")[:10],
    )
