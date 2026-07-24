"""Scion Staffing — paginate the WP Job Board listing, parse per-job JSON-LD. No Cloudflare.

Scion runs Bullhorn behind a WordPress plugin, and the plugin publishes no job sitemap and no REST
route (`wp-json/wp/v2/types` does not expose the job post type), so the listing pagination —
`/search-jobs/?_page=N`, ten jobs a page — is the best discovery route available. Both the parent
board and the tech vertical are crawled and deduped on Bullhorn job id: measured today the vertical
is a strict subset, but it is the board a tech role is *certain* to appear on, so reading only one
of them would make coverage depend on whichever site Scion retires first.

Scion staffs mostly non-tech (nonprofit, legal, medical, finance), so the slugs — which carry title
and location — are dev-filtered before any detail page is fetched. Both contract and permanent are
kept (wide net).

Measured live 2026-07-24: 218 distinct postings (the parent board walks 22 pages; the vertical's 40
are all already in it), of which 15 survive the dev filter. The board carries all three arrangements
— a 25-posting sample ran 10 Direct Hire, 10 Contract, 5 Contract To Hire — and none is filtered
out; that today's 15 dev survivors are all Direct Hire is the board, not the scraper.

**Limitations.** The JSON-LD says `FULL_TIME` on every posting regardless of the real arrangement,
and carries no `baseSalary` and no `jobLocationType`; the truth for all three is in the plugin's
info table on the same page, so employment type and pay rate are read from there and remote is
inferred from the locality string. If that table's markup changes the JSON-LD still parses and every
job silently becomes a full-time one with no rate. Coverage is also shallow by design: the slug
filter refuses a bare "engineer" — Scion lists geotechnical, project and chief engineers — which
costs any software role named without a software word in it. Of the 203 postings it drops today, 23
carry a technical-sounding word and two are arguable losses ("Solutions Architect", "Technical
Engineering Manager, Physical AI"); the rest are data entry, IT directors and analysts.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time

import requests

from core.models import Job

from . import jsonld as _jsonld
from .posting import posting

log = logging.getLogger(__name__)

AGENCY = "Scion Staffing"
# The parent board and the tech vertical. Same Bullhorn feed, deduped on job id.
HOSTS = ["https://scionstaffing.com", "https://sciontechnical.com"]
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
JOB = re.compile(r'href="(https://[^"]*/job/(\d+)/\?jobTitle=([^"]+))"')
# The plugin's info table — the only honest source of employment type and rate (see docstring).
INFO = r'<td class="wpjb-info-label">{}</td>\s*<td[^>]*>(.*?)</td>'
MAX_PAGES = 30
MAX_JOBS = 60
THROTTLE = 0.3
# Software-specific (Scion is heavily NON-software staffing — don't match bare "engineer").
# "software" catches "Software Engineer"; the -platform/-solutions slugs catch the ones that
# would otherwise need it.
DEV_SLUG = (
    "developer", "software", "react", "-node-", "python", "typescript", "javascript",
    "full-stack", "fullstack", "front-end", "frontend", "back-end", "backend", "web-develop",
    "programmer", "sdet", "data-eng", "data-engineer", "machine-learning", "ml-engineer",
    "ai-engineer", "devops", "cloud-engineer", "application-develop", "platform-engineer",
    "web-platform", "solutions-engineer", "agentic-engineer",
)


def fetch() -> list[Job]:
    found: dict[str, tuple[str, str]] = {}  # job id -> (url, slug), first host wins
    for base in HOSTS:
        # The exhaustion test is per host, not against `found`. Sharing one set across the two
        # boards ends the second walk on its first page whenever that page is all duplicates —
        # which is exactly what a subset vertical looks like, so the second board would be dropped
        # entirely at the moment it agreed with the first.
        seen: set[str] = set()
        for p in range(1, MAX_PAGES + 1):
            url = f"{base}/search-jobs/?_page={p}"
            try:
                html = requests.get(url, headers=UA, timeout=30).text
            except Exception as e:  # noqa: BLE001
                log.warning("scion listing %s failed: %s", url, e)
                break
            hits = JOB.findall(html)
            new = [i for _, i, _ in hits if i not in seen]
            seen.update(i for _, i, _ in hits)
            for u, i, slug in hits:
                found.setdefault(i, (u, slug))
            time.sleep(THROTTLE)
            if not new:  # pagination exhausted (the last page repeats nothing new)
                if p == 1:
                    log.warning("scion listing %s yielded no postings — path dead or markup "
                                "changed", base)
                break
        else:
            # 22 pages is the live depth of the parent board; hitting the guard means the walk's
            # stop condition has stopped working and the count below is a floor, not a total.
            log.warning("scion listing %s hit MAX_PAGES=%d — pagination may have changed",
                        base, MAX_PAGES)

    dev = [(i, u) for i, (u, slug) in found.items()
           if any(t in slug.lower() for t in DEV_SLUG)][:MAX_JOBS]

    jobs: list[Job] = []
    for _, u in dev:
        try:
            page = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("scion job fetch failed: %s", e)
            continue
        jps = _jsonld.jobpostings(page)
        if jps:
            jobs.append(_to_job(jps[0], page, u))
        time.sleep(THROTTLE)

    log.info("scion: %d jobs (from %d dev slugs of %d listed)", len(jobs), len(dev), len(found))
    return jobs


def _info(page: str, label: str) -> str:
    """One cell of the plugin's info table, as plain text ('' when the row is absent)."""
    m = re.search(INFO.format(label), page, re.S | re.I)
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else ""


def _to_job(jp: dict, page: str, url: str) -> Job:
    metro, remote = _jsonld.location(jp)
    # The feed never sets jobLocationType; a remote posting says so in the locality instead.
    remote = remote or metro.strip().lower() == "remote"
    return posting(
        title=jp.get("title") or "",
        company=_jsonld.company(jp) or AGENCY,
        link=url,
        source="scion",
        description=_jsonld.description(jp),
        employment_type=_info(page, "Employment Type") or _jsonld.employment_type(jp),
        metro=metro,
        cadence="remote" if remote else "onsite",
        rate=_info(page, "Pay rate") or _jsonld.salary(jp),
        posted=_jsonld.posted(jp),
    )
