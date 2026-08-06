"""Entry point for the triage tool — a TWO-PHASE run (see docs/operating/triage.md).

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
from .channels.common import ArchivePlan, _dedup_key, archive_list_lines, hydrate
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
            "archive": r / f"archive-{run_id}.txt", "fails": r / f"fetch-failures-{run_id}.log",
            "archive_plan": r / f"archive-plan-{run_id}.json"}


def _seen_keys(jobs) -> set[str]:
    """Every key `seen.json` records for a batch of scored jobs — the one definition of "judged".

    Three forms per job, and they are not interchangeable:
      * the composite id (`company|title|city`), which is `Job.id`;
      * each collapsed duplicate's id — a posting merged into this one IS judged, and without its key
        it is fresh again tomorrow and gets collapsed again;
      * `url:<normalized link>`, recorded BESIDE the composite in the form the applied cache already
        uses and the skip check already tests. Without it a job the mail extractor left out is
        unrecognisable tomorrow: it arrives bare, so its identity is its link, while it was stored
        under the company|title it only acquired during hydration — and it is re-fetched every run.

    An ERRORED job contributes nothing. `seen` means judged, and a seen job never surfaces again, so
    recording one that no judgment was ever made for does not block it — it loses it. Prefiltered jobs
    are judged (the cheap gate is a real verdict) and are included. See `Job.analysis_errored`.
    """
    keys: set[str] = set()
    for j in jobs:
        if j.analysis_errored:
            continue
        keys.add(j.id)
        keys.update(d["id"] for d in j.duplicates)
        if j.link:
            keys.add(f"url:{_normalize_link(j.link)}")
    return keys


def _mark_seen(jobs) -> int:
    """Fold `jobs` into seen.json read-modify-write, and return how many keys were new.

    Re-reading rather than holding the set in memory is what makes this safe to call repeatedly during
    a run (see the checkpoint in `_phase1`) and safe to call from `--merge`, which never loaded `seen`.
    """
    seen = store.load_seen()
    keys = _seen_keys(jobs)
    new = keys - seen
    if new:
        store.save_seen(seen | keys)
    return len(new)


# How many scored jobs may be lost to a crash. A flush is two small file writes against an Opus call
# per job, so this is nowhere near a cost trade-off — it is only here so a 358-job run does not do 358
# rewrites of a growing JSON file. On the 2026-07-20 run's timings, 25 jobs is roughly a 90-second
# exposure window.
_CHECKPOINT_EVERY = 25


def _score_all(unique, state_path: Path, days: int, skipped_pre: int):
    """Score every job, flushing the state file and `seen.json` every `_CHECKPOINT_EVERY` results.

    Both used to be written **once**, after all scoring finished, so a crash at job 300 of 358 did not
    merely block those 300 — it *lost* them, judgments and paid-for JD text alike. `ex.map` is consumed
    as it yields rather than collected by `list()`, so whatever completed before the crash is already
    on disk; the partial state file is a valid corpus record (`core/index.py` reads it) and a valid
    input to `--merge`, which is how the run is picked up again.

    Ordering matters inside a flush: state first, then `seen`. State is the judgment; `seen` is the
    promise never to ask again. Reversed, a crash between the two writes would mark a job judged whose
    judgment was never stored — the exact loss this function exists to prevent.
    """
    done = []
    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        for job in ex.map(_process, unique):
            done.append(job)
            if len(done) % _CHECKPOINT_EVERY == 0:
                _write_state(state_path, done, days, skipped_pre)
                _mark_seen(done)
                log.info("checkpoint: %d/%d scored and persisted", len(done), len(unique))
    return done


def _write_state(path: Path, jobs, days: int, skipped_pre: int) -> None:
    """The corpus write, done by BOTH phases — the state file is the only durable copy of a judgment.

    Phase 3 used to re-score on the browser-fetched JD and write only the worklist, so the corpus kept
    the very judgment the browser step was run to replace (verified 2026-07-29: a worklist holding
    `SKIP 8` on a real .NET JD beside a state file still holding `title_only` and `LOW_FIT 52`). That
    also silently starved `core/index.py`, which builds the precedent index from this file — the
    expensive fetched JD text and the better score were thrown away every merge.
    """
    path.write_text(json.dumps(
        {"days": days, "skipped_pre": skipped_pre, "jobs": [job_to_dict(j) for j in jobs]}))


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

    p = _paths(run_id)
    # Written BEFORE scoring, not after: it is how `--merge` finds this run's files, and a run that
    # crashes mid-scoring is precisely the run someone needs to pick up. Pointing it at a state file
    # that does not exist yet costs one clear "run Phase 1 first"; pointing it at yesterday is silent.
    _LATEST.write_text(run_id)
    jobs = _score_all(unique, p["state"], days, skipped_pre)

    scored = [j for j in jobs if not j.analysis_errored]
    seen.update(_seen_keys(jobs))       # `_seen_keys` drops the errored ones — read it for why
    store.save_seen(seen)
    jobs.sort(key=rank.sort_key)
    # Availability check AFTER ranking, so we only spend requests on jobs Ben might act on. A req that
    # was scrapeable an hour ago can already be closed — see liveness.py for why this exists.
    live = liveness.annotate(jobs)

    # Archive list (same set before/after browser fetch — resolution doesn't change, only JD quality).
    # An email archives when EVERY job in it (pre-dedup) is resolved. We resolve by dedup KEY so a job
    # that was a duplicate of an analyzed/seen job also counts — no duplicate-alert email is left behind.
    #
    # Computed BEFORE the worklist is rendered, because the worklist reports it. What was moved out of a
    # mailbox, and what was held back from being moved, are facts a reader needs in the one document they
    # read — the `jobs-triage` label itself is somewhere Ben does not look.
    plan = None
    if not args.no_archive:
        # A posting collapsed into another one IS resolved — its email must still archive. An ERRORED
        # one is not resolved and its email stays in the inbox: for a recruiter email with no link the
        # message *is* the JD, and the job is deliberately un-seen so tomorrow retries it — which only
        # works if tomorrow's ingest can still find the mail.
        resolved_ids = ({j.id for j in scored} | {d["id"] for j in scored for d in j.duplicates}
                        | blocked)
        resolved_keys = {_dedup_key(c) for c in candidates if c.id in resolved_ids}
        plan = archive_list_lines(
            all_extracted, resolved_keys, config.archive_mailbox() or "jobs-triage", run_id[:10])
        if plan.lines:
            p["archive"].write_text("\n".join(plan.lines) + "\n")
        # `rows`/`held` are what the worklist renders, but only `lines` was ever persisted — so
        # `--merge` re-rendering the worklist (below in `_phase3_merge`) silently dropped the
        # HELD BACK section every time, because it had nothing to reload. Round-trip both here.
        if plan.rows or plan.held:
            p["archive_plan"].write_text(json.dumps({"rows": plan.rows, "held": plan.held}))

    out = Path(args.out) if args.out else p["worklist"]
    out.write_text(render(jobs, days=days, skipped_pre=skipped_pre,
                          banner=preflight.worklist_banner(findings), archive=plan))
    _write_state(p["state"], jobs, days, skipped_pre)

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
    n_err = len(jobs) - len(scored)
    if n_err:
        # Loud, and phrased as unfinished work rather than as a result: the run "succeeded" while
        # producing no judgment for these, which is precisely how 134 jobs went missing on 2026-07-29.
        print(f"  ⚠ {n_err} job(s) NOT SCORED — the analyzer failed on them. Left OUT of seen.json and "
              f"their emails left in the inbox, so they retry; `python -m triage --merge` scores them now.")
    if indexed:
        print(f"  ⤷ precedent index: {indexed} past decisions retrievable next run → "
              f"{config.CORPUS_DIR / 'index.json'}")
    if live:
        print(f"  ⤷ liveness: {live['open']} open · {live['closed']} CLOSED · {live['unknown']} unknown "
              f"(of {live['checked']} ranked) — 'unknown' includes aggregators that never expire listings")
    if queue and not args.no_browser:
        print(f"  ⤷ browser queue: {len(queue)} promising JDs to pull via Chrome → {p['queue']}")
        print(f"    (Claude: fetch each, write {p['browser_jds']}, then run `-m triage --merge`)")
    if plan and plan.count:
        print(f"  ⤷ archive list: {plan.count} emails → {p['archive']}")
    if plan and plan.held:
        # Loud, and never only in a log: this is mail that was NOT touched and needs eyes.
        print(f"  ⚠ {len(plan.held)} email(s) HELD BACK from archiving — the sender names a person. "
              f"See '📥 Mail' in the worklist; they are still in the inbox.")


def _phase3_merge(args, run_id: str) -> None:
    p = _paths(run_id)
    if not p["state"].exists():
        log.error("no state file for run %s — run Phase 1 first", run_id); return
    state = json.loads(p["state"].read_text())
    jobs = [job_from_dict(d) for d in state["jobs"]]
    jds = json.loads(p["browser_jds"].read_text()) if p["browser_jds"].exists() else {}

    by_id = {j.id: j for j in jobs}
    merged = []
    for jid, jd_text in jds.items():
        j = by_id.get(jid)
        if j and jd_text and len(jd_text.strip()) >= 120:
            j.fetched_jd = jd_text.strip()
            j.jd_source = "full"
            merged.append(j)

    # THIS is the resume path, and it is a predicate on an existing phase rather than a new flag.
    # A job whose analysis raised has everything it needs to be scored — the fetched JD text is the
    # expensive part and the state file already holds it — so "pick up where the run left off" is
    # exactly "re-analyze the errored ones", which is what this phase already does for browser JDs.
    # A resumed job that fails again simply stays errored and is retried again; a resumed job that
    # succeeds has `analysis_errored` cleared by `analyze` itself.
    merged_ids = {id(j) for j in merged}
    resumed = [j for j in jobs if j.analysis_errored and id(j) not in merged_ids]
    to_reanalyze = merged + resumed

    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        list(ex.map(_reanalyze, to_reanalyze))

    # Scoring a job here is what finally makes it `seen` — phase 1 deliberately left the errored ones
    # out, and without this a job is re-fetched and re-scored on every future run even after the
    # judgment was paid for here. `_seen_keys` still drops anything that failed again. Written before
    # the worklist so a crash in rendering cannot lose the fact that money was spent.
    if to_reanalyze:
        _mark_seen(to_reanalyze)

    jobs.sort(key=rank.sort_key)
    out = Path(args.out) if args.out else p["worklist"]
    days, skipped_pre = state.get("days", 3), state.get("skipped_pre", 0)
    plan = None
    if p["archive_plan"].exists():
        saved = json.loads(p["archive_plan"].read_text())
        plan = ArchivePlan(rows=saved.get("rows", []), held=saved.get("held", []))
    out.write_text(render(jobs, days=days, skipped_pre=skipped_pre, archive=plan))
    # The corpus, not just the worklist — see `_write_state`. Written even when nothing was re-analyzed:
    # a merge that found no JDs still round-trips the file, which is cheap and keeps the two phases'
    # on-disk contract identical.
    _write_state(p["state"], jobs, days, skipped_pre)

    # Same fold-into-the-index step Phase 1 does, for the same reason and with the same fail-soft: the
    # re-scored judgment is the one tomorrow should retrieve. `JobIndex.add` keys on company|title and
    # re-embeds a document whose text changed, so this replaces the stale entry rather than duplicating it.
    try:
        precedent.refresh()
    except Exception as e:  # noqa: BLE001 — the worklist is the product; the index is a cache
        log.warning("could not refresh the retrieval index: %s", e)

    still_errored = [j for j in jobs if j.analysis_errored]
    print(f"\n✓ PHASE 3 done — merged {len(merged)} browser-fetched JD(s); rewrote {out}")
    print(f"  ⤷ corpus updated: {len(jobs)} judgments → {p['state']}")
    if resumed:
        print(f"  ⤷ resumed: {len(resumed) - len(still_errored)} of {len(resumed)} previously-unscored "
              f"job(s) now have a judgment")
    if still_errored:
        print(f"  ⚠ {len(still_errored)} still NOT SCORED — left out of seen.json, so run `--merge` "
              f"again once the cause is fixed (a spend cap, a missing key, a provider outage)")


def _sync_applied(path: str) -> None:
    """Persist Claude's normalized applied-sheet rows into data/corpus/applied.json (the dedup cache). Input is a
    JSON list of rows (or {"rows": [...]}) — see docs/operating/triage.md for the row schema."""
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
