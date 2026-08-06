# The systems map — what this repo *does*, and which part does it

**Read this first, every session.** `CLAUDE.md` imports it for that reason.

This repo is not one tool. It is **eleven systems** that share a corpus, a model path and a config
surface, and the failure this page exists to prevent is an agent answering a question about one system
using the conventions of another — proposing a rubric change to fix a résumé, filing job-search
reasoning in the code knowledge base, or building a second home for something that already has one.

The other two orientation pages answer different questions and neither answers this one:

| page | answers |
|---|---|
| **this page** | *which system am I in, what is its anchor, and **where does a document go?*** |
| `services.md` | *what does it talk to, what does that cost, and how does it fail?* |
| `data-map.md` | *what does it write, and what does losing that cost?* |

Five sections, five different questions: **§1** which system · **§2** what each one is · **§3 where a
document goes, and what never leaves this machine** · **§4** the seams that get confused · **§5** what
to check before building anything.

---

## 1. The whole thing on one screen

Read top-to-bottom: it is the run. **Supply → shortlist → judgement → documents → sent.**

```
        ┌── acquisition ──┐
        │ channels, JD    │   what exists
        │ fetch, scrapers │
        └────────┬────────┘
                 │  Job records
        ┌────────▼────────┐
        │     triage      │   what is worth my attention   ← profile/rubric.md
        └────────┬────────┘
                 │  matches/<date>.md
   ┌─────────────┼─────────────┐
   │             │             │
┌──▼───────┐ ┌───▼──────────┐ ┌▼──────────────┐
│ company  │ │  EVALUATION  │ │  market       │   who are they / should I / what pays
│ research │ │              │ │  reporting    │   ← roles/preferences.md
└──────────┘ └───┬──────────┘ └───────────────┘
                 │  a decision
        ┌────────▼────────┐
        │  cv + letter    │   what I send          ← profile/bullet-bank.md
        └────────┬────────┘
                 │
          applications/  ──▶ /apply-form ──▶ sent
                                  and: applied-sync · setup · publishing
```

**Every system has an anchor** — one hand-tuned file that is the authority for that system, and the
thing to read before answering any question inside it. Anchors are the column that matters:

| # | system | anchor (read this first) | entry point | skill |
|---|---|---|---|---|
| 1 | **acquisition** | `config/settings.yaml → channels:` | `python -m triage` (phase 1) | — |
| 2 | **triage** | **`profile/rubric.md`** | `python -m triage` | `/job-triage` |
| 3 | **company research** | — (no tuned file) | `python -m research "<co>"` | `/research-company` |
| 4 | **market reporting** | `config/settings.yaml → report:` | `python -m research.market` | — |
| 5 | **evaluation** | **`docs/knowledge-base/personal/roles/preferences.md`** | conversation | `/evaluate-role` |
| 6 | **cv generation** | **`profile/bullet-bank.md`** | `cv/scripts/render_cv.py` | `/tailor-cv`, `/tailor-cv-batch` |
| 7 | **cover letters** | `profile/letters/` + `personal/ben-voice.md` | `cv/scripts/make_cover_letter.py` | `/cover-letter` |
| 8 | **applied sync** | `profile/profile.yaml → applied_sheet` | `python -m triage --sync-applied` | `/sync-applied` |
| 9 | **publishing** | `scripts/extract.py` (the allowlist *is* the rule) | `python -m scripts.extract` | `/publish` |
| 10 | **onboarding** | `config/example/` (the fictional seeker, and the test fixture) | `python -m core.setup` · `python -m core.example` | `/setup` |
| 11 | **submission** | `docs/knowledge-base/personal/links.md` | the seeker's browser | `/apply-form` |

Plus **`core/`**, which is not a system — it is the shared floor all eleven stand on.

---

## 2. Each system

### 1 · Acquisition — what exists

Getting postings *in*. Five channels, each in its own `try/except` so a broken one costs that channel
and not the morning.

