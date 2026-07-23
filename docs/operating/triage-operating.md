# Triage — Operator's Guide (as-built)

> **If you are a Claude session and Ben pointed you here: this is all the context you need to run,
> explain, or modify the triage tool.** Read this top-to-bottom, then act. Design rationale (the *why*)
> lives in [`triage-plan.md`](triage-plan.md); this doc is the *how it actually works now*.
>
> **Before changing anything, read [`triage-engineering-log.md`](triage-engineering-log.md)** — the
> lessons behind the current design, plus the open bug list. Several of its entries are mistakes that
> were made twice; it exists so there isn't a third time.

## What it is (30 seconds)

`triage/` is a **second, separate tool** in the `jobs-db` repo. It is NOT jobs-db (which is market
research writing to a Google Sheet). Triage reads Ben's Gmail, scrapes the full job description behind
each job link, judges each JD against Ben's goals with Opus 4.8, and writes a **ranked markdown
worklist** Ben reads to decide what to apply to. Ben runs it manually; it's read-only against his inbox.

**Hard rule:** `triage/` is a leaf package — it may import `core/`, never another leaf. See
`CLAUDE.md` → Code layout; `core/test_layering.py` enforces it. The seam is deliberate and must stay
clean.

## Run it — ALWAYS through Claude Code (`/job-triage`)

**Triage is run by asking Claude — `/job-triage`, or "run my triage".** It must go through a Claude session
because two of its steps are things the Python script physically cannot do — they are Claude's tools, not
the script's:

1. **Tier-2 browser JD retrieval** — pulling the JDs behind bot-walled links (Indeed, Dice) needs
   Claude-in-Chrome driving Ben's real browser (see "Tier-2").
2. **Moving processed mail** to the `jobs-triage` label needs the Gmail connector (see "Archiving").

Run bare in a terminal, `python -m triage` still works but gives you *only* Tier 1 — email-body/easy-fetch
analysis, no walled JDs, no archiving. The full digest only happens through Claude.

**The `/job-triage` runbook** (`.claude/commands/job-triage.md`) tells the session exactly what to do; the short
version is a three-phase loop:

```
Phase 1  .venv/bin/python -m triage        → worklist (preliminary) + state + archive-list + browser-queue
Tier 2   Claude + Ben's Chrome             → fetch each queued walled JD → browser-jds-<date>.json
Phase 3  .venv/bin/python -m triage --merge → re-rank with the full JDs → final worklist
Archive  Claude + Gmail connector          → move processed emails to jobs-triage
Digest   Claude                            → present Focus picks + summary to Ben
```

Ben's only manual touch: type `/job-triage`, and click a CAPTCHA checkbox if a walled site challenges (one
click usually clears the whole session). Everything else is automatic.

Flags: `--days N` (window, default 3) · `--sample N` (process only N representative WHOLE emails,
source-spread — the small end-to-end test; each sampled email is fully processed and therefore archives)
· `--limit N` (cap jobs, cruder) · `--no-browser` (skip the Tier-2 queue) · `--no-archive` (skip the
archive list) · `--merge` (Phase 3).

**Small representative test:** `--sample 5` picks 5 whole emails spread across source types (Indeed and
Dice first, so the walled sources always appear and Tier-2 gets exercised), processes every job in them,
and archives all 5. It's the recommended way to eyeball the digest + prove the full loop before a full
run. `--sample` beats `--limit` here because `--limit` caps *jobs* and LinkedIn sorts first, so a small
limit tests neither the walled sources nor archiving.

> **Memory rule that applies here:** never trigger a jobs-db pull/fetch on Ben's behalf without his
> explicit OK. Running *triage* (reading Gmail) is authorized — that's what the tool is for.

## Pipeline & file map

`read Gmail → extract → skip seen/applied → easy-fetch + analyze-from-email → rank → worklist + queue`
→ *(Claude: browser-fetch walled JDs)* → `--merge re-rank` → *(Claude: archive processed mail)* → digest

