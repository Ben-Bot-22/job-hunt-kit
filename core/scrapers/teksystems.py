"""TEKsystems — discover /job/ URLs from the daily sitemaps, parse per-job JSON-LD. No Cloudflare.

The board publishes a sitemap index of numbered sub-sitemaps (`/us/en/sitemapN.xml`, 500 URLs each).
We take the index as a *seed* and then keep walking `sitemapN+1` while a sitemap yields **new**
postings, stopping on the first one that yields none — not after a fixed count of sitemaps, so an
index that goes stale or starts truncating shows up as a wrong count rather than a silent −500 URLs.
`MAX_SITEMAPS` is only a runaway guard and logs a warning when it is hit.

**Every request is status-checked and retried once, and that is the whole point of this module's last
repair.** A sitemap that answers 403/503/maintenance-HTML contains no `<loc>` at all, so the old code
— which caught exceptions but never looked at the status — treated a rejected sub-sitemap exactly
like an empty one and dropped ~25-30 dev postings without a word. That is the shape of the 51 this
returned on 2026-07-24 against a board that had not moved: re-measured the same day it returns 80,
and the site's own search API (`POST /widgets`, `ddoKey=refineSearch`) independently reported 1,544
live postings of which 83 match the dev slug filter. The supply did not shrink; a fetch went partly
missing. A partial run now logs at ERROR and says its count is a floor.

Known limitations, probed live 2026-07-24:

- **The dev filter is a URL-slug heuristic** (`DEV_SLUG`), and TEK staffs far more non-software than
  software: 87 of 1,468 unique sitemap postings survive it. A dev role whose title names no
  technology ("Technical Lead", "Consultant") is dropped before its JSON-LD is ever read. Coverage
  here is deliberately shallow and the count is a slice of the board, not the board.
- **The sitemaps lag the board by a few hours.** Cross-checked against the search API on 2026-07-24:
  3 dev postings existed that no sitemap listed yet, and 2 sitemap URLs were already 410. Both are
  small and self-correcting; neither is worth a second discovery path.
- URLs repeat across sub-sitemaps (51 duplicates in 1,519 today), so discovery de-duplicates —
  without it the same posting was fetched and emitted twice and the count itself was inflated.
- `MAX_JOBS` is a politeness budget, not a coverage judgement; at 87 dev URLs it is not binding.
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
NUMBERED = re.compile(r"^(.*/sitemap)(\d+)(\.xml)$")
MAX_SITEMAPS = 20  # runaway guard only — the walk stops on "no new postings". 4 is the live depth.
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


def _get(url: str) -> str | None:
    """One GET, one retry, and a status check — a 403/503 body carries no `<loc>` and no JSON-LD,
    so without the check a rejected request is indistinguishable from an empty page."""
    for attempt in (1, 2):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                log.warning("teksystems fetch failed %s: %s", url, e)
                return None
            time.sleep(THROTTLE)
    return None


def _next_sitemap(url: str) -> str | None:
    """`.../sitemap3.xml` -> `.../sitemap4.xml`; None if the URL is not numbered."""
    m = NUMBERED.match(url)
    return f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}" if m else None


def _discover() -> tuple[list[str], bool]:
    """All /job/ URLs from the sitemaps, de-duplicated. Second value is True if a fetch was lost,
    which makes the returned list a floor rather than the board."""
    idx = _get(SITEMAP_INDEX)
    if idx is None:
        log.error("teksystems sitemap index unreachable — returning 0 jobs")
        return [], True

    pending = [u for u in dict.fromkeys(LOC.findall(idx)) if u.endswith(".xml")]
    if not pending:
        log.error("teksystems sitemap index listed no sub-sitemaps — markup changed")
        return [], True

    seen: dict[str, None] = {}
    tried: set[str] = set()
    partial = False
    while pending:
        sm = pending.pop(0)
        if sm in tried:
            continue
        if len(tried) >= MAX_SITEMAPS:
            # Never reached while the board is ~4 sitemaps deep; if it is, the stop condition has
            # stopped working and the count below is a floor, not a total.
            log.warning("teksystems hit MAX_SITEMAPS=%d — sitemap layout may have changed",
                        MAX_SITEMAPS)
            break
        tried.add(sm)
        body = _get(sm)
        if body is None:
            partial = True  # ~500 URLs / ~30 dev postings lost — say so rather than shrink quietly
            continue
        new = [u for u in LOC.findall(body) if "/job/" in u and u not in seen]
        seen.update(dict.fromkeys(new))
        time.sleep(THROTTLE)
        if new:
            # It carried postings, so the next numbered sitemap may exist whether or not the index
            # named it. No new postings = exhausted, and the walk stops here.
            nxt = _next_sitemap(sm)
            if nxt and nxt not in tried:
                pending.append(nxt)

    return list(seen), partial


def fetch() -> list[Job]:
    urls, partial = _discover()
    dev = [u for u in urls if any(t in u.lower() for t in DEV_SLUG)][:MAX_JOBS]
    if urls and not dev:
        log.error("teksystems: %d postings, none matching the dev slug filter — URL shape changed?",
                  len(urls))

    jobs: list[Job] = []
    stale = 0
    for u in dev:
        page = _get(u)
        if page is None:
            stale += 1
            continue
        jps = _jsonld.jobpostings(page)
        if jps:  # all employment types — wide net
            jobs.append(_to_job(jps[0], u))
        else:
            stale += 1  # pulled posting or JSON-LD gone; a handful is normal, a wave is rot
        time.sleep(THROTTLE)

    log.info("teksystems: %d jobs (from %d dev urls / %d unique postings; %d without JSON-LD)",
             len(jobs), len(dev), len(urls), stale)
    if partial:
        log.error("teksystems: a sitemap fetch was lost — %d jobs is a floor, not the board",
                  len(jobs))
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
