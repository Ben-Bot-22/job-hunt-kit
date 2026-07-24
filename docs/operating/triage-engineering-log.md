# Triage — Engineering Log (features shipped + lessons learned)

Durable record of *why the triage tool is the way it is*. `triage-operating.md` is the **how it works
now**; this file is the **what we learned and what it cost to learn it**, so the same mistakes stop
recurring. Append a dated section per working session. Open bugs live at the bottom.

---

## 2026-07-24 — the rot run: four scrapers, four different silent truncations

The run that showed the per-source health line is only a detector if somebody reads it *and disbelieves
it*. Triage itself was routine — 64 analyzed, 173 skipped pre-eval, 11 emails archived, 4 résumés built,
first run under the onsite/relocation rubric. The finding was underneath it.

### What shipped

| Fix | What it does |
|---|---|
| `core/scrapers/motion.py` | Lifted our own 6-page (120-href) ceiling on a 797-posting board; swapped the two sub-listings for the combined `/tech-jobs`; stop on "no new hrefs". **19 → 275** |
| `core/scrapers/apex.py` | Off the cookie-gated GET pagination. **3 → 150** |
| `core/scrapers/teksystems.py` | **Check HTTP status** before treating a sub-sitemap as empty, and de-duplicate discovery. **80 unique, correct** (was 84 records over 80 distinct links) |
| `core/scrapers/kore1.py` | List regex anchored on posting rows, not category headings. **2 → 6** (board is 64) |
| `core/scrapers/scion.py` | **New scraper** — the sixth PRIMARY-tier agency. 218 postings walked, **15** after the dev filter |
| `triage/channels/agencies.py` | `DEFAULT_SOURCES` is now the whole registry (7), not a hand-picked 4 |
| `docs/operating/{services,tuning}.md` | Counts, constants and the rot baseline re-measured 2026-07-24 |

Agency supply per run: **~155 → ~630.**

### The lesson, and what it cost

**A small plausible number is the hardest failure to see, because it looks like an answer.** The
2026-07-22 health line read `insightglobal 87 · teksystems 78 · motion 27 · mondo 15 · apex 3 · kore1 2`
and was interpreted — in this log, in `services.md`, and in the `DEFAULT_SOURCES` comment — as four
healthy sources plus two small boards. All four small numbers were bugs, and **no two had the same
cause**: our own page cap, a cookie-gated results table, an unchecked HTTP status, and a regex anchored on
the wrong element. The only thing they shared was the *shape* of the symptom.

**And the first write-up of this entry got Motion's cause wrong, which is its own lesson.** It said the
site had changed its pagination parameter from `?page=` to `?start=`. The live site does behave that way,
but the committed scraper already used `?start=` and already stopped on "no new hrefs" — the diagnosis
came from reading the module's first 40 lines, seeing `MAX_PAGES = 6`, and letting a true site-level
observation fill the gap instead of reading the pagination code underneath it. The real ceiling was ours.
**A plausible external cause is the most comfortable place to stop looking**; the correction is to prefer
the explanation that implicates your own constants until the external one is proven. The verifier that
caught it did so by running the committed code, which is why the workflow had one.

What it cost: Motion is one of Ben's best agency partners and was returning ~2.5% of its dev contract
supply, for at least two days and probably longer. The two live Motion contracts on the 2026-07-24 apply
doc ($75–100/hr and $69.5–76/hr) were both found by hand; the tool could not have surfaced them.

Three corrections now in the code rather than in prose:

1. **A fixed page cap cannot distinguish "the board ended" from "pagination broke".** Motion's loop
   refetched page one six times and reported success. Walks now stop on *no new postings*, and keep
   `MAX_PAGES` only as a runaway guard — so the next paginator change moves the count loudly.
2. **Never treat an exception-free empty response as an empty board.** TEKsystems swallowed 403/503
   sub-sitemaps as zero-`<loc>` documents. Status is checked now.
3. **Excluding a source on a low count is a bet that the board is small.** That bet lost 4/4.
   `DEFAULT_SOURCES` is the full registry; a source leaves it on evidence, never on suspicion.

### Also this run

- **A false alarm worth recording, because the reasoning was wrong in an instructive way.** Five digests
  logged `extractor returned 5 job(s) … but the email carries 27 job link(s)`, and the identical count
  across five emails read as a hard cap. There is none — the prompt forbids truncating and
  `_EXTRACT_MAX_TOKENS` is 20000. Three were the same IntelliSearch template rendering ~5 jobs in the
  body, and one was a **single-job** "Now Hiring" email that also carried 27 links, which is decisive:
  the extra links are related-jobs rails and footer chrome, not postings. The extractor was correct and
  the reconciliation did exactly its job. **The defect is the warning's wording** — "recovering the 22 it
  left out" reads as data loss and cost a round of investigation.
- **`mondo.gosnaphop.com` surfaced in the unclassified-host report** and is already Mondo's own sitemap
  host — no action, the classifier working as intended.

