"""The `paste` channel — job URLs handed to the tool directly, on the command line or in a file.

This is the channel that needs nothing: any operating system, no key, no OAuth, no mail client, no
config. It is on by default and it is the only channel a stranger is guaranteed to be able to use, so
everything here fails soft — a URL that can't be fetched, or a company name the model won't guess,
still produces a job that goes through the pipeline and gets scored on whatever text there is.

    python -m triage --paste https://boards.greenhouse.io/acme/jobs/1
    python -m triage --paste-file links.txt

`days` is ignored: a pasted URL is an explicit request, not a window over an inbox. `sample=N` caps
the list, so `--sample` still means "a small end-to-end test" here.

**Why this channel fetches the JD itself, unlike `mail`.** A pasted URL arrives with no company and
no title, so `Job.id` falls back to the canonical link (see `core/models.py`, stage 4 · 01). Backfill
that company and title and the id changes — it becomes the composite. If the backfill happened later,
in the pipeline's fetch pool, the job would be checked against `seen`/`applied` under one identity and
stored under another, and a pasted job would be re-scored every run while never matching the applied
cache it should match. Fetching here means the job enters `ingest()` already carrying the identity it
will keep, and `__main__._fetch` skips a job that already has a full JD so the URL is fetched once.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config
from core.fetch import fetch_jd
from core.models import Job, normalize_link

log = logging.getLogger("triage.channels.paste")

_MAX_URLS = 200          # safety cap on one run, in the spirit of mail's _MAX_EMAILS


# --- Where the URLs come from ---------------------------------------------------------------------
# A module-level list rather than a `fetch()` argument, because `fetch(days, sample)` is the channel
# contract the registry calls and widening it for one channel would make the registry know about
# paste. `__main__` fills this from argv before calling `ingest()`. Same trade as `channels.LAST_RUN`.
_URLS: list[str] = []


def set_urls(urls: Iterable[str]) -> list[str]:
    """Install the URLs this run will ingest, replacing anything set before. Returns what was kept."""
    global _URLS
    _URLS = list(urls)
    return _URLS


def read_links_file(path: str | Path) -> list[str]:
    """One URL per line. Blank lines and `#` comments are skipped, so a links file can be annotated.

    A missing or unreadable file logs an error and yields nothing rather than raising: paste is the
    channel a first-time user reaches for, and a typo'd path costing them the whole run — including
    the other channels — is a worse failure than a run that reports `paste 0`.
    """
    try:
        text = Path(path).read_text()
    except OSError as e:
        log.error("could not read links file %s: %s", path, e)
        return []
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def collect_urls(urls: Iterable[str] = (), files: Iterable[str | Path] = ()) -> list[str]:
    """Everything given on argv plus everything in the named files, in order, deduped.

    Non-URLs are dropped with a warning naming the line. Silently ignoring them is how a pasted page
    title, or a links file that turned out to be a CSV, becomes a run that quietly found nothing.
    """
    raw = list(urls) + [u for f in files for u in read_links_file(f)]
    out, seen = [], set()
    for u in raw:
        u = u.strip().strip('<>"\'')
        if not u:
            continue
        if not u.lower().startswith(("http://", "https://")):
            log.warning("ignoring %r — not an http(s) URL", u[:80])
            continue
        key = normalize_link(u)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out[:_MAX_URLS]


# --- Backfilling company and title ----------------------------------------------------------------
# The implementation moved to `common.py` when the mail channel started producing bare jobs of its own
# (the links its extractor left out) and needed the identical treatment. Re-exported under the private
# names this module has always used, so the tests' injection points and `_backfill_model` monkeypatch
# keep working and there is exactly one backfill prompt in the repo.
from .common import _backfill_model, backfill as _shared_backfill  # noqa: E402


def _backfill(job: Job) -> Job:
    """A pasted URL carries no metadata at all — see `common.backfill`."""
    return _shared_backfill(job, default_platform="paste")


def _one(url: str, *, fetch=fetch_jd, backfill=_backfill) -> Job:
    job = Job(link=normalize_link(url.strip()), source_platform="")
    fetch(job)
    return backfill(job)


def fetch(days: int, sample: int | None = None, *,
          urls: Iterable[str] | None = None, fetch_jd=fetch_jd, backfill=_backfill) -> list[Job]:
    """The channel contract: a job per pasted URL, JD fetched and company/title backfilled.

    `urls`, `fetch_jd` and `backfill` are keyword-only injection points for the tests — the registry
    calls this with two positional arguments and gets the real thing.
    """
    todo = list(urls) if urls is not None else list(_URLS)
    if sample:
        todo = todo[:sample]
    if not todo:
        return []
    log.info("paste: %d URL(s) to fetch and backfill", len(todo))
    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        jobs = list(ex.map(lambda u: _one(u, fetch=fetch_jd, backfill=backfill), todo))
    return [j for j in jobs if j.link]