* **Code** — `triage/channels/` (`paste`, `boards`, `agencies`, `mail`, `gmail` stub) · `core/fetch.py`
  (the five-step JD-fetch chain) · `core/scrapers/` (seven agency scrapers).
* **Why the scrapers are in `core/`** — two consumers. `triage/channels/agencies.py` reads them as job
  input, `research/sources/` registers them as market supply, and a leaf may not import a leaf.
* **Rot risk: high.** Scrapers parse live HTML and **fail by returning zero, not by raising.** The
  per-source counts in the run summary are the only detector. `core/scrapers/__init__.py` is the
  authoritative account of scraper health — read the docstring, never a summary of it.
* **Docs** — `services.md` §3–4, `channels-boards.md`.

### 2 · Triage — what is worth my attention

The daily pipeline: fetch → prefilter (cheap model) → semantic dedup → analyze (judgment model, with
retrieved precedent) → rank → liveness → worklist.

* **Anchor: `profile/rubric.md`.** Prose, injected whole into the analyzer. **No schema and no
  validation, deliberately** — it is a prompt, it is the most-edited file here, and nothing may stop
  the tool booting by being wrong about it.
* **It is authoritative over anything an agent remembers.** Read it before answering *any* judgement
  question about a role. A stale value that loads automatically beats a current value that must be
  fetched — that is a recorded incident, not a hypothetical.
* **Code** — `triage/` (`prefilter`, `dedup`, `analyze`, `precedent`, `rank`, `liveness`, `store`,
  `worklist`).
* **Output** — `data/runs/worklist-<run>.md` (machine) → an agent writes `matches/<date>.md` (curated,
  not reproducible).
* **Docs** — `triage.md`, `tuning.md`, `rubric.md`.

### 3 · Company research — who are these people

A LangGraph agent (`decide`/`act`, three tools, three-pass cap) that pivots its next lookup on what the
last one returned. Answers: direct employer or agency, what else is on their board, and your own
history with them.

* **Code** — `research/agent.py`, `boards.py`, `history.py`, `cache.py`.
* **Output** — `data/research/<slug>.json`, 14-day freshness window, markdown to stdout.
* **The engine has no web search; the agent driving it does.** Every brief ends in `## Open questions`
  and closing them is the caller's job — then `--answer` writes them back.
* **Watch for name collisions.** The board lookup resolves a company name to an ATS slug and can land
  on a different company with the same name. Verify against the employer's own careers URL.

### 4 · Market reporting — what the work pays

Monthly, **never a flag on the daily run.**

* **Code** — `research/market.py`, `report.py`, `snapshots.py`, `retrospective.py`, `research/sources/`
  (BLS, CALC+, Adzuna, JSearch, TheirStack, Himalayas, Remotive).
* **The mirror of acquisition:** `triage/channels/` is *where my jobs come from*, `research/sources/` is
  *where market data comes from*. Keeping those separate is what makes the distinction survive.
* **Writes two dated files into `data/reports/` and nothing else, ever.** The numbers are machine-owned;
  the narrative in `personal/market/market-insights.md` is hand-authored and never overwritten.
* **Docs** — `market-report.md`.

### 5 · Evaluation — should I apply, and why did I decide that

**The newest system, and the only one with no Python.** Its unit of work is a *session with Ben* about
one role, going deeper than a score: what the job actually is, who the customer is, what the interview
demands, what the trade is. It **consumes** triage output and company-research briefs; it is not part of
either.

* **Anchor: `docs/knowledge-base/personal/roles/preferences.md`** — how Ben wants to be *advised*.
* **It holds nothing the rubric can hold.** No rates, tiers, filters or scores. If it needs one, it
  points at `profile/rubric.md`. Breaking that rule recreates the stale-copy failure the rubric section
  of `AGENTS.md` documents.
* **Output** — `docs/knowledge-base/personal/roles/<date>_<company>_<slug>.md`, one per role worked
  through. `profile/skiplist.md` stays the machine index; its one-line reason points here.
* **Private.** Everything under `personal/` is pruned from the public snapshot.

