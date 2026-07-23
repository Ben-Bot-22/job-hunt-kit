# triage — daily job-triage tool

A leaf package: it may import `core/`, never another leaf.
It reads Ben's Gmail, follows the job links inside, scrapes each full job description, analyzes it against
Ben's goals with Claude (Opus 4.8), and writes a **ranked markdown worklist** — top picks to focus on, then
everything else ranked with a one-line reason, plus fit / role / red-flags / resume-keywords per role.

Full design + rationale: `../docs/operating/triage-plan.md`.

## Run it — through Claude Code (`/job-triage`)

Run it by asking Claude: **`/job-triage`** (or "run my triage"). It must go through a Claude session because
two steps are Claude's tools, not the script's: **Tier-2 browser JD retrieval** (bot-walled Indeed/Dice,
via Claude-in-Chrome + your real browser) and **moving processed mail** to `jobs-triage` (Gmail connector).
Your only manual touch: type the command, and click a CAPTCHA checkbox if a walled site challenges (one
click clears the whole session).

The underlying script (Claude runs these for you; `--merge` is Phase 3 after the browser step):

```bash
.venv/bin/python -m triage                 # Phase 1: last 3 days -> worklist + state + browser-queue
.venv/bin/python -m triage --merge         # Phase 3: re-rank with the browser-fetched JDs
.venv/bin/python -m triage --sample 5      # small test: 5 representative WHOLE emails, fully processed
.venv/bin/python -m triage --days 5        # widen the window
.venv/bin/python -m triage --no-browser    # Tier-1 only (no walled-JD queue)
```

Run bare in a terminal it still works but gives Tier 1 only (email-body/easy-fetch analysis, no walled
JDs, no archiving). Full detail: `../docs/operating/triage-operating.md`.

## How it works (pipeline)

`read Gmail (Apple Mail) → Sonnet extracts job links+data → skip already-seen/applied → fetch full JD →
collapse semantic duplicates → Opus 4.8 analyzes vs your goals → rank by tier×fit → write worklist.md`

The curated doc you actually work from lands in **`matches/<date>.md`**. The machine worklist
(`worklist-<run_id>.md`) and the run plumbing (`browser-queue-`, `archive-`, logs) are disposable and go to
**`data/runs/`**; the scored state, `seen.json` and `applied.json` accumulate in **`data/corpus/`**.

- **Ingestion** (`channels/`) — a registry of job-input channels, each one a `fetch(days, sample) -> list[Job]`
  run inside its own `try/except` so a broken channel costs you that channel and not the run; the per-channel
  counts print in the run summary. Three are built today, plus one documented stub. **`mail`** (`channels/mail.py`, **macOS only**):
  AppleScript reads the raw message source (so anchored URLs survive), Sonnet pulls out the jobs. Grabs
  everything; a light inclusive gate skips obvious non-job mail. Everything that isn't the transport —
  extraction, the alert-vs-correspondence call, the archive list, the dedup key — lives in `channels/common.py`
  and is reused by any mail-shaped channel. **`boards`** (`channels/boards.py`, **any OS, no key, no OAuth**):
  a watchlist of Greenhouse and Lever board tokens you name in `../config/settings.yaml`, asked what is new. One keyless
  HTTP call per board returns the postings *with* their descriptions and, where the employer publishes one,
  the pay range — so these arrive with company, title and pay stated by the API rather than inferred, enter
  the pipeline already `jd_source="full"`, and nothing is fetched twice. Each board is isolated, so a dead
  token costs that company's postings only. Empty lists by default. **`paste`** (`channels/paste.py`,
  **any OS, no key, no OAuth**):
  URLs given on the command line (`--paste URL ...`) or in a file (`--paste-file PATH`, one per line,
  `#` comments allowed). It fetches each JD itself and backfills company/title from it, because a pasted
  URL has neither and `Job.id` would otherwise change identity mid-pipeline. With no URLs it costs
  nothing. **`gmail`** (`channels/gmail_api.py`) is **not built** — a registered, disabled stub that
  *raises* if you enable it, because an empty list would read as a working channel with a quiet inbox.
  Its docstring is the contract for whoever implements it: the return shape, the OAuth scopes, why
  `email_mid` must be the RFC822 `Message-ID`, why `from_correspondence` must come from
  `common._is_correspondence` rather than be re-derived, and which helpers to reuse verbatim — the
  transport is the only missing part. Enable flags: `channels:` in `../config/settings.yaml`.
- **Fetch** (`core/fetch.py`, the shared layer) — domain-routed: ATS public APIs (Greenhouse/Lever/Ashby) · LinkedIn guest
  endpoint (works from your residential IP) · generic JSON-LD → Jina reader · email-snippet fallback.
  Anything it can't fetch is logged and surfaced in the worklist's **"⚠ Couldn't fetch"** block.
- **Semantic dedup** (`dedup.py`) — after the fetch and **before any paid call**, one client req posted
  under two company names collapses to one entry. `seen.json` structurally cannot catch that: its key is
  `company|title`, and the company is what differs. Three gates must all clear (cosine ≥ 0.95, JD 5-gram
  overlap ≥ 0.80, and never two different titles at one employer), because a missed duplicate costs one
  Opus call while a wrong collapse deletes a real job. Every merge is listed under **"⧉ Collapsed
  duplicates"** in the worklist — that section is the only way a bad merge is ever noticed.