## 2026-07-20 — the staleness run

The run that exposed the tool's biggest blind spot. 358 jobs analyzed over a 7-day window; Ben had
interviewed all week (FPOV 7/15, College Board 7/17) and applied to nothing.

### What shipped

| Feature | Commit | What it does |
|---|---|---|
| Cheap prefilter | `511f1a0` | Regex + Sonnet gates before the Opus analyzer |
| Parallel liveness | `81e719b` | Post-ranking availability check on the ranked jobs |
| Runbook rewrite | `96f1f9d` | 9 steps, ending in tailored résumés + a commit |
| Measured speedup + truncation fix | `6aad993` `b789b59` | Corrected optimistic claims; `max_tokens` headroom |
| Configurable concurrency | `511f1a0` | `max_workers` 5 → 12 in `config.yaml` |
| Alert vs. correspondence split | (this commit) | Human threads never archived, never ranked as fresh leads |

### Lessons — process

**1. Weekly triage cadence is too slow for the Tier-1 contract lane.**
Every one of the five 7/13 picks verifiable at its primary source had closed within 7 days — including
Trident at $90/hr (fit 88) with "100+ applicants". LinkedIn agency contract reqs fill in under a week.
Run every 2–3 days, and apply same-day for Tier-1 contracts. **Ranking quality was never the
bottleneck; latency to apply was.**

**2. Freshness at scrape time ≠ freshness at apply time.**
VortexLink (fit 82) was scraped successfully *during* the run and was already dead when checked minutes
later. Any availability signal has a short half-life; check at the end of the run, not the start.

**3. Delegate high-volume mechanical work to subagents.**
The Gmail archive is ~3 calls × 100+ emails. Run inline it dominates the session; as a subagent it runs
in the background while the main thread continues. It is now the slowest single step (14.5 min for 101
emails) and should be **sharded across several subagents** next.

**4. A runbook that stops early leaves standard work to inference.**
`/job-triage` ended at "deliver the digest", so building tailored CVs for the top picks — which is standard
— read as an open question and got asked about instead of done. Anything standard must be *written in
the runbook*, not left to be inferred. Same for the carryover re-check, the apply doc, and the commit.

### Lessons — engineering

**5. `max_tokens` is headroom, not a target.**
It truncates mid-generation; with structured output that means invalid JSON. It does **not** make the
model terse — the model stops on its own. Unused tokens are not billed, so there is no reason to run
near the edge. Each site's failure mode differs and all of them lose work:

| Site | Was | Now | Failure mode when truncated |
|---|---|---|---|
| `ingest.py` | 8000 | 20000 | a 30-job digest is lost entirely |
| `analyze.py` | 4000 | 8000 | falls back to `verdict=SKIP` — job quietly lands in "Rejected" |
| `prefilter.py` | 200 | 400 | screen fails open — wasted call |

`ingest.py` had already documented this after a previous incident, and it was repeated anyway. **When a
comment in this codebase explains a past failure, read it as a rule, not trivia.**

**6. Validate heuristics by replaying real run data before shipping them.**
The first year-bar regex looked correct and passed hand-written tests. Replayed against the actual 358
jobs it would have killed 5 good ones — it read Darkroom's *"operating for 10 years"* (company age) and
Fractal's *"Experience 5–10+ Years"* (a range) as hard requirements. The fix: count only figures
adjacent to "experience", take the **minimum** stated bar and the **low end of a range**. Pinned in
`test_prefilter.py`. Every state file under `data/corpus/` is a free regression corpus — use it.

**7. A false OPEN is the worst output a liveness check can produce.**
A naive LinkedIn check reported all three reqs confirmed-closed-in-browser as OPEN, because the closed
banner only renders in a signed-in session. The `/jobs-guest/` API is worse — "no longer accepting"
appears in boilerplate on *open* listings and is missing on closed ones. LinkedIn/Indeed/aggregators are
therefore **UNVERIFIED, never OPEN**, and every ambiguous case (timeout, bot-wall, error) resolves to
UNKNOWN. Saying "I don't know" beats a green light on a corpse.

**8. Aggregators never expire listings.** `remotevibecodingjobs.com` and friends show "Apply" forever. A
200 proves only that the aggregator still holds a database row. Resolve to the primary source or mark
unverified — never treat aggregator presence as evidence a req is open.

**9. Bias cheap filters toward KEEP, and fail open.**
A false keep costs one Opus call; a false reject means Ben never sees the job. Those are not symmetric.
The screen prompt says so explicitly, and any API error, refusal, or unparsed response keeps the job.

**10. Measure before claiming a speedup.**
Estimated "~25 min → ~4–6 min"; measured **~9.5 min**. The prefilter removes 28% of Opus calls but adds
a 3.2s screen to the 94% of jobs surviving the regex, netting only ~9% wall-clock. **It is a cost win,
not a speed win.** The runtime lever is `max_workers` (2.4× on its own).

