# Job Triage System — Scope & Build Plan

> **Historical (superseded).** Written before stage 5 · 01 deleted the `jobsdb/` Sheets pipeline,
> `main.py` and the root `config.yaml`. Paths and the two-tool framing below describe the repo as
> it was; the current layout is in `CLAUDE.md` → Code layout.


> **Status: BUILT ✅ (2026-07-04).** This is the design record / rationale. The tool is implemented and
> live-validated. **To operate or modify it, read [`triage-operating.md`](triage-operating.md)** — the
> as-built operator's guide (how to run, file map, gotchas, tuning). This plan explains *why*; that doc
> explains *how it actually works now*.

---

## 0. What this is, in one paragraph

A **second, separate tool** — built in the `jobs-db` repo but standing apart from it — that **reads Ben's
Gmail, follows the job links inside, scrapes each full job description, analyzes it against Ben's goals
with the Claude API (Opus 4.8), and writes a ranked markdown worklist**: the top 3–5 to focus on, then
everything else ranked with a one-line reason, plus fit / role / red-flags / resume-keywords for each. Ben
runs it manually when he sits down to job-hunt, picks how many to apply to, and tailors his resume from
the output.

**It is an add-on, not a change to jobs-db.** jobs-db was the *market-research engine* (API/agency scrapers
→ Google Sheet, daily). This is *tool #2*: turn the daily flood of inbound job email into a short, ranked,
readable list so JD-sifting stops eating Ben's most valuable asset — time — and the hours he needs for
Reazy. **Wide capture in, best-few out.** Design premise: ADHD + very busy + can't afford to miss
fast-closing roles + can't afford to read every JD by hand, and **rework is the enemy** — the analysis
must be good enough to trust, or it costs more time than it saves.

---

## 1. The goal Ben is optimizing for (the ranker's "10/10" anchor) — CONFIRMED

Everything the analyzer scores is measured against this. Ranking accuracy is paramount (bad ranking → rework
→ wasted time), so this is exact:

**The ideal role:**
- **Remote**, worked from **OKC — no relocation.** Remote is the whole point.
- **Contract** (or contract-to-hire) — a **2–3 year bridge**, not a permanent career move. Contract starts
  fastest and fits the bridge. Perm is welcome but ranks lower.
- **~$120k/yr equivalent** target; **$50/hr hard floor** (below → skip).
- **Low intensity (1–3):** scoped, sustainable, clock-out work. **Non-negotiable protected time: weekends,
  jiujitsu, Neon Buffalo (band), and Reazy.** No on-call, no "always-on," no 50%-travel.
- **In-lane skills:** React · TypeScript/JS · Node · Python/FastAPI · GCP (Cloud Run / Firebase / GCS) ·
  Docker / CI-CD; **applied ML + LLM apps** (Anthropic API, prompt engineering, structured outputs).
- **Tailorable, treat as in-lane:** roles keyworded **AWS / cloud** — Ben's core is GCP but he sells into
  AWS/cloud roles; do **not** downrank these. (Lives in the analysis prompt.)
- **Bonus edge — AI-native roles** ("ships with Claude Code/Cursor," "last 90 days," video + GitHub apply,
  "rebuilding around AI," MCP/agentic/evals): Ben's strongest archetype — the screen runs on what he's best
  at and skips the ATS. A plus, not a requirement.

**Downranks (NOT skips — still shown, ranked lower):**
- **Forward Deployed Engineer / heavy-travel / onsite-embed** → demote hard (travel kills the bridge). This
  is what's demoted — **not** startups in general.
