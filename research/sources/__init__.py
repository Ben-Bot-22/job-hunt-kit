"""Market-data source registry. Add a source = write a `fetch() -> list[Job]`, import it, register it.

**Two registries, same shape, different jobs.** `triage/channels/` is *where my jobs come from*;
this is *where market data comes from*. Keeping the shapes side by side is why this file moved out of
the frozen pipeline intact rather than being redesigned on the way over — the six agency scrapers below
are the only keyless source of **contract** supply anyone found, and the day someone adds a seventh the
thing they should have to read is one dict and one `fetch()` signature.

Each run is wrapped so one failure can't kill the others, and per-source counts come back for the
report's health line. That is the whole error strategy, and it is deliberate: see the rot warning below.

**The six agency scrapers now live in `core/scrapers/` and are imported back here.** They gained a
second consumer — `triage/channels/agencies.py`, which reads them as job input rather than as market
supply — and a leaf may not import another leaf, so shared code goes to `core/`. Nothing about this
registry changed: they are still in `ALL`, still counted, still subject to everything below.

**The six agency scrapers are ROT-PRONE and will break without warning.** `motion`, `apex`, `kore1`,
`insightglobal`, `teksystems` and `mondo` parse live HTML — pagination markup, a listing URL shape, an
embedded JSON blob. When one of those is silently restructured the scraper does not raise; it returns
zero jobs, or worse, fewer. Nothing in the test suite can catch that, and pinning a 2026-07 HTML fixture
would only prove the parser still parses last year's page. **The detector is the count**: a source that
normally returns 40 and returns 0 has broken, and `fetch_all` hands those counts back so a caller can
say so out loud. Treat a zero from an agency as a bug report, not as an empty market.

The three key-gated sources — `adzuna`, `jsearch`, `theirstack` — degrade to an empty list with a log
line when their key is unset. That is the standing zero-key rule: the keyless path is the default and
this module is never gated behind "add a key to unlock".

`himalayas` and `remotive` are the third kind: **keyless documented JSON feeds**, not scraped HTML and
not key-gated. Both were considered and rejected as job-input *channels* and live here instead —
Himalayas because a board that is 87-to-6 permanent is a poor contract search and a good picture of
remote permanent supply, Remotive because its own API terms forbid republishing its rows as listings.
Keeping them one directory away from `triage/channels/` is what makes that decision physical.

**Attribution is an obligation, so it is enforced rather than documented.** `ATTRIBUTION` names every
source whose terms require it, each source stamps its line onto every record it emits (see
`_posting.py`), and `fetch_all` **drops** a job that arrives from such a source without it. A renderer
therefore cannot print this data unattributed by forgetting to; it would have to strip the line first.
`attribution_lines()` is what a report prints, and it names only the sources that actually returned
rows this run.

**Two shapes, one file.** `ALL` is job supply — `fetch() -> list[Job]`. `BASELINES` is the pay
distributions the report anchors against — `fetch_bands() -> list[RateBand]`. They are separate because
CALC+ and BLS do not return postings: they return what a kind of work pays across thousands of
contracts or a whole occupational survey, and inventing a fake `Job` per percentile to fit one registry
would be the mistake. Both baselines are **keyless**, which is what lets the external half of the
report be the default rather than a paywalled tier, and both attach their own caveat and attribution to
every band — see `_baseline.py`.

Knobs (page caps, job caps, query windows) are module constants in each source rather than config. The
old `config.yaml sources:` block died with the pipeline that read it, and the per-source `every_days`
throttle died with it: that throttle existed to protect a paid API from a *daily* cron, and the market
report is invoked monthly on demand. If a later ticket wants these as settings they belong in
`config/settings.yaml` under `core/settings.py`'s schema, not in a second config file.
"""
from __future__ import annotations

import logging

from core.models import Job

from . import adzuna, bls, calc, himalayas, jsearch, remotive, theirstack
# The six agency scrapers live in `core/scrapers/` because they have two consumers: this registry
# (market supply) and `triage/channels/agencies.py` (job input). A leaf may not import another leaf,
# so shared code goes to core — see `core/test_layering.py`. They are still registered here, and the
# market report cannot tell the difference.
from core.scrapers import apex, insightglobal, kore1, mondo, motion, teksystems
from ._baseline import RateBand
from ._env import key

log = logging.getLogger(__name__)

# Keyless. Contract-heavy, scraped, and rot-prone — see the module docstring.
AGENCIES = ("insightglobal", "mondo", "teksystems", "kore1", "motion", "apex")

# Key-gated. Each returns [] with a log line when its .env key is absent.
KEYED = ("adzuna", "jsearch", "theirstack")

# Keyless documented JSON feeds. Permanent-heavy and remote-only, which is why they are market data
# rather than job input — and why they are not in AGENCIES: nothing here parses HTML.
FEEDS = ("himalayas", "remotive")

ALL = {
    "adzuna": adzuna.fetch,
    "jsearch": jsearch.fetch,
    "insightglobal": insightglobal.fetch,
    "mondo": mondo.fetch,
    "teksystems": teksystems.fetch,
    "motion": motion.fetch,
    "apex": apex.fetch,
    "kore1": kore1.fetch,
    "theirstack": theirstack.fetch,
    "himalayas": himalayas.fetch,
    "remotive": remotive.fetch,
}

