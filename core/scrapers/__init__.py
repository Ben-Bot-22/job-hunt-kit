"""Agency job scrapers — the seven staffing firms that publish a public job board.

**Why these live in `core/` and the rest of the sources do not.** They have two consumers, and that is
the whole reason: `research/sources/` registers them as *market supply* (what is being hired, at what
rate, across a slice of the contract market), and `triage/channels/agencies.py` reads them as *job
input* (postings to score against the rubric). A leaf may not import another leaf — `core/test_layering.py`
enforces it — so code with a consumer in two leaves belongs here. Nothing else moved: BLS, CALC+,
Adzuna, JSearch, TheirStack, Himalayas and Remotive are market data only and stay in `research/sources/`,
which is the documented mirror of `triage/channels/` and a distinction worth keeping.

**These are rot-prone and they fail by returning zero, not by raising.** Each one parses a live listing
page — sitemaps, embedded JSON, JSON-LD — and a site that restructures does not error, it just stops
matching. The per-source counts at the call site are the only detector. Measured live 2026-07-22:
Insight Global 87, TEKsystems 78, Motion 27, Mondo 15, Apex 3, KORE1 2. Both single digits were
investigated on 2026-07-24 and they were two different things.

**Read the RAW scrape count, not the in-window one — they are different numbers and only the raw one
says anything about board health** (2026-07-27). The run summary prints postings *inside the run's
date window*, so a short window makes a healthy board look dead. On 2026-07-27 the raw scrapes were
Insight Global 442, Apex 493, Motion 268, TEKsystems 78, Mondo 13, KORE1 6, Scion 14 — while the
in-window line for the same run read `motion 9` and `scion 0`. Motion's "27" above and its "3" on an
earlier run were both window artifacts of one healthy board. A source is rot-suspect when its *raw*
count collapses; an in-window zero on a 3-day window is usually just a quiet week.

Apex was rot: **re-measured live 2026-07-24 at 150** (capped; the board held 2,604 postings, 488 of
them dev-slug). Its 3 was the silent-zero failure doing exactly what this docstring warns about —
`?page=N` needed a session cookie the scraper never sent, so the loop refetched page one, saw no new
URLs and stopped.

KORE1 was the second kind: re-measured 2026-07-24 it returns **6** of 64 live postings (was 2 — the
list regex anchored on the category heading and kept only the first job under each). 6/64 is now the
title filter doing its job on a mostly non-software board, not rot.

Motion was rot too, and the same shape as Apex plus a dead path: `?page=N` had become a no-op (every
page repeated the first 20), and `/tech-jobs/direct-hire` had started 404ing, which silently took the
whole permanent half with it. Paginating `?start=N` against the combined `/tech-jobs` listing —
which is an exact superset, 327 contract + 470 direct-hire = 797 — **re-measured live 2026-07-24 at
275**, up from 27.

Scion Staffing is new on 2026-07-24 — the sixth firm in the primary tier and the last one unwired —
and it has no baseline to have rotted away from: **first measured at 15**, from 218 distinct
postings on a board that is mostly non-software. It publishes no job sitemap and no REST route, so
it is listing pagination like Motion rather than a sitemap like Mondo.

TEKsystems was a third kind, and the most instructive: **nothing was wrong with the board.** It read
51 on 2026-07-24 against 78 two days earlier, but re-measured the same day it returns **80**, and the
site's own search API independently reported 1,544 live postings of which 83 match the dev slug
filter — so 51 was a partial fetch, not a shrinking board. The scraper caught exceptions but never
checked status codes, and a sub-sitemap answering 403/503 has no `<loc>` in it, so a rejected request
looked exactly like an empty sitemap and cost ~30 dev postings in silence. Requests are now
status-checked and retried once, discovery de-duplicates (51 of 1,519 URLs repeat across sitemaps,
which was inflating the count), the sitemap walk stops on "no new postings" instead of trusting the
index, and a lost fetch logs at ERROR saying the count is a floor.

Counts as of 2026-07-24: **Apex 150, KORE1 6, Motion 275, Scion 15, TEKsystems 80**; Insight Global
and Mondo unchanged from 2026-07-22 and unverified on this date.

`posting.py` and `jsonld.py` came along because every scraper needs them, and so do the market-only
sources — which now import them from here rather than the other way round.
"""
from __future__ import annotations

from . import apex, insightglobal, jsonld, kore1, mondo, motion, posting, scion, teksystems

# name -> fetch() -> list[Job]. The same shape `research/sources/ALL` uses, so a consumer can iterate
# either registry without caring which one it holds.
AGENCIES = {
    "insightglobal": insightglobal.fetch,
    "teksystems": teksystems.fetch,
    "motion": motion.fetch,
    "mondo": mondo.fetch,
    "apex": apex.fetch,
    "kore1": kore1.fetch,
    "scion": scion.fetch,
}

__all__ = ["AGENCIES", "apex", "insightglobal", "jsonld", "kore1", "mondo", "motion", "posting",
           "scion", "teksystems"]