- **Intensity 4–5** (startup-velocity / on-call / crunch) → downrank. **Remote-contract startups are fine**
  with sane hours; a16z/YC in-person founding roles are not (Ben won't move).
- **Onsite/hybrid requiring relocation** → downrank. **Remote-first always.** DFW-hybrid (~3hr from OKC) is
  tolerable/opportunistic for the right contract, but below any remote option.
- **Permanent** → logged, ranks below an equivalent contract.

**Hard filters (SKIP — before spending an analysis call):** non-US · posted contract rate clearly
**< $50/hr** · primary stack not Ben's (**.NET/Java-primary, native-mobile-only**) · requires
**active/reinstatable clearance**.

---

## 2. Architecture — two tools in one repo (the key design decision)

Ben's ask: *build in this repo, but as a separate module; make it easy to understand and manage; jobs-db
stays untouched.* The design that delivers that is **two self-contained tools side by side, with a hard seam
between them.**

```
jobs-db/                     ← the repo (unchanged name)
├── jobsdb/                  ← TOOL 1: market-research engine — FROZEN, do not edit for triage
├── main.py  · config.yaml   ← TOOL 1's entry point + config (unchanged)
│
├── triage/                  ← TOOL 2: the new daily triage tool (all new work lives here)
│   ├── README.md            ← what it is + how to run (read-me-first)
│   ├── __main__.py          ← entry: `python -m triage`
│   ├── config.yaml          ← triage's OWN config: goal anchor, tiers, sources, models
│   ├── ingest/              ← Apple Mail read (AppleScript) + LLM link/source extraction
│   ├── fetch/               ← domain-routed JD fetch chain (§6)
│   ├── analyze.py           ← Opus 4.8 structured analysis (§8)
│   ├── rank.py              ← tiers × fit sort (§2 model)
│   └── worklist.py          ← markdown renderer (§9)
├── requirements.txt         ← shared (or triage/requirements.txt if deps diverge)
├── profile/                 ← as-built: skiplist.md, bullet-bank.md, cv-base.docx, notes/ (Ben's inputs)
├── matches/                 ← as-built: the curated apply doc, <date>.md, one per run
└── data/                    ← as-built: corpus/ (seen.json, applied.json, state-*), runs/ (worklist-*, logs)
```

**Four rules that keep it easy to manage:**
1. **No cross-imports.** `triage/` does **not** import from `jobsdb/` and vice-versa. Each tool is reasoned
   about in isolation. *(As-built this generalized into the repo-wide layering rule in `CLAUDE.md`: a leaf
   package may import `core/`, never another leaf.)* (Triage defines its own tiny `Job`/analysis types — copying a 30-line dataclass is
   cheaper than coupling two tools, and the analysis shape differs anyway.) → *resolves Q4: standalone.*
2. **Each tool owns its entry point, config, data, and README.** Mental model is one sentence: *"jobsdb/ =
   research engine (Sheet); triage/ = daily triage (markdown)."*
3. **jobs-db is frozen by this work.** You never edit Tool 1 to change Tool 2's behavior.
4. **Deleting `triage/` removes Tool 2 with zero trace in Tool 1.** That clean seam is also the
   open-source split line if ever wanted (not a priority — capability first).

*Language:* Python, matching the repo (AppleScript is called via `subprocess`).

---

## 3. Pipeline (the flow when Ben runs `python -m triage`)

```
Apple Mail (Gmail acct)                              ┌── skiplist.md (Ben's applied/rejected ids)
   │  AppleScript, last N days, GRAB EVERYTHING       │   seen.json   (already-analyzed, internal)
   ▼                                                  ▼
[1] read all recent emails ─▶ [2] LLM EXTRACT ─▶ [3] DEDUP / skip-check ──(new only)──▶
       (no sender allowlist)     (cheap model:      (skip BEFORE any fetch or Opus call)
                                  links + source
                                  → structured doc)
   ──▶ [4] fetch JD per link ──▶ [5] Opus 4.8 ANALYZE ──▶ [6] rank ──▶ [7] write worklist.md
        (domain-routed chain,     (structured: fit, tier,   (tiers ×   (top picks + ranked rest +
         §6; log failures for      role, red flags, resume    fit)      rejected + COULDN'T-FETCH list)
         manual follow-up)         keywords, meets-goals)
```

Manual, synchronous (run → read the result in minutes), read-only against the inbox.

---

## 4. Ingestion — Apple Mail (Gmail), grab everything, LLM-extract the jobs

**Read via Apple Mail.app + AppleScript (`osascript`),** the pattern Ben already proved in
`~/dev/freelance-automation` (`src/imap.js`) — chosen there precisely because **Proton Bridge's
programmatic IMAP was broken on macOS Tahoe** and Apple Mail authenticated fine via the system. For Gmail
it's even simpler (no bridge — Apple Mail handles Google's OAuth when you add the account). `source of m`
gives the full raw message. **Gmail only** for v1; reroute Dice (→ your Gmail address) into Gmail, tagged
low-value.

