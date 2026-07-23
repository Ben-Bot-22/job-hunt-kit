"""Job-input registry. Add a channel = write a `fetch(days, sample) -> list[Job]`, import it, register
it in `ALL`, and give it an `enabled` flag in config.

A channel is a function that returns a list of jobs. That is the entire abstraction — there is no
plugin framework here, and the shape is shared with `research/sources/__init__.py` — *where my jobs
come from* against *where market data comes from* — which has run this way for months: a name→fetch map, a per-channel enable flag, and a per-channel `try/except` so one
rotted scraper costs you that channel and not the morning's triage.

`ingest()` keeps the exact signature and return type it had when mail was the only way in —
`(candidates, all_extracted)`, both `list[Job]` — so `__main__._phase1` and everything downstream of
it are untouched by the existence of channels. Each channel returns its jobs PRE-dedup; the collapse
is done here, across all of them at once, because a posting arriving from both `boards` and `mail` is
only visible as a duplicate from above.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import NamedTuple

from .. import config
from . import agencies, boards, gmail_api, mail, paste
from .common import _dedup_key
from core.models import Job

log = logging.getLogger("triage.channels")

Fetch = Callable[[int, "int | None"], list[Job]]

# Four built channels and one honest stub. `gmail` is registered so the seam is visible and ships
# `enabled: false` so it never runs — it raises rather than returning nothing, which is the point of
# it. It sits last because registry order decides duplicate survivors and a channel that cannot
# produce a job has no business competing for one.
# `paste` is otherwise last on purpose: registry order decides which channel's copy of a duplicate posting
# survives the collapse, and a mail-sourced copy carries an `email_mid`, so keeping it means the
# email it came from can still archive. `boards` sits between them for the same reason read the other
# way — a posting arriving from both mail and a watched board keeps the mail copy, because only that
# one can archive; a posting arriving from both a board and a paste keeps the board copy, which is the
# one with employer-stated company, title and pay rather than model-backfilled guesses.
# `agencies` sits below `boards` by the same rule: several agencies resell the same client req, so a
# posting on both a company's own board and a staffing firm's should survive as the employer's copy —
# that one names the client, and the agency's says "a leading financial services company".
ALL: dict[str, Fetch] = {
    "mail": mail.fetch,
    "boards": boards.fetch,
    "agencies": agencies.fetch,
    "paste": paste.fetch,
    "gmail": gmail_api.fetch,
}

# What a channel wants to say about ITSELF on the health line, beyond its job count — rendered in
# parentheses after the count. A table rather than an attribute on the fetch function, so the seam is
# visible in the file you already open to see what the channels are; a channel absent from here
# renders exactly as it always did.
#
# `agencies` is the one channel that needs it, and it needs it badly: its six scrapers fail by
# returning zero rather than by raising, so the per-source counts are the only rot detector that
# exists. `agencies 45` alone cannot tell you that TEKsystems has been dead for a week.
DETAIL: dict[str, Callable[[], str]] = {
    "agencies": agencies.counts_detail,
}


class ChannelResult(NamedTuple):
    """One channel's contribution to a run, including the ways it can contribute nothing.

    `status` separates the three outcomes the health line has to tell apart: `disabled` (you turned
    it off), `ok` with zero jobs (it ran and the window was empty), and `crashed` (it blew up and you
    are missing jobs you would otherwise have had). Collapsing the last two into "0" is exactly how a
    rotted channel hides for a week.
    """
    name: str
    jobs: list[Job]
    status: str          # "ok" | "disabled" | "crashed"
    error: str = ""
    detail: str = ""     # the channel's own breakdown, if it registered one in `DETAIL`


def fetch_all(days: int, sample: int | None = None, *,
              channels: Mapping[str, Fetch] = ALL,
              enabled: Callable[[str], bool] | None = None,
              detail: Mapping[str, Callable[[], str]] = DETAIL) -> list[ChannelResult]:
    """Run every enabled channel, in registry order, isolating each one's failures.

    `enabled` defaults to the config flag and is injectable so a test can turn a fake channel off
    without writing config. Registry order is the order jobs arrive in, which — since dedup keeps the
    FIRST job it sees for a key — decides which channel's copy of a duplicate posting survives.
    """
    is_enabled = enabled or config.channel_enabled
    results: list[ChannelResult] = []
    for name, fn in channels.items():
        if not is_enabled(name):
            results.append(ChannelResult(name, [], "disabled"))
            continue
        try:
            got = list(fn(days, sample))
        except Exception as e:  # noqa: BLE001 — one bad channel shouldn't kill the run
            log.warning("channel %s crashed: %s: %s", name, type(e).__name__, e)
            results.append(ChannelResult(name, [], "crashed", f"{type(e).__name__}: {e}"))
            continue
        results.append(ChannelResult(name, got, "ok", detail=_detail_of(name, detail)))
    return results


class UnknownChannel(ValueError):
    """A channel was named on the command line that isn't in the registry. Names the typo and the set."""