### 6 · CV generation — what I send

Posting → structured brief → tailored render → blind grade → bounded fix loop.

* **Anchor: `profile/bullet-bank.md`** — evidence-backed claims with confidences and a **DO-NOT-CLAIM**
  list. `cv/test_claims.py` enforces the list against the documents that actually get sent.
* **The anchor is PROTECTED: read freely, ask Ben before every write.** It is one of two files that
  speak *as him* (the other is `profile/rubric.md`), and a line in it becomes a claim in a sent
  document. Propose with evidence, apply on his yes — the same shape as the judge below. A lesson from
  a run goes to `personal/tailoring-playbook.md` unprompted; a *claim* waits. See `AGENTS.md` →
  *What an agent may edit*.
* **Code** — `cv/jd_parse.py` (brief) · `cv/scripts/render_cv.py` (the only renderer) · `cv/review_cv.py`
  (the judge) · `cv/run_eval.py` + `eval_set.json` (the harness) · `cv/batch.py` (N jobs at once).
* **The judge grades and never rewrites**, and **the bank outranks the judge** — a program that edits
  its own claims is how a false claim gets in.
* **Batch agents are read-only on the bank.** Proposed bullets are applied once, serially, afterwards;
  N agents appending concurrently corrupts it for every application in the run.
* **Output** — `applications/<date>_<company>_<role>/`.

### 7 · Cover letters — what I say

* **Four files, deliberately separate:** `profile/bullet-bank.md` = the **claims**;
  `personal/tailoring-playbook.md` = the **strategy** (including the binding preferences list);
  `personal/ben-voice.md` = the **voice**; `profile/letters/` = **what was actually sent**, the corpus
  the voice file is a lossy summary of.
* **`cv/scripts/make_cover_letter.py` is the only renderer.** An agent once built a second voice file
  and a second renderer beside these because it designed a home before searching for one.

### 8 · Applied sync — what I have already done

Reads the applied-jobs sheet, normalizes rows, writes `data/corpus/applied.json`, which the ranker
blocks against. `python -m triage --sync-applied rows.json` is the real seam and takes plain JSON.

### 9 · Publishing — the public snapshot

`scripts/extract.py` produces **`job-hunt-kit`**: a one-way, point-in-time copy. **Default-deny
allowlist over top-level paths**; an unclassified path aborts rather than being guessed.

* `PERSONAL` = `profile`, `matches`, `applications`, `data`, `.scratch`.
* `PERSONAL_SUBTREES` = `docs/knowledge-base/personal` — **the one place the seam is deeper than a
  top-level name.** One level up is published; inside is not.
* `is_personal()` is the single definition; `scripts/test_leaks.py` imports it rather than restating it.
* **The settings substitution:** the public tree ships `config/example/settings.yaml` in place of the
  owner's. There should never be a second substitution.

### 10 · Onboarding — the front door for someone with nothing configured

* **`/setup`** is the agent path: résumé → bullet bank, an interview for whatever the résumé can't back,
  then the profile, the rubric and the settings — **with the channel menu shown before anything is
  fetched** (`triage/test_setup_skill.py` enforces that order).
* **`python -m core.setup`** is the same front door for someone with **no agent**: seeds, asks the five
  things with no sensible default, validates what it wrote, and deliberately writes **no rubric**.
* **`python -m core.example`** copies `config/example/` into place and **never overwrites an existing
  file**. That directory is a complete configuration for a fictional seeker, it is the shipped demo,
  **and it is the suite's fixture** — so it cannot rot. `JOBSDB_CONFIG_HOME=<dir>` points both halves of
  the config at one directory, which is how the demo runs without touching `profile/`.

### 11 · Submission — getting it into their system

The last mile, and the only system whose unit of work is **a page of someone else's web form**.
`/apply-form` drives an in-progress application in the seeker's own browser, one page at a time, and
they approve each page before it advances.

