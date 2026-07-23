# Services — everything this wraps, what it costs, and how it fails

This tool talks to about twenty external things. Most of them need no key and no account, one of them
costs money on every run, and several **fail silently** — they return nothing and the run carries on
looking healthy. This page is the whole list in one table per group, and the column that earns the page
is the last one: **what you see when it is absent or broken.**

The rule underneath the whole design, so the table below reads as a pattern rather than a list of
accidents: **the keyless path is the default, and nothing is gated behind "add a key to unlock".** One
key — your model provider's — is required, because the scoring is the tool. Everything else degrades.

**Which absences are loud, and which are quiet.** Read this before your first run, not after a quiet
one:

| loud — you cannot miss it | quiet — you have to look |
|---|---|
| a missing or wrong provider key on the *first* call (`ConfigurationError` naming the variable and the two ways out) | a rotted agency scraper — returns **zero**, logs `motion 0 ⚠` in the run summary and nothing else |
| enabling the `gmail` channel — it **raises**, deliberately, rather than returning an empty list | a missing market-source key — one log line, an empty section, a report that still renders |
| a malformed `config/settings.yaml` — validated on load, the error names the key | a walled JD — the job is still scored, from the title and whatever the listing gave up |
| an unclassified top-level path during extraction — the publish aborts | no embedding weights — precedent silently switches off, one `INFO` line |
| | a **bad** provider key mid-run — every ingest email logs a warning and returns no jobs; you get a short worklist, not an error |

That last row is the one worth remembering. The three model call sites all fail in the direction that
keeps the run going — the prefilter keeps the job, the extractor returns no jobs for that email, the
analyzer returns a `SKIP` stub carrying `analysis_error`. A key that is *present but wrong* therefore
produces a nearly-empty morning rather than a stack trace.

---

## 0. Which of these should I turn on?

The rest of this page answers *"my run looks wrong, why?"*. This section answers the question you have
first: **is this one worth my time?** Nothing here is required — one provider key is the only thing the
tool cannot run without — so treat every row below as opt-in.

The axis that matters is **volume against precision**, and the two ends are genuinely both useful.
`boards` returns a handful of jobs from companies you chose by hand; Adzuna returns thousands from a
market you did not choose. Neither is better; they answer different questions.

### Sources of jobs you might apply to

| source | what you get | volume | key | turn it on when |
|---|---|---|---|---|
| **`paste`** | exactly the postings you hand it | one at a time | none | always — it is the zero-setup way to try the tool, and the only channel that works with nothing configured |
| **`boards`** | only the companies you name, from their real ATS | low — roughly 15–50/week per company | none | you have a target list. **The highest-precision source here**: no noise, but it finds nothing you did not already think of |
| **`agencies`** | contract roles from six staffing firms, **and they usually state a rate** | ~180 per run | none | you would take contract work. The only source that reliably publishes pay, which also makes it the one worth reading for what the market pays *you* |
| **`mail`** | whatever recruiters already send you | your inbox | none | you are on macOS and already get recruiter mail. **The highest-signal source of all** — someone chose to contact you — but macOS-only and it needs Apple Mail configured first |
| **`gmail`** | — | — | — | never, yet. It is a documented stub that raises. `paste` and `boards` cover the same ground keylessly |

**The cost of `agencies` is time, not money:** it scrapes six live sites, so budget ~2 minutes per run,
and it is off in the shipped settings for that reason. Reach it for one run with
`python -m triage --channels agencies`. Inside it, four scrapers are on by default and measured healthy;
**Apex and KORE1 are excluded** because they return 2–3 jobs each and may already be broken — you cannot
tell a rotted scraper from a small board without checking by hand.

### Sources of market data (`python -m research.market`)

These never produce jobs to apply to. They tell you what the work pays and where demand is, which is
what you set your rubric's floor against.

