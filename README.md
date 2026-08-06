# 💼🔪 job-hunt-kit

**A job-search pipeline that runs on your machine: it fetches postings, scores each one against a
rubric you wrote, and hands you a ranked worklist.** It finds, scores and ranks. It does not apply
for you.

[Why I built it](#why-i-built-it) · [What it does](#what-it-does) · [Quick start](#quick-start) ·
[What you need](#what-each-feature-needs) · [Where things go](#where-things-go) ·
[How it works](#how-it-works) · [Design decisions](#design-decisions) ·
[Limitations](#limitations-and-non-goals) · [Project status](#project-status)

Here is a real run of the shipped demo config — a fictional seeker, against live job sources:

```
▶ Focus today (top picks — put real effort here)

1. Software Developer @ Mondo · PRIMARY · STRONG_FIT · fit 83 · 🟢 OPEN
   why:        Remote W2 contract at $61-66/hr, both halves (Nest API + React),
               clean 4-7yr bar — an agency full-stack contract right in lane.
   red flags:  7am EST start · contract-to-extend, no stated conversion · backend-heavy (60-80%)
   precedent:  Northwind Analytics STRONG_FIT bar — clears the same gates, but is a contract,
               so ranked slightly below an equivalent permanent role.
   tailor with: NestJS, Node.js, TypeScript, React, Redux, REST APIs, CI/CD
```

The `precedent` line is the part worth noticing. The score is not a keyword match: each posting is
judged against `profile/rubric.md` — prose you write, in your own words — and the scorer pulls in how
it judged similar jobs before. It tells you *why*, so you can correct the rubric instead of arguing
with a number.

## Why I built it

I needed to job search but found the process overwhelming. First I made a module to do market
research by gathering jobs from multiple sources. Then I built the triage, and finally the résumé
tailoring.

I run Claude Code inside the repo and let it use the tools for me.

This is built for a full-stack developer search, but it can be used for anything.

## What it does

Four commands, each standalone and none of them needing the others — plus the parts that need a
coding agent, below.

### 1 · Daily triage → a ranked worklist

Pulls postings from whichever sources you enable, screens the obvious noise cheaply, scores what
survives against your rubric, and writes a ranked markdown file you work from.

```bash
python -m triage                       # your enabled sources
python -m triage --paste <job-url>     # score one posting — nothing to configure
python -m triage --channels agencies   # contract roles with rates (~2 min scrape)
```

A run reports what it did:

```
✓ PHASE 1 done — wrote data/runs/worklist-2026-07-23.md
  86 analyzed · 0 skipped pre-eval · 0 couldn't-fetch
  ⤷ channels: agencies 178 (insightglobal 87, teksystems 72, motion 5, mondo 14)
  ⤷ semantic dedup: 6 duplicate posting(s) collapsed before scoring
  ⤷ prefilter: 78 screened out cheaply, 8 sent to claude-sonnet-5 (90% of judgment calls saved)
  ⤷ liveness: 3 open · 5 CLOSED (of 8 ranked)
```

Two of those lines earn their keep. **Liveness** checked the ranked jobs and found five already
closed, before you spent an evening on them. And the **per-source counts** are how you catch a broken
scraper: these read live web pages, so when a site changes layout the scraper returns nothing instead
of failing. A source showing `0 ⚠` is broken — not a quiet day.

### 2 · Market research → what the work pays, before you apply anywhere

**A good place to start.** It answers the two questions that should shape your whole search: what
does this work actually pay, and where is the demand? Use the answers to set the salary floor and
target roles in your rubric, so everything downstream is calibrated against real numbers.

```bash
python -m research.market
```

It needs no API key and works on a fresh clone:

```
GSA CALC+ — federal contract ceiling rates
  full stack developer: $124.22/hr median of 101 · p25 $88.87 · p75 $147.21 · p90 $168.73
  ^ CEILING — an upper bound on a bill rate, not a wage

BLS OEWS — employee wages
  Software Developers (National):  $135,980/yr median · p25 $50.58/hr · p90 $103.21/hr
  Software Developers (Chicago):   $134,380/yr median
```

Every figure carries its sample size and what it is *not*. Once you have run triage a few times, it
adds a second half measured over your own scored postings — what your actual sources are offering,
as against the broad market.

### 3 · Résumé tailoring → a CV targeted at one job

Give it a job description; it writes a tailored `.docx` and `.pdf` into a per-application folder,
with the JD and a record of which bullets it chose and why.

It can only use bullets from your **bullet bank** — the things you have actually done, written down
once. That is the mechanical reason it cannot invent experience for you.

**A second model grades the result.** It reads the rendered PDF alongside the job's brief and scores it
the way a screener would, flagging bullets that are vague or written in marketing register. Its findings
feed a fix loop that is capped at two passes.

**It grades, but it never rewrites.** Fixes may only re-select from bullets already in your bank, because
a grader that edits its own claims is how a false claim reaches an employer.

**This is the only feature that needs a coding agent.** `/tailor-cv` reads the JD, proposes changes,
waits for your approval, then renders.

### 4 · Company research → who is actually hiring

Before you spend effort on an application: is this the employer or an agency, what else are they
hiring for, and have you dealt with them before.

```bash
python -m research "TEKsystems"
```

### 5 · With a coding agent — the parts that are a conversation

Two things here are not commands, because the work is judgement rather than mechanism.

- **`/evaluate-role`** works through a single job in depth: what it actually is, what the interview will
  demand, and what the trade is. Triage ranks the firehose; this provides more information for a decision.
- **`/cover-letter`** writes a letter, a recruiter reply or a form answer in your own voice, using a voice
  file you tune rather than a template.

### Experimental: `/apply-form`

The problem is that companies force you to upload your resume but their autofill is garbage most of the
time, which means manual work that you have to do over and over (full time roles). This helps fill in the
blanks from the resume, but it is slow and error prone because it uses Claude in the browser, which is
experimental.

**WARNING:** Claude got my Apple developer account terminated (with no appeal process). I got it back but
it caused much stress and it took two weeks. I notified Anthropic about this issue and there was no
response, no support and no public warning. You can read about it on
[my blog](https://www.reazy.pro/blog/150000-apple-developers-terminated-2-8-reinstated-heres-how-i-beat-the-odds).
Basically, companies have incentives to stop fraud (and browser automation looks like fraud), so be
careful where you use it.

## Quick start

```bash
git clone <this-repo> && cd job-hunt-kit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m research.market       # no key needed — see what the work pays
cp .env.example .env            # add your provider key; scoring is an LLM call
python -m triage                # a real run against the shipped demo config
```

**You can run all of that before configuring anything.** The repo ships a complete configuration for
a job seeker who does not exist, so the first run is a real run — it just scores against *their*
standards rather than yours. Before fetching anything, it tells you what it is about to do, and what
is missing:

```
Scoring new job postings against your rubric (profile/rubric.md).
  looking at   boards · paste  (7-day window)
  scoring      a cheap claude-sonnet-5 screen first, then claude-sonnet-5 judges what survives
  writing      a ranked worklist under data/runs/

PREFLIGHT — what is missing before this run, and how to fix it:
  ⚠ CRITICAL: the scoring rubric is still the example seeker's — every fit score is calibrated
    to a fictional person, not to you  → run /setup, or edit profile/rubric.md
```

Then make it yours: `/setup` in a coding agent, or `python -m core.setup` in a terminal. The rubric
is the file that matters — it decides every score, it is prose, and nothing parses it, so you cannot
break the tool by getting it wrong.

## What each feature needs

Everything needs a provider API key. Beyond that, each feature needs one or two files of yours, and
they all live in `profile/`.

| to run | you need | where it goes |
|---|---|---|
| **anything** | an API key from Anthropic, OpenAI or Google (or a local Ollama model, no key) | `.env` — copy `.env.example` |
| **triage** | a rubric: what a good job looks like, in your own words | `profile/rubric.md` |
| | job sources: which boards or agencies to watch | `config/settings.yaml` |
| **market research** | nothing else — it works on a fresh clone, no key | — |
| | *optional:* free keys for more market data (Adzuna, JSearch) | `.env` |
| **CV tailoring** | your résumé as a `.docx` — it becomes the base document | `profile/cv-base.docx` |
| | a bullet bank: everything you have done, written once, with evidence | `profile/bullet-bank.md` |
| | a coding agent — the one feature with no command-line path | — |
| **company research** | nothing else | — |

And what each one writes:

| feature | you get | where |
|---|---|---|
| **triage** | a ranked worklist, every posting scored with its reasoning | `data/runs/worklist-<date>.md` |
| **triage** via `/job-triage` | a checkbox apply list, liveness-checked | `matches/<date>.md` |
| **market research** | a written report, plus the raw numbers as JSON | `data/reports/` |
| **CV tailoring** | tailored `.docx` + `.pdf`, the JD, and the bullet choices | `applications/<date>_<company>_<role>/` |
| **company research** | a cached research note, reused later | `data/research/` |

**`/setup` builds all of these with you** — hand it your résumé and it writes the bullet bank, asks
about anything the résumé cannot support, and writes the rubric. Without an agent,
`python -m core.setup` does everything except the rubric, and says so.

Every example of these files is in [`config/example/`](config/example/) — a complete configuration
for a job seeker who does not exist. Read them before writing your own.

## Where things go

Top to bottom, this is the run: **profile → matches → applications**, with `data/` as the memory.

```
profile/                      you: rubric.md, bullet-bank.md, profile.yaml, cv-base.docx
    │                         your most-tuned files — keep them in git
    ▼
data/                         the tool's memory — you never edit this
    ├── runs/                 each run's raw worklist and logs        (disposable)
    ├── corpus/               every judgment ever made                (keep — this is the memory)
    └── reports/              market reports
    ▼
matches/                      the daily apply list — a checkbox doc you work from
    └── 2026-07-23.md
    ▼
applications/                 one folder per job you applied to
    └── 2026-07-23_acme_senior-fullstack/
        ├── jd.txt            the posting, saved
        ├── plan.json         which bullets were chosen, and why
        ├── robin_doe_cv.docx  ← your tailored résumé
        ├── robin_doe_cv.pdf   ← what you send
        └── README.md         the record of what you sent and when
```

`matches/`, `applications/` and `data/` are gitignored — generated bulk. Everything the tool writes
is markdown, JSON or Office files: no database, nothing you cannot read or delete.

The code is `core/` (one `Job` model, one LLM client, the retrieval index), plus `triage/`, `cv/` and
`research/`. Config is three files on purpose: `profile/profile.yaml` (identity),
`profile/rubric.md` (the scoring standard, prose) and `config/settings.yaml` (how the tool runs).

## How it works

```
sources → dedupe → cheap screen → LLM scores vs. your rubric → rank → worklist
              │                             ▲
              └──── retrieval over every past decision ────┘
```

Jobs arrive through **channels**, each isolated so a broken one costs you that channel, not the run:

| channel | needs | OS | default |
|---|---|---|---|
| `paste` | nothing — a URL on the command line | any | on |
| `boards` | Greenhouse/Lever companies you name (seven ship by default) | any | on |
| `agencies` | nothing — six staffing firms' boards, scraped. **The best source of mid-level remote contract work with rates stated** | any | off — a ~2 min scrape; run it with `--channels agencies` |
| `mail` | Apple Mail, already configured | macOS only | off |
| `gmail` | OAuth | any | **not built** — a documented stub that raises if enabled |

Scoring is two-stage: a cheap model screens out obvious misses, and only survivors reach the
expensive one. Every scored decision is embedded into a local index, so later runs retrieve how you
judged similar postings and feed that back into the prompt. **The embedder runs on your machine and
needs no key** — only the scoring is an API call.

The vendor is a config value, not a code change. One module builds every model client:

| provider | status | key |
|---|---|---|
| `anthropic` | **tested** — everything here was measured on it | `ANTHROPIC_API_KEY` |
| `openai` · `google` | untested, should work | `OPENAI_API_KEY` · `GOOGLE_API_KEY` |
| `ollama` | untested — a local model, so no job data leaves your machine | none |

## Which agent runs the workflows

Nine workflows ship as [Agent Skills](https://agentskills.dev) — markdown under `.claude/skills/`,
an open format many clients read. This is how I use it: I open the repo in Claude Code and let it drive.

**They are meant to be edited.** The Python is general; these nine files are not — they were written as
one person's runbook and still read that way: a named user, a Gmail label, a Google Sheet, a Mac. They
are the most fork-shaped thing in the repo — prose, no schema, nothing parses them, and changing one
cannot break the pipeline underneath. Rewriting the second person out of them and putting your own rules
in is not a modification of the tool; it is how the tool is used. Read the skill you care about
(`.claude/skills/<name>/SKILL.md`) and swap its assumptions for yours.

| skill | what it does |
|---|---|
| `/setup` | reads your résumé into a bullet bank, asks about what it can't back, writes your profile and rubric |
| `/job-triage` | runs the pipeline end to end, then researches, tailors and drafts for the top picks |
| `/research-company` | pre-apply research on a company, a URL, or a run's top picks |
| `/evaluate-role` | works through one job in depth and records the decision |
| `/tailor-cv` | builds the JD-tailored résumé, with an approval gate |
| `/tailor-cv-batch` | builds several at once, one agent per job, for a whole run's picks |
| `/cover-letter` | a letter, reply or form answer in your own voice |
| `/apply-form` | experimental — drives an application in your own browser (read the warning above) |
| `/sync-applied` | syncs your applied-jobs sheet so applied roles never resurface |

Tiered by what has actually been run: **Claude Code** is tested — every workflow here was built and
run in it. Other skill-reading clients (Cursor, opencode) should work, but nothing here has been run
in one. **With no agent at all** the Python is still the whole tool; you lose the browser fetch for
login-walled postings, and the mail-archiving step that lives in the `/job-triage` skill.

## Design decisions

The parts that were deliberate, and what each traded away.

- **The rubric is prose, not configuration.** Nothing parses `profile/rubric.md` — it goes into the
  prompt whole. A schema would make it validated and shareable; it would also let a typo stop the tool
  booting, in the file you edit most.
- **Failure is loud where it would otherwise be silent.** Agency scrapers break by returning zero, so
  every run prints per-source counts. The `gmail` channel *raises* rather than returning `[]`, because
  an empty list is indistinguishable from a quiet inbox.
- **Cheap model first.** A Sonnet prefilter screens before Opus scores — measured at 90% of Opus calls
  saved on a real run — and duplicate postings are collapsed *before* scoring, not after.
- **Retrieval instead of fine-tuning.** Past judgments are embedded locally and retrieved into the
  prompt. Offline, no key, no training loop, and the memory is a JSON file you can read.
- **Preflight before any paid call.** A missing key, an unwritten rubric, no job source — each named
  up front with its cost and its fix, before the tool spends anything.
- **The demo config is also the test fixture.** A demo nothing exercises is a demo that rots, and the
  day it rots is a stranger's first five minutes.

## Limitations and non-goals

- **It does not auto-apply.** It finds, scores and tailors; a human reads the worklist and applies.
  A deliberate limit, not a missing feature.
- **`mail` is macOS-only** (it drives Apple Mail via AppleScript) and **`gmail` is not built**.
  `paste`, `boards` and `agencies` cover every OS with no key and no OAuth.
- **The agency scrapers rot.** They parse live HTML and fail by returning zero. The per-source counts
  are the only detector, and fixing one is expected maintenance.
- **Only the Anthropic path is tested.** The others are registered and should work; nothing here was
  measured on them.
- **No tracing is wired up.** `langsmith` arrives as a transitive dependency and stays dormant — it
  would ship your résumé, prompts and inbox-derived data unredacted by default.
- **No web UI, no hosted service, no installer.** It runs on your machine, on your key.
- **Not career advice, and no guarantee of outcomes.** The rubric is yours; the tool applies the
  standard you wrote and shows its reasoning so you can argue with it.

## Further reading

Everything below is in `docs/`. Start with the first two.

| | |
|---|---|
| [`operating/systems.md`](docs/operating/systems.md) | **the map — what this repo does, which part does it, and what each part's anchor file is. Start here** |
| [`operating/triage.md`](docs/operating/triage.md) | the daily run, end to end |
| [`operating/rubric.md`](docs/operating/rubric.md) | how to write a rubric that scores well — the highest-leverage file you own |
| [`operating/services.md`](docs/operating/services.md) | **every source and service: what it gives you, what it costs, whether it is worth enabling** |
| [`operating/channels-boards.md`](docs/operating/channels-boards.md) | picking company boards to watch |
| [`operating/market-report.md`](docs/operating/market-report.md) | the market report, and how to cite its numbers |
| [`operating/scheduling.md`](docs/operating/scheduling.md) | running it unattended, and where that stops |
| [`operating/data-map.md`](docs/operating/data-map.md) | every file written, and what is safe to delete |
| [`operating/tuning.md`](docs/operating/tuning.md) | every tuned number, what it trades, how you'd know it's wrong |
| [`philosophy.md`](docs/philosophy.md) | the goals, and the reasoning behind every refusal above |
| [`agents/tests.md`](docs/agents/tests.md) | what the test suite is for, and why some of it skips on your clone |
| [`knowledge-base/`](docs/knowledge-base/) | everything learned and every reason — the running log, the decisions, and the spikes behind the stack choices |

## Secrets

`.env`, gitignored, and nowhere else. A provider key is required for scoring. The market sources are
keyless except Adzuna, JSearch and TheirStack, which return nothing (with a log line) when their key
is unset rather than failing the run.

## Project status

**Built for my own job search and published as a reference implementation.** Please customize with
your own data to get the most out of it. **Fork it and make it yours.**

Issues are welcome and I read them. This repo is a point-in-time snapshot of a private working repo —
nothing syncs the two — so pull requests are the exception rather than the rule.

## Licence

MIT — see [`LICENSE`](LICENSE). `NOTICE` carries the attribution required by the market-data sources
this wraps, none of whose data is committed to this repo.