| File | Role |
|---|---|
| `triage/__main__.py` | two-phase orchestration: Phase 1 (`-m triage`) + Phase 3 (`--merge`) |
| `triage/channels/` | The job-input registry: `mail.py` (Apple Mail read via AppleScript, captures Message-ID — macOS only), `boards.py` (a watchlist of Greenhouse/Lever board tokens from `config/settings.yaml`; one keyless call per board, postings arrive with description, company, title and employer-stated pay — any OS, no key), `agencies.py` (the six staffing-firm scrapers in `core/scrapers/`, read as job input — the only source of **contract** supply; window, per-source cap, per-source isolation and a WARNING on a zero, because these break by returning nothing rather than by raising; on in the shipped config, off in the keyless demo for speed), `paste.py` (URLs from `--paste` / `--paste-file`; fetches the JD and backfills company/title — any OS, no key), `common.py` (Sonnet 5 extraction + archive-list, transport-agnostic), `__init__.py` (registry, per-channel isolation, counts) |
| `core/fetch.py` | domain-routed easy-JD fetch chain + `needs_manual_review()` (shared layer) |
| `triage/analyze.py` | one Opus 4.8 structured-output call per JD vs the goal anchor |
| `triage/rank.py` | deterministic tier finalize + composite sort key |
| `triage/worklist.py` | renders the markdown digest |
| `triage/store.py` | `seen.json` (auto dedup) + `skiplist.md` (Ben's applied/rejected) |
| `core/models.py` | schemas, `Job` carrier, `composite_id`, serialization, `needs_browser_fetch` (shared layer) |
| `triage/config.py` | the accessors. The values live in three files: `profile/rubric.md` (the goal anchor), `profile/profile.yaml` (inbox, sheet, agencies, archive label), `config/settings.yaml` (provider, models, window, concurrency, channels) |
| `.claude/skills/job-triage/SKILL.md` | the `/job-triage` runbook Claude follows to do all phases |
| `matches/` (git-ignored) | the curated apply doc Ben reads: `<date>.md`, one per run — an **Obsidian-compatible checkbox apply-list** (`- [ ]` per role, with fit/rate/liveness, apply link and résumé path underneath), grouped Tier 1 / Tier 2 / Carryover / Reply-don't-apply, so Ben copies it straight into his notes to manage applying |
| `data/runs/` (git-ignored) | disposable run output: `worklist-<run_id>.md`, `browser-queue-`, `browser-jds-`, `archive-`, `fetch-failures-`, `latest-run.txt` |
| `data/corpus/` (git-ignored) | accumulated judgments: `state-<run_id>.json`, `seen.json`, `applied.json` — survives a clear of `runs/` |

Note: modules are **flat** (`fetch.py`, not `fetch/`) — simpler for a tool this size; the plan's
directory diagram was not followed literally.

## The three models

- **Analyze = `claude-opus-4-8`**, adaptive thinking, default (high) effort — the judgment. ~6–12s/JD.
- **Extract = `claude-sonnet-5`** — cheap mechanical job extraction from emails.
- **Prefilter = `claude-sonnet-5`** — the cheap screen described below.
- All use a prompt-cached system block. Change via `config/settings.yaml → models`.

## Prefilter — two cheap gates before Opus (added 2026-07-20)

The 2026-07-20 run sent all **358** jobs to Opus and took **~25 min**. Most were killable by a rule
already written down in `market-insights.md`. `triage/prefilter.py` adds two gates ahead of the
expensive call:

1. **`hard_skip`** — free regex, no API call. Rejects a stated **10+ year entry bar**, an **active**
   security clearance, **≥50% travel**, and off-lane **primary stacks in the title** (Java/.NET/mobile/
   SAP/Salesforce). Measured **5.9%** of a run (21/358).
2. **`cheap_screen`** — one small Sonnet call. Rejects the obvious out-of-lane remainder (pure ML
   research, non-engineering, onsite-far, junior). Measured **24%** of what reaches it, median 3.2s.

**⚠ The prefilter is a COST win, not a speed win.** Measured on the 2026-07-20 data: it removes **28% of
Opus calls**, but adds a 3.2s Sonnet call to the ~94% of jobs that survive the regex, which nearly
cancels the time saved by skipping Opus — net wall-clock improves only **~9%**. The runtime win comes
almost entirely from `max_workers` (below). Expect the prefilter to make a run *cheaper*, not *faster*.

**Both are deliberately biased toward KEEP.** A false keep costs one Opus call; a false reject means Ben
never sees the job. The Sonnet prompt says this explicitly, and the screen **fails open** — any API
error, refusal, or unparseable response keeps the job.

Prefiltered jobs are **not** hidden: they render under "Rejected / skipped" with their reason, and carry
`prefiltered: true` in the state file.

**Validated against the real 2026-07-20 run** (`state-2026-07-20-094851.json`): 0 of 59 high-fit (≥70)
jobs dropped by either gate; the highest-scoring regex kill was fit 58.

⚠ **The year-bar rule is subtle.** It takes the **minimum** stated bar and the **low end of a range**,
and only counts figures adjacent to the word "experience". Taking the max, or matching bare year
figures, produces false positives — it read Darkroom's "operating for 10 years" (company age) as a
10-year requirement and Fractal's "Experience 5–10+ Years" as 10 rather than 5. Those cases are pinned
in `triage/test_prefilter.py`; run it before touching the regexes:

```
.venv/bin/python -m pytest triage/ -q
```

Turn the whole thing off with `prefilter.enabled: false` (Opus judges everything, the old behaviour), or
keep the free rules and drop the API call with `prefilter.screen: false`.

## Alerts vs. live correspondence (added 2026-07-20)

Ben's inbox mixes two things that look identical to a keyword filter: **automated job alerts** and
**humans writing to him about real roles**. `_JOB_HINT` can't tell them apart — a recruiter's email is
full of the same words. `channels.common._is_correspondence` does, and the distinction drives two behaviours:

| | Automated alert | Live correspondence |
|---|---|---|
| Extracted & ranked | yes | **yes** — these carry real, link-less jobs |
| On the archive list | yes | **never** |
| In the ranked picks | yes | **no** — own section: "📬 Live correspondence" |

**Both behaviours exist because of real 2026-07-20 failures:**

- **Archiving.** The archive list is per-message but Gmail archives per-**thread**. One line can pull a
  whole live thread — Ben's own replies and unread mail included — out of the inbox. Three threads were
  caught by hand that run, one of them his **College Board interview correspondence** (he was between
  a 7/17 panel and a 2nd technical interview).
- **Ranking.** That same College Board role ranked **fit 86 at #2 in Tier 1**, presented as a fresh
  lead. Acting on the list meant cold-applying through an agency to a company already mid-process with
  him — which can cut across a direct process.

**Do not "fix" this by filtering correspondence out of ingest.** Those emails produced three of the
top Tier-1 jobs that run (College Board 86, Item Cloud Blue 78/76) and they have **no link** — they
exist *only* because triage read the recruiter's email body. Extraction is the value; archiving and
ranking are the hazards.

**Detection is default-safe** — a message is correspondence unless *provably* automated:
1. it is a reply (`In-Reply-To` / `References` present), **or**
2. the sender doesn't match `_AUTOMATED_SENDER` (`noreply`, `jobalerts`, `alert@`, board domains…).

The asymmetry is deliberate: a misread alert just stays in the inbox; a misread conversation gets
archived and cold-applied to. Pinned in `triage/test_correspondence.py`, including the three real
threads. **The Gmail step keeps its own backstop** — skip any thread containing a SENT message or a
message not on the list.

## Liveness — is the req still open? (added 2026-07-20)

`triage/liveness.py` runs AFTER ranking, in parallel, over the jobs Ben might act on (non-SKIP, with a
link, capped at `liveness.max_check`). It exists because on 2026-07-20 **all five 7/13 picks that could
be verified at their primary source had already closed** — the tool ranked dead reqs perfectly and had
no idea. VortexLink was scraped successfully *during* that run and was gone minutes later, so freshness
at scrape time is not freshness at apply time.

Three states, rendered in the worklist as 🟢 OPEN / 🔴 CLOSED / ⚪ UNVERIFIED:

| State | Meaning |
|---|---|
| **open** | fetched the page, no closed-marker found |
| **closed** | explicit marker ("no longer accepting applications", "no longer available") or HTTP 404/410 |
| **unknown** | bot-walled, unreachable, an aggregator, or a host needing a signed-in session |

**⚪ UNVERIFIED is not reassurance.** It is the honest answer where a check is impossible, and it covers
the two biggest sources:

- **Aggregators** (`remotevibecodingjobs.com` and friends) show "Apply" forever. A 200 proves only that
  the aggregator still has a database row.
- **LinkedIn** cannot be judged anonymously. Measured against three reqs confirmed closed in a signed-in
  browser (Trident, Themesoft, Encamp), the public page carried **no closed-marker for any of them** — a
  naive check reports all three OPEN. The `/jobs-guest/` API is no better: "no longer accepting" appears
  in boilerplate on *open* listings and is missing on closed ones. So LinkedIn and Indeed are always
  UNKNOWN and get pushed to the browser (Tier-2) path, which is the only thing that actually works.

**A false OPEN is the worst output this module can produce** — it's a green light on a dead req. Every
ambiguous case therefore resolves to UNKNOWN, never OPEN, and a network failure never reads as CLOSED.

What still needs a human/browser: LinkedIn, Indeed, and aggregator listings. Dice is fully automatic
(it returns 410 for expired postings).

Tune via `config/settings.yaml → liveness` (`enabled`, `max_check`, `workers`). Tests: `triage/test_liveness.py`.

## Concurrency — the dominant runtime lever

`config/settings.yaml → max_workers` (default **12**, was hardcoded 5). The pipeline is entirely network-bound
(API + scraping), so threads are nearly free and runtime scales close to linearly. Measured against the
2026-07-20 run (358 jobs, 20.9s/job serial-equivalent):

| workers | projected wall-clock |
|---|---|
| 5 (old) | ~25 min (observed) |
| 12 (current) | **~9.5 min** |
| 16 | ~7 min |

Raise it further only after checking the Anthropic rate limit — if runs start returning 429s, come back
down. This knob, not the prefilter, is what makes a run fast.

## Tier-2 — browser JD retrieval for bot-walled sources (IMPORTANT)

Some sources can't be scraped by the Python script: **Indeed** returns `403` / Cloudflare Turnstile,
**Dice** links are `elinks` trackers that redirect into a JS-rendered SPA. No free headless scraper beats
these — bot detection blocks `navigator.webdriver` + TLS fingerprints + serves CAPTCHAs (tested). The
reliable, free path is **Claude-in-Chrome driving Ben's real Chrome**: real residential IP, real browser
fingerprint, no webdriver flag, his logged-in sessions — the anti-bot check passes because it's genuinely
his browser, and Claude just reads the rendered JD. **Proven end-to-end on Indeed (2026-07).**

How it works in a run:
- Phase 1 marks a job for Tier 2 via `needs_browser_fetch()` — it has a link, no full JD yet, and isn't a
  SKIP — and lists it in `browser-queue-<date>.json`.
- Claude opens each queued link in Ben's Chrome (`navigate` → `get_page_text`).
- **CAPTCHA handoff:** if the page is a wall (title "Just a moment…" / text "Verify you are human"),
  Claude pauses and asks Ben to click the checkbox, then continues. **One click drops a `cf_clearance`
  cookie that unlocks the whole session** — so it's ~one click per run, not per job. (Staying logged into
  the sites makes even that rare.)