# The env key(s) each key-gated source needs, and where to get one. This is what lets a report
# explain a zero as "unconfigured — here is the fix" rather than "broken": on a fresh clone the three
# keyed sources return nothing because no key is set, and the supply caveat's "a zero is a broken
# source" is wrong for exactly them. The signup notes mirror `.env.example`, the one place keys go.
KEY_REQUIREMENTS: dict[str, tuple[tuple[str, ...], str]] = {
    "adzuna":     (("ADZUNA_APP_ID", "ADZUNA_APP_KEY"), "free — https://developer.adzuna.com"),
    "jsearch":    (("RAPIDAPI_KEY",),                   "free tier — https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"),
    "theirstack": (("THEIRSTACK_KEY",),                 "paid — https://theirstack.com"),
}


def unconfigured_reason(name: str) -> str | None:
    """For a key-gated source missing its `.env` key(s): a one-line 'skipped — here is how to enable it',
    with the exact variables, the file they go in, and where to sign up. `None` for a keyless source or
    a fully-configured keyed one — those cases are a real count or a real (rot-detecting) zero.

    This is the warn-the-user path for the market report: a stranger who ran `--supply` with no keys
    sees *why* adzuna/jsearch/theirstack are empty and how to fix it, not a bare zero that the caveat
    then mislabels as breakage.
    """
    spec = KEY_REQUIREMENTS.get(name)
    if not spec:
        return None
    variables, where = spec
    missing = [v for v in variables if not key(v)]
    if not missing:
        return None
    return f"skipped — set {' + '.join(missing)} in .env ({where}); see .env.example"


# The sources whose terms require naming them wherever their data appears. Each module owns its own
# string so the obligation sits next to the code that incurs it; this dict is the enforcement point.
# The six agency scrapers are absent deliberately — they carry no such published requirement.
ATTRIBUTION = {
    "adzuna": adzuna.ATTRIBUTION,
    "himalayas": himalayas.ATTRIBUTION,
    "remotive": remotive.ATTRIBUTION,
}

# Pay distributions, not postings. Keyless, both of them — this is the zero-key path the whole module
# is allowed to be a default because of.
BASELINES = {
    "calc": calc.fetch_bands,
    "bls": bls.fetch_bands,
}


def fetch_all(names: tuple[str, ...] | None = None) -> tuple[list[Job], dict[str, int]]:
    """Every named source (default: all of them), and what each returned.

    The counts are the deliverable as much as the jobs are — they are the only thing that can tell you
    an agency scraper has rotted. A crash is logged and counted as 0 rather than raised, because one
    restructured listing page must not cost the whole pull.
    """
    jobs: list[Job] = []
    counts: dict[str, int] = {}
    for name in (names if names is not None else tuple(ALL)):
        fn = ALL.get(name)
        if fn is None:
            log.warning("no such source: %s (have: %s)", name, ", ".join(ALL))
            continue
        try:
            got = fn()
        except Exception as e:  # noqa: BLE001 — one bad source shouldn't kill the run
            log.warning("source %s crashed: %s", name, e)
            got = []
        got = _attributed(name, got)
        counts[name] = len(got)
        jobs += got
    return jobs, counts


def _attributed(name: str, jobs: list[Job]) -> list[Job]:
    """Drop anything from an attribution-bearing source that arrived without its line.

    Losing the row is the cheap direction: an un-attributed listing is a terms breach, and a breach is
    what gets a stranger's API access terminated. A silent pass-through would put the obligation back
    where this module exists to take it from — a renderer that might remember.
    """
    line = ATTRIBUTION.get(name)
    if not line:
        return jobs
    kept = [j for j in jobs if line in j.jd_text]
    if len(kept) != len(jobs):
        log.warning("%s: dropped %d job(s) carrying no attribution line", name, len(jobs) - len(kept))
    return kept


def attribution_lines(counts: dict[str, int]) -> list[str]:
    """The attribution a run actually incurred, in registry order — what a report has to print.

    Keyed off the counts rather than off `ATTRIBUTION` so a report that got nothing from Remotive does
    not credit Remotive, which would read as data it does not have.
    """
    return [ATTRIBUTION[name] for name in ALL if name in ATTRIBUTION and counts.get(name)]


def fetch_baselines(names: tuple[str, ...] | None = None,
                    options: dict[str, dict] | None = None) -> tuple[list[RateBand], dict[str, int]]:
    """Every named baseline (default: both), and how many bands each returned.

    Same error strategy as `fetch_all` and for a sharper reason: the external half of the report is
    required to degrade to a **labelled gap**, never to a shorter report. A source that crashes, times
    out or hits a daily quota comes back as zero bands here, and the count is what lets the renderer
    say which one is missing rather than silently printing less.

    `options` is per-source keyword arguments — `{"bls": {"areas": ...}}` is how the report command
    passes a user's own metro through from `config/settings.yaml`. It goes through the registry rather
    than round the side of it so a bad argument is still one source returning zero bands with a log
    line, not a traceback out of a monthly command.
    """
    options = options or {}
    bands: list[RateBand] = []
    counts: dict[str, int] = {}
    for name in (names if names is not None else tuple(BASELINES)):
        fn = BASELINES.get(name)
        if fn is None:
            log.warning("no such baseline: %s (have: %s)", name, ", ".join(BASELINES))
            continue
        try:
            got = fn(**options.get(name, {}))
        except Exception as e:  # noqa: BLE001 — an unreachable baseline is a gap, not a crash
            log.warning("baseline %s crashed: %s", name, e)
            got = []
        counts[name] = len(got)
        bands += got
    return bands, counts