| source | what you get | key | cost | turn it on when |
|---|---|---|---|---|
| **BLS OEWS** | US government wage survey — national and per-metro medians and percentiles for your occupation | none | free | **always.** Keyless, authoritative, and the only *employee salary* anchor here. Capped at 2 requests/run against a 25/day limit |
| **GSA CALC+** | federal contract **ceiling** bill rates, ~281k rows | none | free | **always** — keyless, and the best contract-rate anchor available. Read the caveat: a ceiling is the most a vendor *may* bill, not a wage |
| **Remotive** | remote listings, and the only keyless source that publishes **hourly** rates as text | none | free | you want a contract-rate signal that is not a federal ceiling |
| **Himalayas** | remote **permanent** supply | none | free | you want a sense of how much remote permanent work exists |
| **Adzuna** | broad US aggregate, contract and permanent | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | free tier | you want **breadth** — this is the high-volume, whole-market end of the axis. Note its salary figures are model *predictions*, not posted pay, and are labelled as such |
| **JSearch** | Google-for-Jobs aggregate | `RAPIDAPI_KEY` | free tier, ~200 requests/month | you want a second broad aggregate to check Adzuna against. The quota is small — roughly one request per search term |
| **TheirStack** | agency job search | `THEIRSTACK_KEY` | **paid — one credit per job returned** | rarely. **The only source here that spends money**, capped by `MAX_JOBS`. Leave it off unless you specifically want agency-side data and have a plan for the bill |

**The four keyless market sources are enough for a useful report.** The three keyed ones add breadth,
one of them costs money, and none of them is required: an unset key produces one log line and a labelled
gap in the report, never a failed run.

---

## 1. Model providers — the one key you actually need

Every model call in the repo goes through `core/llm.py`. The vendor is `llm.provider` in
`config/settings.yaml`; the key goes in `.env`; the model ids are `models:` in the same settings file.

| provider | status | key | package | cost |
|---|---|---|---|---|
| `anthropic` | **tested** — every number in this repo was measured on it | `ANTHROPIC_API_KEY` | `langchain-anthropic` | pay-as-you-go. A ~350-job run is one Sonnet screen and one Opus judgment per surviving job |
| `openai` | untested, registered | `OPENAI_API_KEY` | `langchain-openai` | as above, on their pricing |
| `google` | untested, registered | `GOOGLE_API_KEY` | `langchain-google-genai` | as above |
| `ollama` | untested, registered | none — set `llm.base_url` | `langchain-ollama` | free; a local model, so no job data leaves the machine |

**Absent:** `ConfigurationError` naming the provider, its environment variable, and the providers whose
keys you do have. A missing *package* is the same error class with `pip install langchain-openai` in it,
not an `ImportError` from three frames down.