- Dice `elinks` links land on a listing → Claude searches `dice.com/jobs?q=<title> <company>` and opens
  the real posting.
- Claude writes `{composite_id: jd_text}` to `browser-jds-<date>.json`; Phase 3 (`--merge`) re-analyzes
  those with the full JD and rewrites the worklist. Anything still unreadable stays in the worklist's
  "⚠ manual check" list — never fed to the ranker as garbage.

This is why triage runs through Claude: the script hands off a queue, Claude does the browser work.

**Browser won't connect? (`list_connected_browsers` returns `[]`, "Browser extension is not connected")** — the Claude desktop app and Claude Code share ONE Chrome extension and only one can hold it. **Quit the Claude desktop app before the browser step.** If still empty, a stray helper may be holding it: `pkill -f "Claude.app/Contents/Helpers/chrome-native-host"`, then reconnect (extension Connect button or `/chrome` → Reconnect). Other 2026-07 factors: a claude.ai **auth outage** breaks the connection; a **Chrome update** can blank the extension popup — the blank popup does NOT block automation (that runs through the service worker), only `list_connected_browsers` returning a browser matters. The `/job-triage` runbook does this as a preflight.

## Archiving — how processed emails leave the inbox (IMPORTANT)

Goal: after a run, move each processed job email out of INBOX into the `jobs-triage` Gmail label, so the
inbox shows only *unprocessed* mail. Two things make this non-trivial, and shape the design:

