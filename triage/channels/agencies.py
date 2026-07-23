"""The `agencies` channel — six staffing firms' own job boards, read as job input.

This is the only source of **contract** supply in the tree. `boards` is a watchlist of product
companies and returns permanent roles; `paste` is whatever you hand it; the mail channel is whatever
the alerts send. Agency contract work is a first-class tier in this profile's rubric, and the firms
that carry it — Motion, TEKsystems, Insight Global — publish their reqs on a public board with no key
and no OAuth.

    channels:
      agencies:
        enabled: true
        sources: [insightglobal, teksystems, motion, mondo]

**This module is the wrapper, not the scraping.** The scrapers live in `core/scrapers/` because they
have two consumers — this channel (job input) and `research/sources/` (market supply) — and a leaf may
not import another leaf. `core.scrapers.AGENCIES` is a `name -> fetch() -> list[Job]` dict, and
nothing here changes what a scraper returns: the jobs already arrive with company, title, a
`YYYY-MM-DD` posted date and `jd_source="full"`, so `__main__._fetch` leaves them alone exactly as it
does a board's postings. What this module adds is the four things a *daily* consumer needs and a
monthly report does not — the freshness window, a per-source cap, per-source isolation, and a loud
zero.

**What this channel does to dedup, measured rather than assumed.** The ticket expected cross-agency
duplicates — several firms reselling one client req — and the first live run found none: 152 postings
collapsed to 147 clusters, and all 5 merges were *within* one agency's own board. Two firms shopping
the same req do not publish the same text; each anonymizes the client and rewrites the description, so
the 5-gram overlap gate never approaches 0.80. The duplicate this channel really produces is the same
firm listing a req twice, and that collapses cleanly at cos 0.975–1.000.

**Why a zero is loud here.** These scrapers parse live HTML and they fail by returning zero, not by
raising; `core/scrapers/__init__.py` says so at length. For the monthly report a silent zero costs one
line of a table. For a channel feeding the morning worklist it is worse than that: a rotted scraper
looks exactly like a quiet market, indefinitely. So an enabled source that returns nothing gets a
WARNING naming it, and the per-source counts ride onto the run's own health line —
`agencies 45 (insightglobal 30, teksystems 12, motion 3, mondo 0 ⚠)`. It does **not** raise: one dead
board must not cost the run.

The `⚠` fires on the RAW count being zero, not on the in-window count. A source that returned 80
postings of which none are inside a three-day window is a quiet week, not rot, and a warning that
fires on quiet weeks is one that gets ignored — at which point the only rot detector this channel has
is dead.

**Why the sources run concurrently.** Measured live 2026-07-22, one fetch each: insightglobal 87 jobs
in 15s, teksystems 78 in 131s, motion 27 in 25s, mondo 15 in 21s. Serially that is 192s of wall-clock
in front of every model call in the run; concurrently it is TEKsystems' run and nothing else — this
channel's first live fetch, same day, returned 152 postings from all four in **147s**. They are pure
network waits against four unrelated hosts, so threads are the cheap answer, and there is no
politeness argument against them — each scraper still throttles itself against its own host.

The deadline is a ceiling on the worst case rather than a kill switch: a source still running when it
passes is *abandoned*, because a thread cannot be interrupted mid-request. Its scraper keeps running
until its own per-request timeouts expire while the channel moves on without it. That is the right
trade for a source that has hung — the alternative is a morning run that never starts.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from datetime import date, datetime, timedelta, timezone
from time import monotonic

from .. import config
from core.models import Job
from core.scrapers import AGENCIES

log = logging.getLogger("triage.channels.agencies")

# The four sources measured healthy on 2026-07-22: insightglobal 87, teksystems 78, motion 27,
# mondo 15. **`apex` and `kore1` are deliberately absent** — they returned 3 and 2 postings with no
# error, which is precisely the documented silent-zero failure, and Apex's own module docstring
# predicts it (its keyword filter is AJAX-gated, so a plain GET sees a shallow slice). Nothing in the
# code can tell a rotted scraper from a genuinely small board, so they are excluded rather than
# deleted: they are still market supply in `research/sources/`, and putting one back is one config
# line. What would put it back is a fetch returning a DOUBLE-DIGIT count whose postings survive a
# spot-check — at that point add the name here and say so in the commit.
DEFAULT_SOURCES = ("insightglobal", "teksystems", "motion", "mondo")

# Per-source cap, applied AFTER the freshness window and newest-first — the same shape and the same
# reason as `boards._MAX_PER_BOARD`. An agency that republishes its whole board at once should cost
# one noisy run, not a run that never finishes.
_MAX_PER_SOURCE = 200

# Wall-clock ceiling for the whole channel, in seconds. TEKsystems' healthy run is 131s and the four
# run concurrently, so this is a hang detector with room to spare rather than a performance knob.
#
# One shared DEADLINE rather than a timeout per source: the sources are waited on one after another,
# so four per-source ceilings of 300s would stack into twenty minutes in front of a run that is
# supposed to be bounded. A deadline bounds the channel, which is the number that actually matters.
# See the module docstring on why a source past it is abandoned rather than stopped.
_DEADLINE = 300.0

# The last run's per-source counts, as `name -> (raw, kept)`: what the scraper returned, and what
# survived the freshness window and the cap. A module-level side channel because `fetch(days, sample)`
# is the registry's contract — the same trade `channels.LAST_RUN` and `paste._URLS` make. It reaches
# the health line through `channels.DETAIL`, an explicit table next to `ALL`. Single-process, written
# once per run, read immediately after.
LAST_COUNTS: dict[str, tuple[int, int]] = {}


def _posted(job: Job) -> date | None:
    """Every scraper states the date as `YYYY-MM-DD` or as '' — see `core.scrapers.jsonld.posted`."""
    try:
        return date.fromisoformat((job.posted_hint or "").strip()[:10])
    except ValueError:
        return None


def _in_window(jobs: list[Job], since: date | None) -> list[Job]:
    """Newest first, undated last, then capped — so the cap cuts the stale end.

    An undated posting is KEPT, for the reason `boards._newest_first` keeps one: a source that stopped
    stating dates would otherwise go permanently silent, which is the failure you cannot notice. The
    cost is one noisy run, because from the second run on `seen.json` filters it — an agency job's id
    is the agency name and the title, and the scraper states both.
    """
    dated = [(d, j) for j in jobs if (d := _posted(j)) and (since is None or d >= since)]
    dated.sort(key=lambda r: r[0], reverse=True)
    undated = [j for j in jobs if _posted(j) is None]
    return ([j for _, j in dated] + undated)[:_MAX_PER_SOURCE]


def _one_source(fn, since: date | None) -> tuple[int, list[Job]]:
    """One scraper: its raw count, and the jobs that survived the window. Raising is the caller's.

    A posting with no link is nothing to apply to, and one with no title would take the id
    `<agency>||` — shared with every other title-less posting from that agency. Both are dropped
    before the raw count, so the count means "postings I could actually use".
    """
    got = [j for j in fn() if isinstance(j, Job) and j.link and j.title]
    return len(got), _in_window(got, since)


def counts_detail() -> str:
    """`insightglobal 30, teksystems 12, motion 3, mondo 0 ⚠` — the parenthetical on the health line.

    The number is what the source CONTRIBUTED, after the window; the `⚠` is on its raw count being
    zero. See the module docstring for why those are two different numbers.
    """
    return ", ".join(f"{name} {kept}" + ("" if raw else " ⚠")
                     for name, (raw, kept) in LAST_COUNTS.items())


def fetch(days: int, sample: int | None = None, *,
          sources: list[str] | None = None, agencies=AGENCIES) -> list[Job]:
    """The channel contract: every posting on the enabled agency boards inside the freshness window.

    `sources` and `agencies` are keyword-only injection points for the tests — the registry calls this
    with two positional arguments and gets the configured source list and the real scrapers.

    Each SOURCE is wrapped in its own `try/except`, inside the registry's per-CHANNEL one. A scraper
    that raises on restructured markup, a host that 403s, a source still running at `_DEADLINE` —
    each costs that agency's postings and nothing else.
    """
    names = list(sources if sources is not None else config.agency_sources() or DEFAULT_SOURCES)
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)) if days and days > 0 else None

    LAST_COUNTS.clear()
    jobs: list[Job] = []
    pool = ThreadPoolExecutor(max_workers=max(1, len(names)), thread_name_prefix="agencies")
    futures = {}
    try:
        for name in names:
            fn = agencies.get(name)
            if fn is None:
                log.warning("agencies: unknown source %r — known: %s", name, ", ".join(agencies))
                continue
            futures[name] = pool.submit(_one_source, fn, since)
        deadline = monotonic() + _DEADLINE
        for name, future in futures.items():
            try:
                raw, got = future.result(timeout=max(0.0, deadline - monotonic()))
            except _FutureTimeout:
                log.warning("agencies: %s was still running at the %.0fs deadline — abandoned for "
                            "this run", name, _DEADLINE)
                LAST_COUNTS[name] = (0, 0)
                continue
            except Exception as e:  # noqa: BLE001 — one rotted scraper shouldn't cost the others
                log.warning("agencies: %s failed: %s: %s", name, type(e).__name__, e)
                LAST_COUNTS[name] = (0, 0)
                continue
            LAST_COUNTS[name] = (raw, len(got))
            if raw:
                log.info("agencies: %s — %d posting(s), %d in the window", name, raw, len(got))
            else:
                # The documented failure mode, said out loud. These scrapers do not raise when a site
                # restructures — they return nothing. Treat it as a bug report, not an empty market.
                log.warning("agencies: %s returned ZERO postings — this scraper fails by returning "
                            "zero, so read it as rot until a live check says otherwise", name)
            jobs.extend(got)
    finally:
        # Not a `with` block: a timed-out source's thread cannot be interrupted, and waiting on it
        # here is exactly the wall-clock the timeout exists to bound.
        pool.shutdown(wait=False, cancel_futures=True)

    return jobs[:sample] if sample else jobs
