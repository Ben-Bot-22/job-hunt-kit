"""Agency job scrapers — the six staffing firms that publish a public job board.

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
Insight Global 87, TEKsystems 78, Motion 27, Mondo 15, **Apex 3, KORE1 2**. The last two are either
genuinely small boards or already partly rotted, and nothing in the code can tell you which.

`posting.py` and `jsonld.py` came along because every scraper needs them, and so do the market-only
sources — which now import them from here rather than the other way round.
"""
from __future__ import annotations

from . import apex, insightglobal, jsonld, kore1, mondo, motion, posting, teksystems

# name -> fetch() -> list[Job]. The same shape `research/sources/ALL` uses, so a consumer can iterate
# either registry without caring which one it holds.
AGENCIES = {
    "insightglobal": insightglobal.fetch,
    "teksystems": teksystems.fetch,
    "motion": motion.fetch,
    "mondo": mondo.fetch,
    "apex": apex.fetch,
    "kore1": kore1.fetch,
}

__all__ = ["AGENCIES", "apex", "insightglobal", "jsonld", "kore1", "mondo", "motion", "posting",
           "teksystems"]