1. **Apple Mail can't do it.** AppleScript `move`/`set mailbox` on a Gmail account **dual-labels** — it
   adds the target label but does NOT remove INBOX (confirmed live + widely documented; Gmail's label
   model vs Apple Mail's single-folder assumption). GUI-scripting the Archive menu or a Trash-hack are the
   only Apple-Mail workarounds and both are fragile/risky. So the tool does **not** move mail.
2. **The Python script and Claude are different programs.** The reliable mover is the **Claude Gmail
   connector** (`mcp__claude_ai_Gmail__*`) — but that lives in a *Claude session*, not in the standalone
   `python -m triage` process. A script run in a bare terminal cannot reach it.

**So the design splits the work:** the script writes an **archive list**; a Claude session executes the
moves. The `email_mid` (Message-ID) captured at read time is the handle that ties them together.

- **What the script writes:** `data/runs/archive-<date>.txt` — one line per email that's *done*: every
  job extracted from it (pre-dedup) is resolved — analyzed this run, already seen/applied, **or a
  duplicate of a job resolved elsewhere**. Resolution is by *dedup key*, so a duplicate-alert email
  (LinkedIn + Google on the same job) still archives instead of lingering, while a `--limit`-truncated
  digest with any un-analyzed job is never half-archived. Each line: `<message-id>\t<label>\t<context>`.
  `--no-archive` skips it.
- **What a Claude session does** (the archive step) — for each Message-ID in the list:
  1. `search_threads(query="rfc822msgid:<id>")` → get the `threadId` (or messageId).
  2. `label_thread(threadId, ["<jobs-triage label id>"])` — add the label. Get the id from `list_labels`
     (`list_labels` is the only source for it — the id names one person's mailbox and is not
     written down in this repo).
  3. `unlabel_thread(threadId, ["INBOX"])` — remove from inbox. **This is what actually archives it.**
  Both label ops are reliable and reversible (a copy always remains in All Mail).

### Running it as ONE seamless request (what Ben wants)

If Ben **asks Claude** to run triage (in Claude Code / claude.ai), the whole thing is one request — no
separate ask:

1. Run `.venv/bin/python -m triage` via Bash.
2. Read `data/runs/archive-<date>.txt`.
3. Archive each Message-ID via the connector steps above.
4. Report: worklist summary + how many emails archived.

If Ben instead runs `python -m triage` himself in a bare terminal, steps 2–4 don't happen automatically
(no Claude in the loop) — the list just waits until he opens a session and says "archive the triage list."
That's the only reason it would feel like a separate step. **To keep it automatic, start the run by
asking Claude.** (A future fully-headless option is Gmail IMAP + app password — see triage-plan; not built.)

## Tuning — three files, split by what changes them

There was a single config file inside `triage/` until 2026-07-22, and 54% of its 141 lines were a
prompt rather than settings. Splitting it means an edit to the rubric — the file edited most — can no longer break the load
of the models, the window and the channel flags.

- **`profile/rubric.md`** — the "10/10" fit anchor. **This is the single most important knob**, it is the
  only personal rubric sent to Claude, and if rankings feel off it is the first thing to edit. The whole
  file is the prompt: no front matter, nothing stripped. **Nothing parses it**, so no edit to it can stop
  the tool booting — which is exactly what a bad indent in the old block scalar did.
- **`profile/profile.yaml`** — identity: `inbox` (Gmail account name in Apple Mail, mailbox),
  `archive_mailbox`, `applied_sheet`, `primary_agencies`, `secondary_platforms`.
- **`config/settings.yaml`** — operations: `llm.provider` + `models`, `window_days` (default 3),
  `max_workers` (default 12, the main runtime knob), `prefilter.enabled` / `prefilter.screen`,
  `precedent`, `dedup`, `liveness.enabled` / `max_check` / `workers`, `channels`.
- Secrets: `.env`, and nowhere else.
- Rank tiers are code, not config: PRIMARY = agency contract remote/DFW → SECONDARY = contract platforms
  → OPPORTUNISTIC.

### Picking channels for one run — `--channels`

`config/settings.yaml` says what a normal morning does. `--channels` says what *this* run does, and
never writes back:

```
python -m triage --channels agencies            # only the agency scrapers
python -m triage --channels mail,agencies        # both
python -m triage                                 # whatever config enables
```

Two properties worth knowing, because they are deliberate (full argument:
`.scratch/oss-rag-6-extraction/issues/14-composable-channel-selection.md`):

- **It is an override, not a second config.** Omitting the flag is indistinguishable from the flag not
  existing. A run that changes the channel set leaves no trace in settings — so an experiment can
  never quietly become the default.
- **Selection is exhaustive, not additive.** `--channels agencies` runs agencies and *nothing else*,
  including channels enabled in config. This is the point: on a day when mail triage is already done,
  additive selection would re-read the inbox and re-archive it as a side effect of asking for
  contract supply. The health line still prints every registered channel, so `mail off` is visible
  and what ran is never inferred from what was typed.

A misspelled name is a hard error naming it and listing the valid set — it does not fall back to
"no channels", which would render identically to a quiet morning.

**The practical use:** `agencies` ships off because it is a 130s+ scrape, and it is the tool's only
source of **contract** supply. When a morning's Tier 1 comes back empty, `--channels agencies` adds
that supply without touching the mail run that already happened.

## Dedup — how "don't show me this again" works

- `data/corpus/seen.json` — every id ever analyzed; auto-written. Re-runs skip these, so **day-2 runs only
  process new arrivals** (this is what keeps ongoing cost small).
- `profile/skiplist.md` — Ben pastes an id here when he applies to / rejects a role. Checked *before* any
  fetch/analysis. Each worklist entry prints its `id` for this.
- id = `composite_id` = normalized `company|title|city`. Same company+title collapses to one id (by
  design), so near-dup postings dedup together.
- **To force a clean full-backlog run:** `rm data/corpus/seen.json`.

## Gotchas discovered during the build (read before debugging)

- **LinkedIn links only survive in the raw email `source`, not `content`.** `channels/mail.py` reads
  `source of m` and parses it with Python's `email` module (decodes quoted-printable), then hands the
  decoded job URLs to the extractor. If links stop appearing, this is the first place to look.
- **Indeed hard-blocks scraping (HTTP 451)** — even via Jina. Those degrade to the email snippet and
  appear under "⚠ Couldn't fetch" for Ben to open by hand. Expected, not a bug.
- **LinkedIn guest endpoint works from Ben's residential IP** (`jobs-guest/jobs/api/jobPosting/{id}`).
  It would fail from a datacenter IP — this is why the tool runs locally, not in CI/cloud.
- **Mega-digest emails** ("72 new jobs today") are capped: extractor returns ≤30 jobs/email
  (`_MAX_JOBS_PER_EMAIL`) and is told to keep the most senior-relevant. Raised extract `max_tokens` to
  8000 so big digests don't truncate mid-JSON.
- **First run = backlog.** ~180 jobs in a 3-day window ≈ a few minutes + ~$2–4 Opus. Use `--limit` to
  sample. Steady state is cheap (`seen.json`).
- **A job can appear in both Focus and "Couldn't fetch"** — analyzed from the email snippet (so it's
  actionable) but flagged because the full JD didn't scrape. Intended.
- Fetch/analyze failures never crash the run — they're recorded on the Job and surfaced in the worklist.

## Worklist anatomy

`▶ Focus today` (top ≤5 STRONG/FIT, full detail: why/role/meets-goals/red-flags/tailor-keywords/link/id)
→ `PRIMARY / SECONDARY / OPPORTUNISTIC` (ranked one-liners) → `✕ Rejected` (SKIP + reason) →
`⚠ Couldn't fetch` (open manually). Links render as `[open ↗](url)`; each entry ends with its `id`.

## What Ben still owns (not code)

1. **Widen the funnel** — set up job-alert emails on boards (LinkedIn saved searches, YC, a16z, ai-jobs,
   agencies) + reroute Dice (to the address in `profile/profile.yaml → inbox.account`) → Gmail. More inflow → better Focus picks. Today the
   inbox skews LinkedIn AI-engineer digests (enterprise/onsite), so fits are thin.
2. **Record decisions** in `skiplist.md` as he applies/rejects.

## If Ben asks you to change behavior

- Ranking/fit feels wrong → edit `profile/rubric.md` (or the rubric bands in
  `analyze.py:_SYSTEM`).
- Missing a source/board → add its host to `channels/common.py:_JOB_HOSTS` and a fetch handler in `fetch.py` if
  it's a new ATS.
- Cost/latency → lower `models.analyze` to Sonnet, or default `--limit`.
- Always keep the leaf seam clean; code a sibling needs belongs in `core/`, not imported across.