**11. Never pipe a long run through `tail`.**
`tail` buffers until the process exits — 25 minutes with a 0-byte log and no way to tell progress from a
hang. Use `tee`. (Diagnostic while blind: `%CPU` near 0 with *cycling* TCP connections means
network-bound progress, not a stall.)

**12. Use the Edit tool for doc changes, not scripted string replaces.**
A `python3` replace missed because the file used Unicode `≥` and the pattern used ASCII `>=`. It failed
silently and a commit message claimed the doc was updated when it wasn't. Edit errors on no-match;
string replaces do not.

---

### Lesson 13 — the obvious fix was the wrong fix (correspondence handling)

Filed as "triage ingests recruiter reply threads — filter them out." **Filtering them out would have
destroyed real value.** Those emails produced three of the top Tier-1 jobs that run — College Board
(86), Item Cloud Blue (78, 76) — and none of them have a link. They exist *only* because triage read a
recruiter's email body. Extraction was never the bug.

The bug was that one category was being used for **three** purposes with different safety profiles:

| Purpose | Correct behaviour | What was happening |
|---|---|---|
| Extract & rank the job | keep — it's real | ✅ working |
| Put the email on the archive list | never | ❌ would archive a live thread |
| Present it as a fresh lead | never | ❌ College Board at #2, mid-process |

The ranking half was the more dangerous one and wasn't in the original bug report at all. Ben supplied
it in conversation: he was between a 7/17 panel and a 2nd technical interview at College Board while
the tool listed it as a fresh contract to apply to. Cold-applying via an agency there could have cut
across his own live process.

**Generalisable:** when a bug report says "stop ingesting X", check what X is *worth* before filtering
it. The fix is usually to split the downstream uses, not to drop the input. Fixed in `ingest.
_is_correspondence` + a dedicated worklist section; the classifier is default-safe because the two
error directions are wildly asymmetric (misread alert → one email stays in the inbox; misread
conversation → archived and cold-applied to).

---

## Open bugs / next steps
- **[COSMETIC · found 2026-07-24] The link-reconciliation warning reads as data loss.** `extractor
  returned 5 job(s) for X, but the email carries 27 job link(s) — recovering the 22 it left out` fires on
  every templated digest, where the surplus links are related-jobs rails rather than missed postings. It
  is the tool working correctly, but the wording cost a full investigation this run. Reword to something
  like `22 unclaimed links recovered as bare jobs (may be related-job chrome)`.
- **[DEFERRED · 2026-07-24] No automatic rot detector.** A per-source floor warning when a count drops
  >40% run-over-run was scoped and **deliberately declined** by Ben as likely-flaky for the value. The
  standing mitigation is the health line in the run summary plus the corrected instinct that a low count
  is a hypothesis. Revisit only if a scraper rots again undetected.
- **[GAP · found 2026-07-23] Tier-2 browser queue can be 100% unfetchable — and the runbook oversells it.**
  On the 2026-07-23 run all 8 queued links were dead: 1 Indeed `pagead/clk` tracker → hard Cloudflare wall
  even in Ben's real Chrome; 7 `elinks.dice.com` email-click wrappers → expired to browser error pages, and
  because they never resolved a title/company the `dice.com/jobs?q=` fallback had nothing to search. Two doc
  claims in `triage-operating.md` need caveats: line ~227 "Proven end-to-end on Indeed" (now Cloudflare-walled)
  and line ~200 "Dice is fully automatic" (true for real job pages, false for expired elink wrappers). **Fix
  candidates:** resolve/strip `elinks.dice.com` wrappers before queuing; drop Indeed `pagead` trackers from the
  queue (they redirect to sponsored listings even when cleared).
- **[GAP · found 2026-07-23] Dice JD fetches 429 through the shared `r.jina.ai` proxy** — most of this run's
  32 couldn't-fetch. A public proxy with no per-user budget throttles under load; a stranger cloning the repo
  hits the same wall. Worth documenting as a known external dependency (and a reason to prefer first-party fetch).
- **[NOTE · 2026-07-23] The extractor-undercount recovery path is load-bearing, not a safety net.** Multiple
  multi-job alert emails had the Sonnet extractor return ~5 of 20–27 links; the "recovering the N it left out"
  reconciliation is what makes coverage correct. Backed by the Project-D "silent LLM under-production" bullet.
- **[PERF] Shard the email archive across subagents** — 14.5 min for 101 emails is now the slowest step.
  (2026-07-23: 16 emails via one subagent ran fine, ~3.5 min; the backstop correctly skipped 2 mixed threads.)
- **[PERF] `ingest.py:281` extraction pool is still 6** while the analyze pool is 12.
- **[PERF] Pipeline ingest into analysis** — extraction fully completes before any analysis starts;
  streaming would overlap the two stages.
- **[PERF] Test whether `max_workers` can exceed 12** without hitting Anthropic 429s (16 projects ~7 min).
- **[GAP] Liveness cannot check LinkedIn/Indeed** — those still need the browser (Tier-2) path.
