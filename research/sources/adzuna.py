"""Adzuna — free US aggregator. Contract and permanent are two queries, and the JD is the detail page.

Two things this module got wrong for a month, both found by measuring the live API rather than by
reading the code, and both fixed here.

**`contract_type` is absent from an unfiltered `/search` row.** A 20-row sweep of `software engineer`
came back with the key simply missing from most results, so every posting was emitted as
`Employment type: unspecified` — which quietly deleted the contract-versus-permanent cut, the single
most important one in the report. Adding `contract=1` or `permanent=1` to the query populates it on
**every** row (20/20 on both, measured 2026-07-22). So this source now runs each search term twice,
once per filter, and labels the rows from the query that returned them.

**`description` is hard-truncated to exactly 500 characters.** Every row, on every query — the tail is
an ellipsis mid-word. Anything reading it was reading the top of an ad. Adzuna's own `/details/{id}`
page carries the whole thing, so the JD is fetched from there through `core.fetch`. Measured over 43
contract postings: a rate was extractable from **17** teasers and from **38** untruncated JDs, and one
of the 17 (`$96/hr` from the teaser, `$77-87/hr` from the ad) was simply the wrong number. Truncation
does not only lose rates; it invents them.

The detail fetch needs a guard and it is the load-bearing line here. Adzuna serves a CloudFront 403
interstitial under load, HTTP 200, ~666 characters, and `core.fetch` has no way to know it is not a job
description — at four concurrent workers 12 of 25 pages came back that way and would have been stored
as JD text. `_is_same_ad` refuses any page that does not contain the teaser it is supposed to be the
rest of. At three workers and a one-second throttle the failure rate falls to ~14%, and those keep the
teaser and are marked `title_only`, because a 500-character opener is not a job description that was
read.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from core.fetch import fetch_jd
from core.models import Job

from ._env import key
from core.scrapers.posting import posting
from ._query import TERMS

log = logging.getLogger(__name__)

# Adzuna's terms require attribution wherever their data appears. It rides on every record rather than
# in a render template — see `_posting.py` and the registry's drop guard.
ATTRIBUTION = "Job data from Adzuna (https://www.adzuna.com)"

RESULTS_PER_PAGE = 50
MAX_PAGES = 1
MAX_DAYS_OLD = 3      # a live req goes stale fast; the frozen pipeline ran this at 3 days
THROTTLE = 1.0        # be polite; Adzuna free rate limits are undocumented

# One query per (term, filter). Doubling the request count is the point of the ticket: the label has
# to come from the query, because the row does not reliably carry one. The cost is real and is written
# down — filtering also drops everything Adzuna has not classified, and it has not classified most of
# it: `software engineer` matches 9,550 ads, of which 385 are tagged contract and 278 permanent. An
# unlabelled ad in a contract-vs-perm aggregate is noise, so losing it is the direction to lose in.
FILTERS: tuple[tuple[str, str], ...] = (("contract", "contract"), ("permanent", "permanent"))

DETAIL_URL = "https://www.adzuna.com/details/{id}"
DETAIL_WORKERS = 3     # measured: 4 with no throttle got 12 of 25 pages 403'd; 3 at 1.0s got 0
DETAIL_THROTTLE = 1.0
_SAME_AD_CHARS = 120   # of squashed teaser that a real detail page must contain


def fetch() -> list[Job]:
    app_id, app_key = key("ADZUNA_APP_ID"), key("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        log.info("adzuna: no credentials, skipping")
        return []

    seen: set[str] = set()
    rows: list[tuple[dict, str]] = []
    for param, label in FILTERS:
        for term in TERMS:  # national US sweep — location comes from each result
            for page in range(1, MAX_PAGES + 1):
                url = f"https://api.adzuna.com/v1/api/jobs/us/search/{page}"
                params = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": RESULTS_PER_PAGE,
                    "what": term,
                    "max_days_old": MAX_DAYS_OLD,
                    "sort_by": "date",
                    "content-type": "application/json",
                    param: 1,
                }
                try:
                    r = requests.get(url, params=params, timeout=30)
                    r.raise_for_status()
                    results = r.json().get("results", [])
                except Exception as e:  # noqa: BLE001
                    log.warning("adzuna query failed (%s/%s p%d): %s", label, term, page, e)
                    time.sleep(THROTTLE)
                    continue
                for item in results:
                    link = item.get("redirect_url", "")
                    if not link or link in seen:
                        continue
                    seen.add(link)
                    rows.append((item, label))
                time.sleep(THROTTLE)

    full = _full_descriptions([item for item, _ in rows])
    jobs = [_to_job(item, filtered_as=label, full_description=full.get(str(item.get("id") or ""), ""))
            for item, label in rows]
    log.info("adzuna: %d jobs (%d full JDs, %d left on the 500-char teaser)",
             len(jobs), len(full), len(jobs) - len(full))
    return jobs


def _squash(text: str) -> str:
    """Letters and digits only. Adzuna's API and its own detail page disagree about whitespace for the
    same ad (`info_outline X In` against `info_outline\\nXIn`), so a whitespace-preserving comparison
    would reject good pages."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _is_same_ad(teaser: str, page_text: str) -> bool:
    """Is this page the rest of that ad, or is it an error page wearing a 200?

    Adzuna answers under load with a CloudFront `403 ERROR` interstitial that `core.fetch` accepts as a
    full JD — nothing in the chain can tell it apart from a short job description. The teaser is the
    only thing known to be genuinely from this ad, so requiring the page to contain it is the check.
    Failure direction: a rate extracted from a page belonging to a different job, or from an error
    message, both of which enter the report as an employer's number.
    """
    head = _squash(teaser)[:_SAME_AD_CHARS]
    return bool(head) and head in _squash(page_text)