* **Anchor: `docs/knowledge-base/personal/links.md`** — the links, handles and the answers to fields the
  CV deliberately refuses to carry. *Years of experience* is the standing example: forbidden on the
  résumé by DO-NOT-CLAIM, required by half the forms, so the number lives there and only there.
* **Its real work is auditing the ATS autofill.** Every applicant tracking system offers "autofill with
  résumé", every one of them mangles it, and **the mangled parse — not the attached PDF — is what a
  recruiter screens on.** One run turned one résumé into five jobs, invented a job title out of a bullet
  fragment, used one job's title as another's employer, and promoted a BBA to an MBA. The last of those
  stops being a parser artifact the moment the page is saved.
* **The tab rule, and it is not negotiable:** the skill opens the group, *the seeker* adds the
  application tab, and the skill **never closes a tab and never navigates theirs**. Closing one tore
  the whole group down twice; navigating to the apply URL started a second draft at step 1 while the
  real one sat at step 3.
* **Never submits, never authenticates, never answers a voluntary disclosure.** Those are the seeker's,
  every time.

### 0 · `core/` — the shared floor

Not a system. `models.py` (the one `Job`) · `fetch.py` · `index.py` (embeddings, MMR retrieval) ·
`cluster.py` · `llm.py` (**the single generation path — the only place a model client is built**) ·
`rates.py` · `scrapers/` · `settings.py` · `rules.py` · `example.py` / `setup.py`.

**The layering rule, enforced by `core/test_layering.py`:** a leaf may import `core/`; a leaf never
imports another leaf; `core/` imports nothing local. **A leaf that needs a sibling's code is telling you
that code belongs in `core/`.**

---

## 3. Where a document goes

**Every document is under `docs/`, and which subfolder it is in says what kind of thing it is. There is
no fifth place** — if you are about to create one, the answer is already below. The full rule lives in
`AGENTS.md` → *Where documentation lives* and `docs/knowledge-base/README.md`; this is the routing table.

| | what goes there | rots? | **ships?** |
|---|---|---|---|
| `docs/operating/` | **how it works now** — this page, `triage.md`, `services.md`, `data-map.md`, `tuning.md`, `rubric.md`, `scheduling.md`, `channels-boards.md`, `market-report.md` | yes, present tense | **yes** |
| `docs/knowledge-base/` | **why it is that way** — dated history, never edited to stay current | no | **yes** |
| `docs/knowledge-base/personal/` | **the owner's decision-support material** — the search, not the code | n/a | **no — pruned** |
| `docs/agents/` | agent conventions: test policy, issue tracker, triage labels | rarely | **yes** |

**The knowledge base is flat and the filename prefix carries the kind.** Four shapes, no numbering, no
acronyms: `log.md` (the running record, newest first — **the default**; most changes need only an entry),
`decision-<slug>.md` (one decision that could have gone another way, with a revisit trigger),
`research-<slug>.md` (one investigation), `plan-<slug>.md` (a build plan, kept for its reasoning).
`core/test_docs_layout.py` fails on a file that names no kind, and on `docs/adr/` or `docs/research/`
coming back.

**`personal/` is the one subfolder the flat rule allows, and it is a privacy seam rather than a topic:**

| | |
|---|---|
| `job-search/` | strategy, positioning, channels, the standing context |
| `market/` | what the work pays, remote-vs-onsite odds, relocation economics |
| `calls/` | interview and screening prep, how to field inbound |
| `roles/` | **the evaluation system** — `preferences.md` plus one file per role worked through |
| `projects/` | side work that shares context with the search |
| `archive/` | closed: past offers, superseded plans, old threads |

### What never reaches the open-source version

`scripts/extract.py` builds the public **`job-hunt-kit`** snapshot as a **default-deny allowlist over
top-level paths** — an unclassified path aborts the publish rather than being guessed.

* **Whole top-level directories that are personal:** `profile/`, `matches/`, `applications/`, `data/`,
  `.scratch/`. Plus `.env` (secret) and `scripts/`, `skills-lock.json` (excluded, not personal).
