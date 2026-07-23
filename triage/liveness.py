"""Is this req still open? A parallel liveness check over the ranked jobs.

Why this exists — the 2026-07-20 run. Ben interviewed all week and applied to nothing. When the 7/13
apply list was re-checked seven days later, **every one of the five picks verifiable at its primary
source had already closed**: Trident ($90/hr, fit 88, "100+ applicants"), Themesoft, Sriven, Randstad,
Encamp. The tool had ranked them beautifully and had no idea any of them were dead.

Worse, freshness at scrape time is not freshness at apply time: VortexLink (fit 82) was scraped
successfully *during* that run and was already gone minutes later. So this check runs at the END of a
run, after ranking, against the jobs Ben would actually act on.

Three states, and the third one matters as much as the other two:

  OPEN    — fetched the page and found no closed-marker.
  CLOSED  — an explicit closed-marker, or HTTP 404/410.
  UNKNOWN — bot-walled, timed out, errored, or the host is an aggregator that NEVER marks a listing
            closed. remotevibecodingjobs shows "Apply for this position" forever. Reporting that as
            OPEN would be a lie, and it is the exact lie that made the 7/13 list look healthy.

Checks run in a thread pool — they are pure network waits, so wall-clock is roughly one request.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from . import config
from core.fetch import _is_block_page
from core.models import Job

log = logging.getLogger("triage.liveness")

OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}

# Verified against real closed postings on 2026-07-20.
_CLOSED_MARKERS = (
    "no longer accepting applications",      # LinkedIn
    "sorry this job is no longer available",  # Dice
    "this job is no longer available",
    "no longer available",
    "this position has been filled",
    "this job posting has expired",
    "job posting is no longer active",
    "applications are closed",
    "we are no longer accepting",
)

# Hosts that re-publish other boards' listings and never expire them. A 200 from these proves the
# aggregator still has a row in its database — nothing about the underlying req. Always UNKNOWN.
_AGGREGATORS = ("remotevibecodingjobs.com", "jobright.ai", "remotezestjobs.com", "vacancytargetjobs.com")

# Hosts that cannot be judged from an anonymous fetch. LinkedIn is the important one: measured
# 2026-07-20 against three reqs confirmed closed in a signed-in browser (Trident, Themesoft, Encamp),
# the public page returned NO closed-marker for any of them — it would have reported all three OPEN.
# The /jobs-guest/ API is no better: "no longer accepting" shows up in boilerplate on open listings and
# is absent on closed ones. A false OPEN is the worst output this module can produce, so LinkedIn is
# reported UNKNOWN and pushed to the browser (Tier-2) path, which is how it was verified by hand.
_NEEDS_SESSION = {"linkedin.com": "LinkedIn needs a signed-in session — verify in the browser (Tier-2)",
                  "indeed.com": "Indeed is bot-walled — verify in the browser (Tier-2)",
                  "glassdoor.com": "Glassdoor is bot-walled — verify in the browser (Tier-2)"}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _is_aggregator(url: str) -> bool:
    host = _host(url)
    return any(host.endswith(a) for a in _AGGREGATORS)


def _needs_session(url: str) -> str | None:
    host = _host(url)
    return next((why for dom, why in _NEEDS_SESSION.items() if host.endswith(dom)), None)


def check_one(url: str, *, timeout: float = 15.0) -> tuple[str, str]:
    """Return (state, detail) for one URL. Never raises — an unreachable page is UNKNOWN, not CLOSED."""
    if not url:
        return UNKNOWN, "no link"
    if _is_aggregator(url):
        return UNKNOWN, "aggregator — never marks listings closed; verify at the primary source"
    if (why := _needs_session(url)):
        return UNKNOWN, why
    try:
        r = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001 — a network failure is not evidence the job closed
        return UNKNOWN, f"unreachable ({type(e).__name__})"
    if r.status_code in (404, 410):
        return CLOSED, f"HTTP {r.status_code}"
    if r.status_code >= 400:
        return UNKNOWN, f"HTTP {r.status_code}"
    text = r.text or ""
    if _is_block_page(text):
        return UNKNOWN, "bot-walled"
    low = text.lower()
    for m in _CLOSED_MARKERS:
        if m in low:
            return CLOSED, f'page says "{m}"'
    return OPEN, ""


def annotate(jobs: list[Job]) -> dict:
    """Check the jobs Ben might actually act on, in parallel, and write the result onto each Job.

    Only non-SKIP jobs that have a link are checked, capped at `liveness.max_check` (highest-ranked
    first) so a 358-job run doesn't fire 358 requests at job boards. Returns a summary dict.
    """
    if not config.liveness_enabled():
        return {}
    targets = [j for j in jobs
               if j.link and j.analysis is not None and j.analysis.verdict != "SKIP"][:config.liveness_max_check()]
    if not targets:
        return {}

    log.info("liveness: checking %d ranked jobs (%d workers)", len(targets), config.liveness_workers())
    with ThreadPoolExecutor(max_workers=config.liveness_workers()) as ex:
        results = list(ex.map(lambda j: check_one(j.link), targets))
    for j, (state, detail) in zip(targets, results):
        j.liveness, j.liveness_detail = state, detail

    summary = {"checked": len(targets),
               "open": sum(1 for s, _ in results if s == OPEN),
               "closed": sum(1 for s, _ in results if s == CLOSED),
               "unknown": sum(1 for s, _ in results if s == UNKNOWN)}
    log.info("liveness: %(open)d open · %(closed)d CLOSED · %(unknown)d unknown", summary)
    return summary