def _full_descriptions(items: list[dict]) -> dict[str, str]:
    """`{adzuna id: the whole ad}` for the rows whose detail page verified. Missing = keep the teaser."""
    def one(item: dict) -> tuple[str, str]:
        jid = str(item.get("id") or "")
        if not jid:
            return "", ""
        job = Job(link=DETAIL_URL.format(id=jid))
        fetch_jd(job)          # never raises; records fetch_error and degrades
        time.sleep(DETAIL_THROTTLE)
        text = job.fetched_jd.strip()
        return jid, text if _is_same_ad(item.get("description") or "", text) else ""

    if not items:
        return {}
    with ThreadPoolExecutor(DETAIL_WORKERS) as pool:
        return {jid: text for jid, text in pool.map(one, items) if jid and text}


def _to_job(item: dict, *, filtered_as: str = "", full_description: str = "") -> Job:
    desc = full_description or (item.get("description", "") or "")
    loc = (item.get("location") or {}).get("display_name", "") or ""
    # Populated on every filtered row; `filtered_as` is the query that returned it, and is the answer
    # when Adzuna omits the field anyway. "unspecified" now means a caller built a Job by hand.
    ctype = (item.get("contract_type", "") or "") or filtered_as
    ctime = item.get("contract_time", "") or ""    # full_time | part_time | ""
    remote = "remote" in (str(item.get("title", "")) + " " + desc + " " + loc).lower()
    metro = "Remote" if remote else loc
    # Adzuna's salary is usually a MODEL PREDICTION, not an employer's number: a live 50-row US
    # sample came back 100% `salary_is_predicted: "1"` with salary_min == salary_max — a point
    # estimate. So a predicted figure is not printed at all, only named. The alternative — printing
    # it with a label — puts a machine-generated salary into JD text that `core/rates.py` then reads
    # as a posted rate, and the label does not survive the extraction. A missing number is
    # recoverable; a laundered one is what damages a negotiation.
    # An absent flag is treated as predicted, because unknown provenance is not evidence.
    smin, smax = item.get("salary_min"), item.get("salary_max")
    predicted = str(item.get("salary_is_predicted") or "1") == "1"
    if not (smin or smax):
        rate = ""
    elif predicted:
        rate = "not stated (Adzuna's figure is PREDICTED, not posted — withheld)"
    else:
        rate = f"${int(smin or 0)}-{int(smax or 0)}/yr (posted)"
    job = posting(
        title=item.get("title") or "",
        company=(item.get("company", {}) or {}).get("display_name", ""),
        link=item.get("redirect_url", ""),
        source="adzuna",
        description=desc,
        employment_type=f"{ctype or 'unspecified'} {ctime}".strip(),
        metro=metro,
        cadence="remote" if remote else "",
        rate=rate,
        posted=str(item.get("created") or "")[:10],  # Adzuna ISO timestamp
        attribution=ATTRIBUTION,
    )
    if not full_description:
        # The text is a 500-character opener, not a JD that was read. `jd_source` is what the
        # retrospective counts its own coverage with, and overstating it there is how a teaser gets
        # reported as a job description. Understating costs one row of coverage; the text is still on
        # the record for anything that wants it.
        job.jd_source = "title_only"
    return job
