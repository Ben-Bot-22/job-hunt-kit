"""Insight Global — embedded per-job JSON on find_a_job pages (no Cloudflare).

Each job is a JSON object inside a hidden `<div style="display:none;">{...}</div>`. We parse those
directly (no HTML/CSS scraping) and keep every employment type — the report needs the mix.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote

import requests

from core.models import Job

from .posting import posting

log = logging.getLogger(__name__)

AGENCY = "Insight Global"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
BASE = "https://jobs.insightglobal.com/find_a_job/{page}/?remote=false&miles=false&srch={srch}"
MARKER = 'display:none;">'

# TODO: replace with Ben's exact saved-search terms/URLs when provided.
KEYWORDS = ["software developer", "react", "typescript", "node", "full stack developer"]
MAX_PAGES = 2
THROTTLE = 0.7


def fetch() -> list[Job]:
    dec = json.JSONDecoder()
    seen: set[int] = set()
    jobs: list[Job] = []
    for kw in KEYWORDS:
        for page in range(1, MAX_PAGES + 1):
            url = BASE.format(page=page, srch=quote(kw))
            try:
                text = requests.get(url, headers=UA, timeout=30).text
            except Exception as e:  # noqa: BLE001
                log.warning("insightglobal '%s' p%d failed: %s", kw, page, e)
                continue
            objs = _extract(text, dec)
            if not objs:
                break  # no more results for this keyword
            for o in objs:
                jid = o.get("JobID")
                if jid in seen:
                    continue
                seen.add(jid)
                jobs.append(_to_job(o))  # all employment types — wide net
            time.sleep(THROTTLE)
    log.info("insightglobal: %d jobs", len(jobs))
    return jobs


def _extract(text: str, dec: json.JSONDecoder) -> list[dict]:
    out: list[dict] = []
    i = text.find(MARKER)
    while i != -1:
        start = i + len(MARKER)
        try:
            obj, _ = dec.raw_decode(text, start)
            if isinstance(obj, dict) and "JobID" in obj:
                out.append(obj)
        except ValueError:
            pass
        i = text.find(MARKER, start)
    return out


def _to_job(o: dict) -> Job:
    jid = o.get("JobID")
    remote = bool(o.get("IsRemoteJob") or o.get("IsRemote"))
    city, state = o.get("City") or "", o.get("State") or ""
    metro = "Remote" if remote else ", ".join(p for p in (city, state) if p)

    pr = o.get("PayRateStraight") or 0
    sl, sh = o.get("SalaryLow") or 0, o.get("SalaryHigh") or 0
    if pr:
        rate = f"${pr}/hr"
    elif sl or sh:
        hi = max(sl, sh)
        unit = "/hr" if hi < 1000 else "/yr"  # contract rates are hourly, perm are annual
        rate = f"${int(sl)}-{int(sh)}{unit}"
    else:
        rate = ""

    # Duration and applicant count were spreadsheet columns; they survive as JD text because that is
    # where a reader (and `core/rates.py`) can still find them, and nothing aggregates them.
    desc = " ".join(s for s in (
        str(o.get("Description") or ""),
        "Requirements: " + str(o.get("Requirements") or ""),
        "Skills: " + str(o.get("Skills") or ""),
        f"Duration: {o['JobDuration']}." if o.get("JobDuration") else "",
        f"Applicants: {o['ApplicantCount']}." if o.get("ApplicantCount") else "",
    ) if s)

    return posting(
        title=o.get("Title") or "",
        company=AGENCY,
        link=f"https://jobs.insightglobal.com/jobapplynoaccount.aspx?jobid={jid}",
        source="insightglobal",
        description=desc,
        employment_type=",".join(o.get("JobType") or []),
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=rate,
        posted=str(o.get("PostedDate") or o.get("DatePosted") or o.get("DateAdded") or "")[:10],
    )
