"""Entry point for the triage tool — a TWO-PHASE run (see docs/operating/triage-operating.md).

  Phase 1  `python -m triage`         read Gmail -> extract -> skip seen/applied -> fetch easy JDs +
                                        analyze from the email body -> rank -> write the worklist, a
                                        `state` file, an `archive list`, and a `browser-queue` (the
                                        promising jobs whose full JD is walled/thin).
  Phase 3  `python -m triage --merge`  after a Claude session has pulled the queued JDs through the
                                        browser (Tier 2) into `browser-jds-<date>.json`, re-analyze
                                        those with the full JD and rewrite the worklist.

The script never touches the mailbox and never opens a browser — those (Tier 2 browser retrieval and
moving processed mail to jobs-triage) are done by the Claude session that drives the run. That is why
triage is run THROUGH Claude Code, not from a bare terminal.
"""
from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import applied, channels, config, dedup, liveness, precedent, prefilter, preflight, rank, store
from .analyze import analyze
from core.fetch import fetch_jd, needs_manual_review
from .channels import ingest, paste
from .channels.common import _dedup_key, archive_list_lines, hydrate
from core.models import job_from_dict, job_to_dict, needs_browser_fetch, normalize_link as _normalize_link
from .worklist import render

log = logging.getLogger("triage")


_LATEST = config.RUNS_DIR / "latest-run.txt"   # pointer so Phase 3 (--merge) finds Phase 1's run files


def _paths(run_id: str) -> dict:
    """All artifacts for ONE run, keyed by a unique run_id (date+time) so a later run never overwrites an
    earlier one. Phase 1 and its Phase 3 merge share the same run_id (via latest-run.txt)."""
    r = config.RUNS_DIR
    # The scored state file is the corpus — a month of Opus judgments, kept where clearing run junk can't
    # reach it. Everything else here is disposable plumbing for one run.
    return {"worklist": r / f"worklist-{run_id}.md", "state": config.CORPUS_DIR / f"state-{run_id}.json",
            "queue": r / f"browser-queue-{run_id}.json", "browser_jds": r / f"browser-jds-{run_id}.json",
            "archive": r / f"archive-{run_id}.txt", "fails": r / f"fetch-failures-{run_id}.log"}


def _fetch(job):
    # The `paste` channel already fetched its own JDs (it needs them to backfill company/title before
    # the job has an identity), so a job that arrives with a full JD is not fetched a second time.
    if job.jd_source != "full":
        fetch_jd(job)                   # scrape the easy sources, else fall back to the email's JD text
    return job


def _process(job):
    # Two cheap gates before the expensive call: free regex rules, then a small Sonnet screen. Both are
    # biased toward keeping — a prefilter kill still renders under "Rejected / skipped" with its reason.
    reason = prefilter.hard_skip(job)
    if not reason:
        keep, why = prefilter.cheap_screen(job)
        if not keep:
            reason = f"prefilter: {why}" if why else "prefilter: screened out as off-lane"
    if reason:
        job.analysis = prefilter.skip_analysis(reason)
        job.prefiltered = True
    else:
        job.analysis = analyze(job)     # Opus 4.8 structured judgment (from full JD or email body)
    job.final_tier = rank.finalize_tier(job)
    return job


def _reanalyze(job):
    job.analysis = analyze(job)         # now with the browser-fetched full JD
    job.final_tier = rank.finalize_tier(job)
    return job