def selection(names: "list[str] | None",
              channels: Mapping[str, Fetch] = ALL) -> "Callable[[str], bool] | None":
    """Build the per-run `enabled` predicate from an explicit list of channel names, or None.

    `None` in, `None` out — meaning "nobody asked for a selection", and `fetch_all` falls through to
    the config flag, which stays the default and the only *persistent* answer. This is deliberately an
    OVERRIDE and not a second config: naming channels on the command line answers "what do I want THIS
    run", while `config/settings.yaml` answers "what does a normal morning do". Collapsing the two
    would mean an experiment silently becomes the default, which is the failure mode of every tool
    that lets a flag write config.

    Selection is *exhaustive*, not additive: `--channels agencies` runs agencies and nothing else,
    including channels enabled in config. Additive would need a second flag to subtract, and the
    common cases here are "just agencies" and "mail and agencies" — both of which are the full set the
    user wants, stated positively. A run whose channels came from the flag still prints the same
    health line, so what actually ran is never inferred from what was typed.

    An unknown name is a hard failure naming the offender, matching how `config/settings.yaml`
    validates: a misspelled `--channels agences` must not silently mean "no channels", which would
    look exactly like a quiet morning.
    """
    if names is None:
        return None
    wanted = {n.strip().lower() for n in names if n.strip()}
    if not wanted:
        raise UnknownChannel("--channels was given no names; omit it to use config/settings.yaml")
    unknown = sorted(wanted - set(channels))
    if unknown:
        raise UnknownChannel(
            f"unknown channel(s): {', '.join(unknown)} — registered channels are "
            f"{', '.join(channels)}")
    return lambda name: name in wanted


def _detail_of(name: str, detail: Mapping[str, Callable[[], str]]) -> str:
    """A channel's own breakdown, or ''. A breakdown that raises must not cost the channel its jobs —
    it is a log line, and losing a run's postings to a formatting bug would be an absurd trade."""
    fn = detail.get(name)
    if fn is None:
        return ""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        log.warning("channel %s detail failed: %s: %s", name, type(e).__name__, e)
        return ""


def counts_line(results: list[ChannelResult]) -> str:
    """The run-summary health line.

        mail 42 · boards 0 · agencies 45 (insightglobal 30, teksystems 15, motion 0 ⚠) · paste off

    A channel that registered a breakdown in `DETAIL` gets it in parentheses after its count — for
    `agencies` that parenthetical is the only way a rotted scraper is visible at all.
    """
    parts = []
    for r in results:
        if r.status == "disabled":
            parts.append(f"{r.name} off")
        elif r.status == "crashed":
            parts.append(f"{r.name} CRASHED ({r.error[:60]})")
        else:
            parts.append(f"{r.name} {len(r.jobs)}" + (f" ({r.detail})" if r.detail else ""))
    return " · ".join(parts) or "(no channels registered)"


# The last run's per-channel results, for the summary `__main__` prints. A side channel rather than a
# return value because `ingest()`'s signature is fixed by the pipeline it feeds — see the module
# docstring. Single-process, written once per run, read immediately after.
LAST_RUN: list[ChannelResult] = []


def ingest(days: int, sample: int | None = None, *,
           channels: Mapping[str, Fetch] = ALL,
           enabled: Callable[[str], bool] | None = None) -> tuple[list[Job], list[Job]]:
    """Fan out across the channels and return (candidates, all_extracted).

    `candidates` is deduped and fed to analysis; `all_extracted` is every job every channel returned,
    pre-dedup, and is fed to the archive check — so an email whose jobs are all duplicates of
    already-processed jobs still archives. `sample=N` is passed through to each channel (for `mail`
    it selects N representative WHOLE emails — a small end-to-end test where every sampled email is
    fully processed, and therefore archivable).
    """
    global LAST_RUN
    results = fetch_all(days, sample, channels=channels, enabled=enabled)
    LAST_RUN = results
    all_extracted: list[Job] = [job for r in results for job in r.jobs]
    candidates: list[Job] = []
    seen: set[str] = set()
    for job in all_extracted:
        key = _dedup_key(job)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(job)
    log.info("channels: %s — extracted %d jobs (%d unique candidates)",
             counts_line(results), len(all_extracted), len(candidates))
    return candidates, all_extracted