**No sender/subject allowlist — grab everything (resolves Q2).** Per Ben: *"we already said grab
everything."* Pull all emails in the window and let an **LLM extractor** find the jobs. Two-model split
(see §8):

- **[2] Extraction pass — cheap model (Sonnet 5).** For each email, extract **every job link + the source
  metadata visible in the email** (company, title snippet, sender/platform, posted-ish date, inline JD
  text) into a **structured doc** (`data/extracted-<date>.json`) that drives scraping. This replaces
  brittle regex/sender rules with judgment: it finds LinkedIn/Dice/ATS/recruiter links wherever they sit,
  and captures the email's own JD text as the guaranteed fallback (§6). *(Optional cost-saver: a trivial
  heuristic can skip obvious non-mail — receipts, newsletters — but bias to inclusion; missing a role is
  worse than one wasted cheap call.)*

---

## 5. Dedup + skip-before-eval — two layers

Skipping happens **before** any fetch or Opus call, so no processing is spent on handled roles.

1. **`seen.json` (internal, auto):** every job id already analyzed → don't re-analyze across runs.
2. **`skiplist.md` (Ben's, hand-editable):** a **separate markdown doc** of ids Ben **applied to** or
   **rejected** — never surface again. He adds an id when he applies or rejects; the worklist prints each
   id so he can paste it in one move.

**The id (ids aren't always available):** real ATS/LinkedIn id when present; otherwise a **composite**
normalized `company|title|city` (same idea as jobs-db's `dedupe_key_from`).

---

## 6. Fetching the JD behind each link — the domain-routed chain (RESEARCHED)

No single scraper works; the robust + **$0** answer is a per-URL fallback chain, because the two biggest
buckets (ATS boards, LinkedIn) each have a free, unauthenticated path. Route by hostname:

1. **Known ATS host → public JSON API** (free, high reliability — verified live):
   Greenhouse `boards-api.greenhouse.io/v1/boards/{b}/jobs/{id}?content=true` · Lever
   `api.lever.co/v0/postings/{co}/{id}` · Ashby `api.ashbyhq.com/posting-api/job-board/{org}` · Workday
   `cxs` endpoint · YC workatastartup JSON.
2. **LinkedIn → guest endpoint from Ben's residential Mac IP:**
   `linkedin.com/jobs-guest/jobs/api/jobPosting/{id}`. Free, full JD, **no login.** Use **`python-jobspy`**
   (`linkedin_fetch_description=True`) so selector-rot is a `pip -U`. Jitter + backoff, ~a-handful-per-run
   (429 near ~10/IP), **cache hard.** Works *because* it's your residential IP — datacenter IPs and generic
   reader APIs get 999/authwalled.
3. **Unknown host → generic:** `httpx` → JSON-LD `JobPosting` → **trafilatura** → **Jina Reader**
   (`r.jina.ai/{url}`, 10M free tokens). Covers career sites, Dice.
4. **Bot-walled (Indeed, Wellfound) → don't fight it in v1.** One cheap try; on 403 → degrade.
5. **Unfetched → the email's own JD text** (from §4's extraction), tagged `jd_source = email_snippet`.

**Log every failure for manual follow-up (Ben's request).** Anything that can't be fetched (bot-walled,
429, dead endpoint) is recorded — link + host + reason — and surfaced in a dedicated **"⚠ Couldn't fetch —
investigate manually"** block in the worklist (and `data/runs/fetch-failures-<date>.log`), so Ben can open those
by hand. **LinkedIn verdict:** PARTIAL — headless, no login, free, but flaky (residential-IP dependent);
reliable-tier upgrade later = Bright Data LinkedIn Jobs API (5k free/mo). **Legal:** logged-off public
scraping is favorable-but-unsettled (hiQ 2022; Meta/X v. Bright Data 2024); **never scrape logged-in
LinkedIn.** Not legal advice.

---

## 7. Where to look (best sources for Ben's goals) — feed them all into Gmail

**Philosophy: wide scrape → best rise to the top → prune sources empirically** (don't pre-rule anything).
The unifier: **set up saved-search / job-alert emails on each board so everything lands in Gmail** — one
tool then triages all of it; no per-board scraper to build.

- **PRIMARY (agency contract):** Motion, TEKsystems, Insight Global, Apex, KORE1, **Scion**; direct
  recruiter threads. + Dice alerts (rerouted, low-value).
- **SECONDARY (platforms):** Braintrust (**skip for v1** — Ben hasn't signed up), Gun.io (matcher, tracked
  manually), Upwork/Toptal.
- **OPPORTUNISTIC (remote AI-native / startup / perm):** LinkedIn saved-search alerts (`"AI-native"`,
  `Claude Code`, `Cursor`, `founding engineer`, `applied AI engineer`, `full stack remote`); YC
  workatastartup; a16z portfolio jobs; topstartups.io; trueup.io; ai-jobs.net; aitmpl.com; startup.jobs;
  Remotive; remotevibecodingjobs.com. **Screen for remote + sane hours** (FDE demoted for travel).

We don't permanently rule anything out — the ranker + Ben's `applied` data tell us what converts; prune the
duds over time.

---

## 8. The two LLM roles — cheap extractor + Opus 4.8 judge

Deliberately split so cost goes to mechanical work and **judgment goes to the best model** (Ben: *"I prefer
Opus — this needs to be very good; rework eats my most valuable asset"*).

| Role | Model | Why |
|---|---|---|
| **Extract** links + source data from emails (§4) | **Sonnet 5** (`claude-sonnet-5`) | Mechanical, high-volume, low-judgment — cheap + reliable structured extraction. |
| **Analyze + rank** each scraped JD | **Opus 4.8** (`claude-opus-4-8`), **effort `high`**, adaptive thinking | This is the judgment that must be trustworthy. High effort = best ranking, least rework. |

**Analysis = one structured-output call per new JD** (`messages.parse`), the anchor (§1) + tiers (§2) +
AWS-tailorable rule baked into the prompt. Returns:
`id · title · company · link · rate · cadence · employment_type · is_agency · jd_source` ·
`tier` · `fit_score` (0–100) · `intensity` (1–5) · `verdict` · **`why`** (one line) · **`role_summary`** ·
**`meets_goals`** · **`red_flags`** · **`resume_keywords`** *(later: `resume_bullets`)*.

**Prompt caching:** the anchor/rubric system prompt is identical for every JD in a run — cache it so only
each JD's text is billed full-price. (Caches only if the prefix clears Opus 4.8's ~4k-token minimum; pad the
rubric or accept a no-op if short.)

---

## 9. Output — `worklist-YYYY-MM-DD.md` (markdown, not a spreadsheet)

> As-built: the machine worklist lands in `data/runs/`; the curated doc Ben works from is `matches/<date>.md`.
> See `triage-operating.md`.

Ben reads text to pick the top 3–5; the doc is the product.

```markdown
# Job Worklist — 2026-07-04   (28 new · 6 skipped pre-eval · 4 couldn't-fetch)

## ▶ Focus today (top 3–5 — put real effort here)
### 1. Senior React Contractor @ Acme  ·  PRIMARY · fit 91 · intensity 2 · ⏱ 1d
- **why:** remote contract, in-lane React/Node, calm, ~$115/hr — near-ideal
- **role:** build/maintain their customer dashboard; 6-mo contract, extendable
- **meets goals:** ✅ remote ✅ contract ✅ rate ✅ intensity — misses: none
- **red flags:** none
- **tailor with:** React, TypeScript, TanStack Query, Cloud Run, CI/CD
- **apply:** <link>   ·   **id:** `acme|senior-react-contractor|remote`

## PRIMARY — agency contract, remote/DFW   ## SECONDARY   ## OPPORTUNISTIC

## ⤵ Ranked rest (work down as time allows — one line each)
- [PRIMARY · 74 · int 3] Full-Stack Contract @ Foo — remote, rate unposted — <link> · `id`

## ✕ Rejected / skipped (why)
- [SKIP] FDE @ Palantir — 50% travel (bridge-killer)

## ⚠ Couldn't fetch — investigate manually
- LinkedIn 429 (rate-limited): "Sr Frontend @ Bar" — <link>
- Indeed (bot-walled): "React Dev @ Baz" — <link>   ·   (only the email snippet was available)
```

Grouped by tier (mirrors daily attention); focus roles fully explained; the long tail one-line-ranked;
rejects with reasons; **and the couldn't-fetch list so nothing silently disappears.**

---

## 10. Anthropic's primitives vs. a framework like LangChain (for Ben's education)

**The primitives are a ladder from simple → complex. Climb only as high as the task forces you to.**

| Rung | Primitive | What it's for |
|---|---|---|
| 1 | **Single Messages API call** | One request → one answer: classify, extract, summarize, judge. *(This project's analysis step.)* |
| 2 | **Structured outputs** (`messages.parse`) | Force the answer into a validated schema. |
| 3 | **Prompt caching** | Cheap repeated context (identical system prompt across calls). |
| 4 | **Batch API** | Async, 50% off, for high-volume non-latency-sensitive jobs. |
| 5 | **Tool use (function calling)** | The model calls *your* functions mid-reasoning; you run the loop. For workflows that must act/fetch to proceed. |
| 6 | **Server-side tools** | Anthropic-hosted web search / web fetch / code execution. |
| 7 | **Agent SDK / agentic loop** | The model drives its *own* multi-step trajectory over tools you host. For open-ended tasks. |
| 8 | **Managed Agents** | Anthropic hosts the whole agent loop **+ a cloud container**. Stateful, long-running, hosted. |

**Where does something like LangChain (or LlamaIndex / LangGraph / Haystack) fit?** These are
**orchestration frameworks that sit *on top of* the SDK** — you still call Claude underneath. They earn
their keep when the **orchestration itself is the hard part**, specifically:
- **Provider-agnostic abstraction** — one interface across Anthropic / OpenAI / local models, to swap
  freely.
- **Complex multi-step chains or graphs** — many LLM calls wired with branching, looping, conditional
  routing, and shared state (**LangGraph** targets stateful agent graphs specifically).
- **RAG pipelines** — document loaders, chunking, embeddings, vector stores, retrievers: lots of prebuilt
  plumbing you'd rather not hand-write.
- **Breadth of prebuilt integrations** — hundreds of off-the-shelf loaders / tools / vector-store
  connectors.

**The cost of a framework:** a layer of indirection between you and the API — leaky abstractions, version
churn, harder debugging, and often fighting the framework to do what the SDK does in three lines. A common
arc is: reach for LangChain to move fast early, then drop it for the raw SDK once flows stabilize and you
want control.

**Rule of thumb:** use a **framework when the flow is the hard part** (retrieval, many components,
provider-swapping, stateful agent graphs); call the **SDK directly when the model call is the hard part and
the surrounding flow is simple/deterministic.**

**For this project:** one Opus judgment call per JD wrapped in plain deterministic Python — the
orchestration is a `for` loop. LangChain would add indirection for zero benefit. **Direct Anthropic SDK +
structured outputs is correct.** If Ben later builds RAG over his past applications, a multi-step agentic
research loop, or wants provider-swapping, *then* revisit LangGraph/LangChain.

### Which primitives this project uses — and why the rest are skipped

| Feature | Fit | Why |
|---|---|---|
| **Structured outputs** | ✅ backbone | Validated analysis object per JD. |
| **Prompt caching** | ✅ cheap win | Shared rubric prefix cached across the run's JDs. |
| **Opus 4.8, effort high** | ✅ the judge | Ranking must be trustworthy; rework is the cost of being wrong. |
| **Sonnet 5** | ✅ the extractor | Cheap mechanical link/source extraction. |
| **Batch API** | ⚠️ optional | You trigger it and want to read the result — a **synchronous** run (seconds–minutes) beats Batch's up-to-1h latency. Use Batch only if you'd rather run-and-return-later for 50% off. |
| **Agent SDK / tool-use loop** (core) | ❌ skip | The pipeline is deterministic, not open-ended. An agent adds latency, cost, nondeterminism, babysitting. |
| **Managed Agents / scheduled deployments** | ❌ architecturally wrong | Run in Anthropic's cloud — can't touch your Mac's Apple Mail or fetch LinkedIn from your residential IP. **This tool must run locally.** |
| **MCP Gmail connector** | ❌ skip | Chat-product only; wrapping mail-reading in MCP adds an auth system + fragility for nothing. |
| **Memory tool / stores** | ❌ skip | `skiplist.md` + `seen.json` are plain files you edit — simpler and what you asked for. |
| **Server `web_fetch`** | ❌ skip | Fetches from Anthropic's datacenter IPs → same LinkedIn 999-wall; the local chain covers the rest cheaper. |
| **Code execution / computer use** | ❌ skip | Sandbox has no internet; computer-use is the fragile logged-in path research says to avoid. |

**The decisive fact:** this tool is **mandatory-local** (Apple Mail + residential-IP LinkedIn). That rules
out every hosted-agent surface. Good fit for Anthropic's *primitives*, not its *hosted orchestration*.

---

## 11. Build sequence (v1 cut)

1. **Skeleton + easy path.** AppleScript Gmail read (grab everything) → Sonnet 5 extraction → dedup
   (`seen.json` + `skiplist.md`) → fetch chain for **ATS + JSON-LD + email-snippet fallback** (skip
   LinkedIn hardening for step 1) → **Opus 4.8** analysis → ranked `worklist.md` with the couldn't-fetch
   list. Triages recruiter emails + ATS links end-to-end.
2. **LinkedIn fetch** via `python-jobspy` guest endpoint (residential IP, backoff, cache). Biggest bucket.
3. **Polish** analysis + worklist (red flags, resume keywords, tier tuning against real output).

---

## 12. Deferred / future expansions (parking lot)

Captured so nothing is lost; none are in v1.

- **`resume_bullets` generation** — Files API + PDF input (feed Ben's CV) so the analyzer drafts tailored
  bullets per role. Ben's stated optional expansion.
- **Braintrust source** — add once Ben signs up (self-apply listings, SECONDARY).
- **Scion + other agency adapters** — if a source proves high-yield.
- **Bright Data LinkedIn Jobs API** (5k free/mo) — reliable-tier upgrade if the free guest endpoint flakes.
- **Hard-case JD-fetch fallback agent** — a small bounded tool-use agent for unknown sites the deterministic
  chain misses (the one genuinely open-ended sub-task; email-snippet degradation covers it meanwhile).
- **Batch API** — switch on for 50% cost if Ben prefers run-and-return-later over synchronous.
- **Proton inbox** — second Apple-Mail account if meaningful job mail lands there.
- **Gmail API migration** — only if this ever needs to run headless/cloud (loses the local happy path).
- **Cross-reference jobs-db's Sheet** — optionally fold Tool 1's scored rows into the same worklist.
- **AI-native board seeds** (aitmpl "Claude Code jobs", etc.) as opportunistic sources.

---

## 13. Decisions (all resolved)

Repo = in `jobs-db`, `triage/` module, standalone / no cross-imports · grab-everything + LLM extraction,
no allowlist · manual trigger, synchronous · window = **3 days** (`--days` to override) · **Opus 4.8
(effort high)** for analysis, **Sonnet 5** for extraction — prefer smarter models, scope is affordable,
downgrade later if needed · Braintrust skipped for v1 · couldn't-fetch links logged for manual follow-up.
Priority: **work out of the box** (smarter models are likelier to add value than to need rework).

---

## 14. Implementation stages, tests, and where Ben is needed

**Execution model:** Claude builds and self-tests autonomously (env is unblocked — Apple Mail + Gmail
configured, automation permission granted, API key present, residential IP). **Ben comes in at the end**
to do the final acceptance test + set up the inbound job-alert emails.

### Stages (each independently testable)
| # | Stage | Builds | Claude can test now? |
|---|---|---|---|
| 0 | **Scaffold** | `triage/` package, `config.yaml` (anchor/tiers/sources/models/window), `requirements.txt`, `README.md`, `data/` + `skiplist.md`, `models.py` (own types) | ✅ `python -m triage --help` |
| 1 | **JD fetch chain** (`fetch/`) | domain router → ATS APIs · LinkedIn guest · JSON-LD→readability→Jina · email-snippet fallback · failure log | ✅ live, from Ben's IP |
| 2 | **Analysis** (`analyze.py`) | Opus 4.8 structured output vs the anchor; rubric prompt-cached | ✅ live API |
| 3 | **Ingestion** (`ingest/`) | AppleScript read (grab everything, 3d) + Sonnet 5 extraction → structured doc | ✅ live (real inbox) |
| 4 | **Dedup + rank + worklist** (`rank.py`, `worklist.py`, `__main__.py`) | seen.json + skiplist skip-before-eval · composite id · tiers×fit sort · markdown incl. couldn't-fetch block · full wiring | ✅ end-to-end |
| 5 | **Polish** | tune prompt/tiers vs real output; finalize README | partial (needs Ben's eye) |

### Acceptance tests (Ben runs at the end)
1. **Fetch:** sample URLs across ATS / LinkedIn / generic → full JD returned, or logged in "couldn't-fetch"
   (never silently dropped).
2. **Analysis sanity:** a remote React contract JD → PRIMARY / high fit; a .NET-primary onsite JD →
   SKIP/low; an FDE "50% travel" role → downranked with a travel red flag.
3. **Ingestion:** last-3-day Gmail read yields job links; a recruiter email with an inline JD (like
   `profile/notes/email-jobs/college-board.md`) is captured even with no scrapeable link.
4. **Dedup:** re-run skips already-seen; an id added to `skiplist.md` disappears next run.
5. **Output:** `worklist.md` has all four sections (focus / ranked rest / rejected / couldn't-fetch), with
   ids present to paste into `skiplist.md`.
6. **Out-of-box:** a fresh `python -m triage` produces a usable worklist with no manual fiddling.

### Where Ben is needed (and only here)
- **Already done:** Gmail in Apple Mail ✅ · osascript automation permission ✅ · `ANTHROPIC_API_KEY` ✅.
- **Ben, one-time — inbound alerts:** set up saved-search / job-alert emails on the §7 boards (LinkedIn
  searches, YC, a16z, ai-jobs, agencies) and **reroute Dice (→ your Gmail address) → Gmail**, so jobs flow in.
  *(The tool works on whatever's already in the inbox before this — alerts just widen the funnel.)*
- **Ben, at the end — acceptance:** run `python -m triage`, read the worklist, sanity-check the top picks +
  ranking against your judgment, mark one applied + one rejected in `skiplist.md`, confirm they drop out.