def _args():
    ap = argparse.ArgumentParser(prog="triage",
                                 description="Read Gmail, scrape JDs, rank vs your goals -> worklist.md")
    ap.add_argument("--days", type=int, default=None, help="inbox/freshness window (default: config, 3)")
    ap.add_argument("--limit", type=int, default=None, help="cap jobs analyzed this run (for testing)")
    ap.add_argument("--sample", type=int, default=None,
                    help="process only N representative WHOLE emails (source-spread) — small end-to-end test")
    ap.add_argument("--paste", nargs="*", metavar="URL", default=None,
                    help="job URLs to ingest directly — the channel that needs no mail, key or OAuth")
    ap.add_argument("--paste-file", action="append", metavar="PATH", default=None,
                    help="file of job URLs, one per line ('#' comments allowed); repeatable")
    ap.add_argument("--channels", metavar="NAMES", default=None,
                    help="run ONLY these channels this run, comma-separated (e.g. 'agencies' or "
                         "'mail,agencies'). Overrides the enables in config/settings.yaml for this "
                         "run only and never writes them back; omit to use config")
    ap.add_argument("--out", default=None, help="output path (default: data/runs/worklist-<date>.md)")
    ap.add_argument("--no-archive", action="store_true", help="don't write the archive list this run")
    ap.add_argument("--no-browser", action="store_true", help="don't emit a Tier-2 browser-fetch queue")
    ap.add_argument("--merge", action="store_true",
                    help="Phase 3: re-rank using browser-fetched JDs in data/runs/browser-jds-<date>.json")
    ap.add_argument("--sync-applied", metavar="PATH", default=None,
                    help="rebuild data/corpus/applied.json from Claude-normalized applied-sheet rows (JSON at PATH)")
    return ap.parse_args()


def _intro(days: int, picked) -> str:
    """What this run is about to do, before it does any of it.

    A first `python -m triage` used to open with log lines from six scrapers — no statement of what
    was happening, how long it would take, or that it spends money. Four lines fix that, and the run
    summary still reports what actually happened. Every value is read from the same config the run
    itself uses, so this cannot describe a run other than the one about to happen.
    """
    live = [n for n in channels.ALL if (picked(n) if picked else config.channel_enabled(n))]
    return "\n".join([
        "",
        "Scoring new job postings against your rubric (profile/rubric.md).",
        f"  looking at   {' · '.join(live) if live else 'nothing — every channel is off'}"
        f"  ({days}-day window)",
        f"  scoring      a cheap {config.model('prefilter')} screen first, then "
        f"{config.model('analyze')} judges what survives",
        "  writing      a ranked worklist under data/runs/",
    ])