**Wrong or rate-limited:** the SDK retries twice with backoff (`core/llm.py` · `MAX_RETRIES`, which is
the SDK's own default made explicit), then the call site absorbs it — see the quiet row above.

**What does not carry over to the untested tier:** on Anthropic the structured-output request is
byte-identical to the native SDK call it replaced (`core/test_structured_output.py` pins it); elsewhere
it is LangChain's own translation of the same schema, and scores may differ. Extended thinking is
Anthropic-only and is **dropped with a warning** rather than forwarded into a `TypeError`.

**No tracing is wired up.** `langsmith` arrives as a transitive dependency and `core/llm.py` sets
`LANGSMITH_TRACING=false` at import (with `setdefault`, so an explicit export still wins). It would
otherwise ship your résumé, your inbox-derived job data and your goal profile to a third party by
default.

---

## 2. Retrieval — the service people assume this needs and it does not

| what | key | account | network | cost |
|---|---|---|---|---|
| `fastembed` + `BAAI/bge-small-en-v1.5` (ONNX, CPU, no torch) | none | none | **once**, to download ~64 MB of weights | free |

This is the half of the tool that would obviously be a hosted vector database in someone else's design,
and it is a 20 MB JSON file and a local ONNX model. The weights land in `~/.cache/fastembed/`
(`core/index.py` · `DEFAULT_CACHE_DIR` — fastembed's own default is `$TMPDIR`, which macOS empties).
After the download there is no network and no key on any retrieval path, ever.

Measured here: 1,226 documents, **~38 s to build the index cold**, ~13 ms per retrieval (300 ms on the
first call, which is the model load).

**Absent (no weights, no network):** retrieval degrades and the run continues. `triage/precedent.py`
logs *"no index … — scoring without precedent"* or *"could not open the index … — scoring without
precedent"* and the analyzer scores against the rubric alone. This is quiet by design — memory is an
enhancement, never a blocker — and the way you notice is that `precedent:` stops appearing in the
worklist's focus blocks. Tests that need the real model skip cleanly when it is not cached
(`core/index.py` · `model_is_cached`).

---

## 3. Input channels — where *your* jobs come from

`triage/channels/`. Each channel runs inside its own `try/except`, so a broken one costs you that
channel and not the morning. Enables live under `channels:` in `config/settings.yaml`; `--channels
mail,agencies` overrides the set for one run without editing anything.

| channel | what it talks to | key | OS | default | absent / broken |
|---|---|---|---|---|---|
| `paste` | nothing — URLs on the command line or in a file | none | any | on | nothing to break; a URL that won't fetch degrades like any other |
| `boards` | Greenhouse `boards-api.greenhouse.io` and Lever `api.lever.co`, public read endpoints, one request per board with the JD included | none | any | on, **with empty lists** — it reports `boards 0` until you name boards | a dead board 404s and costs you that board; **there is no HTML here to rot** |
| `agencies` | six staffing firms' own boards, **scraped** (`core/scrapers/`) | none | any | **off** | **silent zero — see below** |
| `mail` | Apple Mail, via `osascript` | none | **macOS only** | on in the shipped settings | not on macOS: turn it off. First run raises an Automation permission dialog **a scheduled job cannot answer** |
| `gmail` | nothing yet | Google OAuth | any | **not built** | **raises** if you enable it, on purpose: an empty list would look exactly like a working channel with a quiet inbox |

**`agencies` is the rot-prone one and it is the reason this page exists.** The six scrapers parse live
HTML — sitemaps, embedded JSON, JSON-LD — and a site that restructures does not raise, it stops
matching. **The per-source counts in the run summary are the only detector**, and the run summary prints
them for exactly that reason:

    agencies 45 (insightglobal 30, teksystems 15, motion 0 ⚠)

Last measured live, **2026-07-22**: Insight Global 87 · TEKsystems 78 · Motion 27 · Mondo 15 · **Apex 3 ·
KORE1 2**. The last two are either genuinely small boards or already partly rotted, and nothing in the
code can tell you which — which is why they are excluded from the shipped `sources:` list. A source that
normally returns 40 and returns 0 is a bug report, not an empty market. Nothing in the test suite can
catch this: pinning a 2026-07 HTML fixture would only prove the parser still parses last year's page.

It is also the only channel that returns **contract** work, which is why it survives being the fragile
one. It is off by default because it is a 130 s+ scrape in front of a run.

---

## 4. JD fetching — the chain behind every job link

`core/fetch.py`, in order, per URL. All keyless.

| step | what it talks to | fails to |
|---|---|---|
| known ATS public API | `boards-api.greenhouse.io`, `api.lever.co`, `api.ashbyhq.com` | the next step |
| LinkedIn guest endpoint | `linkedin.com/jobs-guest/...` — no login, works from a residential IP | the next step |
| generic: JSON-LD | the posting's own page, parsed for `schema.org/JobPosting` | the next step |
| generic: reader API | `r.jina.ai` — a public reader that renders JS and sometimes gets past a bot wall | the email snippet |
| email snippet | nothing | `Job.fetch_error`, and a line in the worklist's couldn't-fetch block |

**Nothing is silently dropped**: every failure is recorded on the job and surfaced. Bot-wall
interstitials come back HTTP 200 with real length, so they are detected by signature
(`_BLOCK_MARKERS`) and treated as a failure rather than fed to the analyzer as garbage — those jobs go
into the browser queue instead.

**Liveness** (`triage/liveness.py`) re-fetches the top ranked jobs at the end of a run and reports
`OPEN` / `CLOSED` / `UNKNOWN`. The third state is load-bearing: an aggregator that never marks a listing
closed is reported as `UNKNOWN`, not as `OPEN`.

---

## 5. Market sources — where *market* data comes from

`research/sources/`, read by `python -m research.market`. The mirror of §3: that is *my jobs*, this is
*the market*. All of these are absent-tolerant — an unset key is one log line and an empty list, never a
failed run.

| source | what it gives | key | cost | absent / broken |
|---|---|---|---|---|
| **GSA CALC+** | federal contract **ceiling** bill rates — 281,084 labor-category rows, re-indexed nightly | none | free | an **undocumented internal API**: nothing promises it stays. Degrades to no bands with a log line, and the external half renders as a labelled gap |
| **BLS OEWS** | permanent salary wages, national and per metro | none | free — public v1 API, **25 queries/day per IP** | a quota breach comes back HTTP 200 with `REQUEST_NOT_PROCESSED`, detected on the payload rather than the status code. `MAX_QUERIES` caps a run at 2 requests, 8% of the allowance |
| **Himalayas** | remote **permanent** supply — a keyless JSON feed, 20 rows a page | none | free | empty list, logged. Note its API ignores every filter it accepts except `offset` |
| **Remotive** | the only keyless source found that posts **hourly** contract rates as text | none | free | empty list, logged. Its terms forbid republishing rows as listings, which is why it is here and not a channel |
| **Adzuna** | broad US aggregate, contract and permanent as two queries | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | free tier | empty list, logged. **Attribution required** — see below. Its salary figures are model *predictions*, labelled as such |
| **JSearch** (RapidAPI) | Google-for-Jobs aggregate | `RAPIDAPI_KEY` | free tier ~200 requests/month, ~1 request per search term | empty list, logged |
| **TheirStack** | agency job search | `THEIRSTACK_KEY` | **paid — one credit per job *returned***, capped by `MAX_JOBS` | empty list, logged. The only source here that spends money |
| **the six agency scrapers** | contract supply, shared with the `agencies` channel | none | free | **silent zero — §3 again.** Same code, same detector |

**Attribution is enforced in code, not left to a template.** `research/sources/__init__.py` stamps an
attribution line onto every record from a source whose terms require one, and `fetch_all` **drops** a
job that arrives without it. `NOTICE` is the reader-facing half, and `core/test_licensing.py` fails when
a new attributed source reaches one and not the other.

**The external half degrades to a labelled gap, never to a shorter report.** A stranger with no network
reads that the baseline is missing and costs nothing to have — not a corpus-only document they would
mistake for complete.

---

## 6. The two things a human agent drives

Neither is Python, and both are steps in a workflow rather than in the pipeline. This is the tier-3
degradation the README's support matrix names.

| what | used by | needs | absent |
|---|---|---|---|
| **Google Sheets / Drive** | `/sync-applied` — reads the applied-jobs sheet named in `profile/profile.yaml → applied_sheet`, normalizes its rows, writes `data/corpus/applied.json` | a Drive connector in your agent. **Read-only; nothing ever writes back to Google** | no connector → paste a CSV export instead, or hand-edit `profile/skiplist.md`. `python -m triage --sync-applied rows.json` is the real seam and takes plain JSON |
| **Chrome** | `/job-triage` step 2 — pulls the walled JDs in `browser-queue-<date>.json` through your own logged-in browser | a browser-control tool in your agent | `--no-browser` is the supported flag. Those jobs are scored from the title and the listing, or dropped |

**Mail archiving** is the third one and it is prose, not code: the `/job-triage` workflow moves
processed mail using the list the run wrote to `data/runs/archive-<date>.txt`. Without an agent, the run
is unaffected — it reads the mailbox, scores everything, writes the worklist — but **processed mail
stays in your inbox** and the next run reads it again. Dedup means you get no duplicate output; you get
an inbox that never empties.

---

## 7. Every way to run it

Costs are measured on this machine against a ~350-job window and a 1,300-record corpus.

| command | cost | writes | needs |
|---|---|---|---|
| `python -m triage` | ~9–10 min, network-bound. One Sonnet screen + one Opus judgment per surviving job | `data/corpus/state-<run>.json`, `data/corpus/index.json`, `data/runs/*` | a provider key. Channels per config |
| `python -m triage --channels agencies` | the scrape (130 s+) plus scoring | as above | none beyond the provider key — exhaustive, so *only* that channel runs |
| `python -m triage --paste <url> …` | one job's fetch + two model calls | as above | a provider key. No inbox, no OS constraint |
| `python -m triage --merge` | re-ranks with browser-fetched JDs; re-analyzes only what changed | rewrites the run's worklist and state file | phase 1's files still in `data/runs/` |
| `python -m triage --sync-applied rows.json` | seconds, no model call | `data/corpus/applied.json` | normalized rows — the `/sync-applied` workflow produces them |
| `python -m research "<company>"` | 2–3 network lookups + a planner call; **free and instant** on a cached brief (14 days) | `data/research/<slug>.json`; markdown to stdout | a provider key. No corpus, no setup — the one thing that works on a fresh clone |
| `python -m research.market` | **~83 s** with the keyless baselines | `data/reports/market-numbers-<date>.json` + `market-report-<date>.md`, **and nothing else, ever** | nothing. Keys only add Adzuna/JSearch/TheirStack |
| `python -m research.market --offline` | **~11 s**, first-party only, no network at all | as above | nothing |
| `python -m research.market --supply` | minutes — third-party feed counts. **Untested at this scale** | as above | keys, for the gated feeds |
| `python cv/scripts/render_cv.py --base … --plan … --out …` | seconds; `--pdf` shells out to LibreOffice | a `.docx` (and a `.pdf`) under `applications/` | the base CV in `profile/`. LibreOffice only for `--pdf` |
| `python -m core.setup` | instant, offline. Asks name, inbox, provider, channels, board tokens — nothing else | as below, plus your answers edited into `profile/profile.yaml` and `config/settings.yaml`, which it then validates | nothing. `--yes` and the `JOBSDB_SETUP_*` variables make it unattended. **Writes no rubric** — that is `/setup`'s job |
| `python -m core.example` | instant | seeds `profile/` and `config/`, **never overwriting an existing file** | nothing |
| `python -m core.settings` | instant | regenerates `config/settings.schema.json` | nothing |
| `JOBSDB_CONFIG_HOME=config/example python -m triage --paste <url>` | a real run against the fictional seeker | still writes to the real `data/` — see `data-map.md` §4 | a provider key |
| `pytest -q` | ~6 s, 636 tests | nothing | **offline, no key** |

The five workflows — `/setup`, `/job-triage`, `/research-company`, `/sync-applied`, `/tailor-cv` — sit
on top of those commands and are prose an agent reads. `docs/operating/workflows.md` maps each one's
assumptions onto yours.

---

## See also

* `docs/operating/data-map.md` — every path these commands write, and what losing it costs.
* `docs/operating/tuning.md` — the throttles, caps and page limits that decide how hard each of these
  services is hit.
* `docs/operating/market-report.md` — the monthly report, and how to cite its numbers.
* `docs/operating/scheduling.md` — running the unattended half on a timer, and where unattended stops.