* **`docs/knowledge-base/personal/` is the single exception to "top-level" — the one place the seam is
  deeper than a directory name.** `docs/` ships whole; that subtree does not. **One level up is
  published; inside is not.**
* **`is_personal()` is the only definition of the rule.** `_copy_ignore()` prunes during the staging
  copy and `scripts/test_leaks.py` **imports the same function** rather than restating it, so the guard
  and the test cannot disagree.

**Why the exception exists, so nobody 'tidies' it away:** the owner's notes *are* documentation and are
read alongside the rest of it. Keeping them in a fifth scattered top-level directory to preserve a tidy
allowlist meant nobody could find them. **One documentation root beat one allowlist rule** — and the
mitigation for the weaker allowlist is `scripts/test_leaks.py`, which asserts in the ordinary suite that
no tracked path outside the personal paths carries the owner's identifiers. **If it goes red, fix the
file it names — never the test.**

### Deciding, in one line each

* Names an inbox address, a Sheet or label id, an absolute `/Users/…` path, a company being talked to,
  comp, or the owner's circumstances → **`personal/`**.
* A file the *tool loads* — `rubric.md`, `profile.yaml`, `bullet-bank.md`, `skiplist.md`, `cv-base.docx`,
  `letters/` → **`profile/`**, not `docs/`. That is configuration, not prose.
* Someone would read it to *use* the tool → **`docs/operating/`**. To learn *why* → **knowledge base**.
* A ticket or spec for work in flight → **`.scratch/<slug>/`**, and **reasoning never goes there** — a
  ticket is written before the work and never corrected after it. When the work ships, the reasoning
  moves to the knowledge base and the ticket can go.

---

## 4. The seams that actually get confused

Four distinctions this repo has already paid for. Each one has a recorded incident behind it.

**Triage vs evaluation.** Triage *ranks the firehose* — machine, per-posting, automatic, anchored on
`rubric.md`. Evaluation *deliberates over one role* — conversational, accumulating, anchored on
`preferences.md`. A preference about how Ben is **screened** (an algo-test gate, a pairing hour) is not
a scoring rule and must not be pushed into the rubric.

**My jobs vs market data.** `triage/channels/` = jobs to apply to. `research/sources/` = what the market
pays. Same shape, different question; the agency scrapers are the only code both use, which is why they
sit in `core/`.

**Configuration vs code.** `profile/` and `config/` are the configuration surface — **an agent may edit
them to change what the tool does.** Everything else is code, and changing behaviour by editing it is a
code change: ticket, test, commit message. `config/settings.schema.json` is the machine-readable list of
every operational setting and its range.

**Documentation vs configuration vs reasoning.** `docs/operating/` = how it works **now**;
`docs/knowledge-base/` = **why**; `personal/` = the owner's, and never published; `profile/` = the files
the tool *loads*. Full routing table in §3 — **there is no fifth place.**

---

## 5. Before you build anything

1. **Grep first.** A repo this documented has usually already answered "where does this live". The
   recorded failure: an agent asked to save cover-letter examples built a second voice file and a second
   renderer, because it designed a home before searching for one.
2. **Check the rules table** in `AGENTS.md` — 19 rules here are enforced by a test. If a rule is in that
   table, do not report it as unenforced; read the test. Regenerate with `python -m core.rules --write`.
3. **Read the anchor of the system you are in**, from §1's table, before answering a judgement question
   inside it.
4. **Never quote a measurement in a rules file.** Counts belong in the code that produces them; a number
   in a prose file is a rot timer. Twice an agent has quoted a stale gloss and had to reverse itself.
5. **After any change to how the tool behaves**, append a dated entry to `docs/knowledge-base/log.md`
   before the session ends. That is an obligation, not a courtesy.

---

## See also

* `services.md` — every external thing, what it costs, how it fails.
* `data-map.md` — every path written, and what losing it costs.
* `AGENTS.md` — the rules, and the enforcement index.
* `docs/knowledge-base/README.md` — where reasoning goes, and the four filename kinds.