def _phase1(args, run_id: str) -> None:
    days = config.window_days(args.days)
    picked = channels.selection(args.channels.split(",") if args.channels else None)
    print(_intro(days, picked))

    # Before any fetch or paid call: say what is missing and how to fix it. Warn and continue — never
    # block, because a seeded example with an unwritten rubric is exactly the tier-0 demo, and it must
    # still run. The findings are rendered again in the summary and (if CRITICAL) on the worklist.
    findings = preflight.check()
    block = preflight.format_block(findings)
    if block:
        print(block)

    seen, skiplist = store.load_seen(), store.load_skiplist()
    blocked = seen | skiplist | applied.load_blocked()   # applied.json = synced from Ben's Google Sheet

    # `paste` takes its URLs from argv, which the channel contract `fetch(days, sample)` has no room
    # for — so they are installed on the channel before the fan-out. Nothing is fetched by paste when
    # the list is empty, and the summary line then reads `paste 0`.
    pasted = paste.set_urls(paste.collect_urls(args.paste or [], args.paste_file or []))
    if pasted:
        log.info("paste: %d URL(s) from the command line / links file(s)", len(pasted))

    # `--channels` is a per-run override of the config enables; `None` means "nobody asked", and the
    # config flag decides. See `channels.selection` for why this never writes back to settings.
    # `picked` is resolved at the top of the run, so `_intro` names the channels that actually run.
    candidates, all_extracted = ingest(days, sample=args.sample, enabled=picked)
    # A candidate is blocked by its composite id OR by its normalized apply-URL (the applied cache carries
    # both keys, so a job Ben applied to is caught even if company/title normalized slightly differently).
    fresh = [j for j in candidates
             if j.id not in blocked and f"url:{_normalize_link(j.link)}" not in blocked]
    skipped_pre = len(candidates) - len(fresh)
    log.info("skip-before-eval: %d already seen/applied/rejected", skipped_pre)
    if args.limit:
        fresh = fresh[:args.limit]
    if not fresh:
        log.info("no new jobs to analyze")

    # Recovered links — the postings the mail extractor listed but never described — arrive bare, so
    # they get a JD and a company/title here. Deliberately AFTER the block above: `store.py` promises
    # all three caches are checked before any fetch, and hydrating earlier would re-fetch every
    # recovered link on every run. `save_seen` below records the `url:` key that makes that gate able
    # to recognise a bare job at all.
    fresh = hydrate(fresh)

    # Fetch first, then collapse, THEN score. The split exists so semantic dedup can read the real JD
    # text (which is where the evidence for a merge lives) while still landing before the first paid
    # call — a duplicate that reaches `_process` has already cost a Sonnet screen and an Opus judgment.
    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        fetched = list(ex.map(_fetch, fresh))
    unique = dedup.collapse(fetched)
    n_collapsed = len(fetched) - len(unique)

    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        jobs = list(ex.map(_process, unique))

    # A collapsed posting is still SEEN — otherwise it is fresh again tomorrow and gets collapsed again.
    seen.update(j.id for j in jobs)
    seen.update(d["id"] for j in jobs for d in j.duplicates)
    # The apply URL is recorded BESIDE the composite id, in the `url:` form the applied cache already
    # uses and the skip check above already tests. Without it a job the mail extractor left out is
    # unrecognisable tomorrow: it arrives bare, so its identity is its link, while it was stored under
    # the company|title it only acquired during hydration — and it would be re-fetched every run.
    seen.update(f"url:{_normalize_link(j.link)}" for j in jobs if j.link)
    store.save_seen(seen)
    jobs.sort(key=rank.sort_key)
    # Availability check AFTER ranking, so we only spend requests on jobs Ben might act on. A req that
    # was scrapeable an hour ago can already be closed — see liveness.py for why this exists.
    live = liveness.annotate(jobs)

    p = _paths(run_id)
    _LATEST.write_text(run_id)          # so `--merge` (Phase 3) targets THIS run's files, not a guess
    out = Path(args.out) if args.out else p["worklist"]
    out.write_text(render(jobs, days=days, skipped_pre=skipped_pre,
                          banner=preflight.worklist_banner(findings)))
    p["state"].write_text(json.dumps(
        {"days": days, "skipped_pre": skipped_pre, "jobs": [job_to_dict(j) for j in jobs]}))

    # Fold this run's judgments into the retrieval index, AFTER the state file exists — today's
    # decisions are tomorrow's precedent, and doing it here means a job is never its own precedent.
    # Incremental, so this embeds today's documents only. Never fatal: an index that failed to build
    # costs the next run its memory, not this run its worklist.
    indexed = 0
    try:
        indexed = precedent.refresh()
    except Exception as e:  # noqa: BLE001 — the worklist is the product; the index is a cache
        log.warning("could not refresh the retrieval index: %s", e)

    # Tier-2 queue: promising jobs whose full JD we couldn't scrape — Claude pulls these via the browser.
    queue = [{"id": j.id, "link": j.link, "company": j.company, "title": j.title,
              "source_platform": j.source_platform, "jd_source": j.jd_source,
              "why": j.analysis.why if j.analysis else ""} for j in jobs if needs_browser_fetch(j)]
    if queue and not args.no_browser:
        p["queue"].write_text(json.dumps(queue, indent=2))

    fails = [j for j in jobs if needs_manual_review(j)]
    if fails:
        p["fails"].write_text(
            "\n".join(f"{j.fetch_error}\t{j.link}\t{j.title} @ {j.company}" for j in fails) + "\n")

    # Archive list (same set before/after browser fetch — resolution doesn't change, only JD quality).
    # An email archives when EVERY job in it (pre-dedup) is resolved. We resolve by dedup KEY so a job
    # that was a duplicate of an analyzed/seen job also counts — no duplicate-alert email is left behind.
    n_archive = 0
    if not args.no_archive:
        # A posting collapsed into another one IS resolved — its email must still archive.
        resolved_ids = {j.id for j in jobs} | {d["id"] for j in jobs for d in j.duplicates} | blocked
        resolved_keys = {_dedup_key(c) for c in candidates if c.id in resolved_ids}
        lines, n_archive = archive_list_lines(
            all_extracted, resolved_keys, config.archive_mailbox() or "jobs-triage", run_id[:10])
        if lines:
            p["archive"].write_text("\n".join(lines) + "\n")

    n_pre = sum(1 for j in jobs if j.prefiltered)
    print(f"\n✓ PHASE 1 done ({run_id}) — wrote {out}")
    print(f"  {len(jobs)} analyzed · {skipped_pre} skipped pre-eval · {len(fails)} couldn't-fetch")
    # Which channel actually supplied jobs. 'off' is a channel you disabled; a bare 0 is one that ran
    # and found nothing; CRASHED is jobs you should have had and didn't.
    print(f"  ⤷ channels: {channels.counts_line(channels.LAST_RUN)}")
    pf = preflight.summary_line(findings)
    if pf:
        print(f"  ⤷ {pf}")
    if n_collapsed:
        print(f"  ⤷ semantic dedup: {n_collapsed} duplicate posting(s) collapsed before scoring "
              f"— see '⧉ Collapsed duplicates' in the worklist for what merged into what")
    if n_pre:
        print(f"  ⤷ prefilter: {n_pre} screened out cheaply, {len(jobs) - n_pre} sent to "
              f"{config.model('analyze')} ({n_pre * 100 // max(1, len(jobs))}% of Opus calls saved)")
    if indexed:
        print(f"  ⤷ precedent index: {indexed} past decisions retrievable next run → "
              f"{config.CORPUS_DIR / 'index.json'}")
    if live:
        print(f"  ⤷ liveness: {live['open']} open · {live['closed']} CLOSED · {live['unknown']} unknown "
              f"(of {live['checked']} ranked) — 'unknown' includes aggregators that never expire listings")
    if queue and not args.no_browser:
        print(f"  ⤷ browser queue: {len(queue)} promising JDs to pull via Chrome → {p['queue']}")
        print(f"    (Claude: fetch each, write {p['browser_jds']}, then run `-m triage --merge`)")
    if n_archive:
        print(f"  ⤷ archive list: {n_archive} emails → {p['archive']}")