- **Precedent** (`precedent.py`, over `core/index.py`) — before the Opus call, the 3 most similar *and
  mutually different* past decisions (score · verdict · one-line why) are retrieved from the corpus and
  injected alongside the JD. Offline, no key. The goal profile always outranks a precedent — some of what
  comes back are the mis-scores `../profile/rubric.md`'s CALIBRATION block was written to correct.
- **Preflight** (`preflight.py`) — runs **before any fetch or paid call** and reports what is missing,
  what it costs *this* run, and the one command that fixes it. The tool degrades quietly — every config
  accessor but `goal_profile()` has a default — so a stranger who seeded the example but wrote no rubric
  gets confident scores against a *fictional* seeker with nothing to say so. Preflight is the single
  source of that judgment, rendered in three places: printed before the run, a `⤷ preflight:` line in
  the summary beside the channel counts, and — for the one CRITICAL case, the rubric still being the
  example's — a banner at the top of the worklist, because the page is read hours after the terminal
  scrolls away. It **warns and continues, never blocks**: a seeded example with no rubric *is* the
  tier-0 demo and must still run.
- **Analyze** (`analyze.py`) — one Opus 4.8 structured-output call per JD vs the goal anchor.
- **Rank** (`rank.py`) — PRIMARY (agency contract, remote/DFW) → SECONDARY (platforms) → OPPORTUNISTIC,
  then by fit → intensity.

## Tuning — three files, split by what changes them

There was one `config.yaml` and 54% of it was a prompt rather than settings. It is now:

- **`../profile/rubric.md`** — the "10/10" fit anchor the analyzer scores against, and the only thing
  sent to Claude. The whole file is the prompt; nothing parses it, so no edit to it can stop the tool
  loading. This is the file worth editing when ranking feels wrong.
- **`../profile/profile.yaml`** — identity: `inbox`, `archive_mailbox`, `applied_sheet`,
  `primary_agencies`, `secondary_platforms`.
- **`../config/settings.yaml`** — operations: `llm.provider`, `models` (`analyze: claude-opus-4-8` for
  judgment, `extract: claude-sonnet-5` for mechanical — downgrade if cost matters), `window_days`,
  `prefilter`, `precedent`, `dedup`, `max_workers`, `liveness`, `channels`.

Secrets are in `../.env` and nowhere else. Accessors: `config.py`.

`JOBSDB_CONFIG_HOME=<dir>` moves both halves onto one directory. `../config/example/` is one — a
complete configuration for a fictional seeker, so
`JOBSDB_CONFIG_HOME=config/example python -m triage --paste <url>` is a real run that touches nothing
of yours. `python -m core.example` copies it into place when you want it as a starting point.

## Recording decisions — `skiplist.md` + the applied sheet

Three sources feed the "already handled, don't surface again" set, all checked **before** any fetch/analysis:

- **`data/corpus/seen.json`** — auto: everything already analyzed, so re-runs only process new jobs.
- **`profile/skiplist.md`** — hand-edited: paste a worklist `id:` here to permanently skip a role you rejected.
- **`data/corpus/applied.json`** — auto: **synced from your applied Google Sheet** via `/sync-applied`, so jobs
  you've already applied to stop re-appearing without you copying ids by hand. It normalizes the sheet's
  messy rows (Claude in-session), keys them the same way the ranker does, and gates low-confidence rows for
  review. `/job-triage` offers to run this first. Full detail: `../docs/operating/triage-applied-sync.md`.

## Archiving processed emails → `jobs-triage`

After a run, the tool writes `data/runs/archive-<date>.txt` — the Message-IDs of emails it fully processed
(every job analyzed). It does **not** move them itself (Apple Mail can't reliably archive Gmail mail — it
dual-labels). Instead, a **Claude session** moves them via the Gmail connector (add `jobs-triage`, remove
`INBOX`).

**To get this in one step:** ask Claude to run triage ("run my triage / archive the list") rather than
running `python -m triage` yourself — then Claude runs the script *and* archives the list in the same
request. Full detail: `../docs/operating/triage-operating.md → Archiving`. Use `--no-archive` to skip the list.

## First run vs steady state

The first run works a **backlog** (every job in the last 3 days) — that can be 100+ jobs and a few minutes
/ a few dollars of Opus. Use `--limit` to sample it if you like. After that, `seen.json` means each run only
analyzes the **new** arrivals, so daily runs are small and cheap.

## One-time setup (mostly done)

- Gmail account in Apple Mail ✅ · osascript automation permission ✅ · `ANTHROPIC_API_KEY` in repo `.env` ✅.
- **Widen the funnel:** set up saved-search / job-alert emails on your boards (LinkedIn searches, YC, a16z,
  ai-jobs, agencies) and reroute Dice (→ your Gmail address) → Gmail, so more jobs flow in.

## Deps

`pip install -r triage/requirements.txt` (already installed in the repo `.venv`).