def _phase3_merge(args, run_id: str) -> None:
    p = _paths(run_id)
    if not p["state"].exists():
        log.error("no state file for run %s — run Phase 1 first", run_id); return
    state = json.loads(p["state"].read_text())
    jobs = [job_from_dict(d) for d in state["jobs"]]
    jds = json.loads(p["browser_jds"].read_text()) if p["browser_jds"].exists() else {}

    by_id = {j.id: j for j in jobs}
    to_reanalyze = []
    for jid, jd_text in jds.items():
        j = by_id.get(jid)
        if j and jd_text and len(jd_text.strip()) >= 120:
            j.fetched_jd = jd_text.strip()
            j.jd_source = "full"
            to_reanalyze.append(j)

    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        list(ex.map(_reanalyze, to_reanalyze))

    jobs.sort(key=rank.sort_key)
    out = Path(args.out) if args.out else p["worklist"]
    out.write_text(render(jobs, days=state.get("days", 3), skipped_pre=state.get("skipped_pre", 0)))
    print(f"\n✓ PHASE 3 done — merged {len(to_reanalyze)} browser-fetched JD(s); rewrote {out}")


def _sync_applied(path: str) -> None:
    """Persist Claude's normalized applied-sheet rows into data/corpus/applied.json (the dedup cache). Input is a
    JSON list of rows (or {"rows": [...]}) — see docs/operating/triage-applied-sync.md for the row schema."""
    rows = json.loads(Path(path).read_text())
    if isinstance(rows, dict):
        rows = rows.get("rows", [])
    s = applied.sync_from_rows(rows)
    print(f"\n✓ SYNC-APPLIED done — {s['records']} record(s), {s['block_keys']} block key(s) "
          f"({len(s['auto_blocked'])} auto-blocked · {len(s['held_for_review'])} held for review)")
    for h in s["held_for_review"]:
        print(f"  ⚠ review row {h['row']}: {h['company'] or '?'} — {h['title'] or '?'}  ({h['note']})")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _args()
    if args.sync_applied:
        _sync_applied(args.sync_applied)
    elif args.merge:
        if not _LATEST.exists():
            log.error("no latest-run.txt — run Phase 1 first"); return
        _phase3_merge(args, _LATEST.read_text().strip())
    else:
        # unique per run (date + time) so a new run never overwrites a previous run's worklist/state
        try:
            _phase1(args, datetime.now().strftime("%Y-%m-%d-%H%M%S"))
        except channels.UnknownChannel as e:
            # A typo'd `--channels` is a user error, not a bug: say which name and stop. A traceback
            # here would bury the one line that fixes it.
            log.error("%s", e)


if __name__ == "__main__":
    main()
