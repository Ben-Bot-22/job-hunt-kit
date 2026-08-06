# jobs-db

## Where things live

Four directories are named for their **content**, and they read top-to-bottom as the run —
**profile → matches → applications**, with `data/` as the memory underneath:

| dir | what it is |
|---|---|
| `profile/` | What you give the tool: `profile.yaml` (identity — inbox, applied sheet, agencies), `rubric.md` (the scoring anchor, prose, injected whole into the analyzer), `bullet-bank.md`, `cv-base.docx`, `skiplist.md`, `letters/`. **Configuration only — prose about the search lives in `docs/knowledge-base/personal/`.** **Tracked in git** — the most-tuned files in the repo. |
| `matches/` | What the tool gives back: one dated apply doc per run (`2026-07-20.md`). |
| `applications/` | What you did about it: one folder per job applied to. **Top level holds only what's live — the jobs on the current apply doc. Everything else moves to `applications/archive/`, one-way.** |
| `data/` | The tool's working memory — `corpus/` (state, `seen.json`, `applied.json`), `runs/` (worklists, archives, browser queues, logs), `research/`, `reports/`. You never edit it. |
| `config/` | `settings.yaml` — how the tool *runs*, shared across tools: provider, models, window, prefilter, dedup, concurrency, channel enables. Plus `example/` — a complete configuration for a fictional job seeker (Robin Doe), which is both the shipped demo and the test fixture. **Tracked in git.** |

The config is split three ways on purpose: **identity** → `profile/profile.yaml`, **the rubric** →
`profile/rubric.md`, **operations** → `config/settings.yaml`, **secrets** → `.env` and nowhere else.
The rubric is markdown rather than a YAML string because it is prose and it is the file edited most —
nothing parses it, so an edit to it can never stop the tool booting. Accessors: `triage/config.py`.

`matches/`, `applications/` and `data/` are gitignored as **generated bulk** — that is not a privacy
rule, and `.gitignore` is not the open-source extraction rule.

Never write output anywhere else. `data/runs/` is disposable; `data/corpus/` is a month of accumulated
judgments and must survive a cleanup of run junk.

**Those directory names are also the privacy seam, and it is a standing condition rather than a
convention.** Extraction into the public repo is a default-deny allowlist over *top-level paths*
(`scripts/extract.py`), with exactly one path named deeper — `docs/knowledge-base/personal/`, the
owner's decision-support material, which lives with the documentation but never ships. The allowlist
only works while the personal paths are exhaustive — so
**`scripts/test_leaks.py` asserts, in the ordinary suite, that no tracked path outside them contains
the owner's identifiers.** Four personal directories is a weaker allowlist than one would be; that
trade was made in favour of daily ergonomics and this test is the mitigation. **If it goes red, fix
the file it names — never the test.** Practically: an inbox address, a Sheet or label id, an absolute
`/Users/...` path or a personal filename belongs in `profile/` and is read from there. That includes
test files, which ship: `triage/test_config.py` reads the identity values out of
`profile/profile.yaml` rather than spelling them, and `core/test_example.py` derives the owner's
surname from it rather than naming the thing it is guarding against.

## What an agent may edit

**`profile/` and `config/` are the configuration surface — an agent may edit them to change what the
tool does. Everything else is code, and changing behaviour by editing it is a code change: it gets a
ticket, a test and a commit message.**

**Two files inside that surface are exceptions, and they are the two that speak *as Ben*:
`profile/bullet-bank.md` and `profile/rubric.md`. An agent READS them freely and ASKS before it writes
— every time, in every workflow.** Everything in the bank becomes a factual claim about Ben in a
document sent to an employer, and the rubric is the priority function; he is the only one who can
approve either. **Propose in chat with the evidence, then apply on his yes** — the same shape as the
grader that reports fixes and never applies them, and as batch agents being read-only on the bank.
A "yes" to *tailor a CV* is not a yes to edit these. The failure this prevents (2026-07-30, Sift): an
agent read `/tailor-cv` step 7's *"feed the knowledge back"* as licence and added a bullet unprompted.
**Strategy and lessons go to `docs/knowledge-base/personal/tailoring-playbook.md` unprompted; a new
claim about Ben goes to the bank only after he says so.** The full routing table is in the bank's
header.

The boundary is a file rather than a convention:
`config/settings.schema.json` is the machine-readable list of every operational setting, its type and
its range, generated from `core/settings.py` by `python -m core.settings`. Read it before editing
`config/settings.yaml`; that file is **validated on load**, so a misspelled key is now an error naming
the key rather than a silent fall back to a default.

`config/example/` is the same surface for someone who has not configured anything yet: a complete
profile, rubric, bullet bank, skiplist and settings for a fictional seeker. `JOBSDB_CONFIG_HOME=<dir>`
points the whole tool — both halves — at one directory like that one, which is how the demo runs
without touching `profile/`. It is **also the test fixture** (`core/test_example.py`,
`triage/test_example.py`), so editing it is editing something the suite runs. `python -m core.example`
copies it into place and never overwrites a file that already exists.

**`profile/rubric.md` is the priority function, and it is authoritative over anything an agent
remembers.** Read it before answering *any* judgement question about a role — should he apply, how does
this score, which of these two is better, is this rate acceptable, is onsite a problem. It is versioned,
reviewed, and injected whole into the scorer, so it is the only copy that is ever current.

**This is stated here because here is a file that loads every session, and the thing it guards against
is a copy that also loads every session.** On 2026-07-27 an agent was asked whether to apply to an
onsite Florida contract at $40–50/hr and said no on two grounds — onsite, and a $115k floor — that the
rubric had already retired in `e4d9a8f` ("open the funnel to onsite/relocation"; "Speed to a signed role
matters (runway)"). The stale copy was in an auto-loaded agent memory; the rubric had not been read once
that session. **A stale value that loads automatically beats a current value that must be fetched**, so
the rule is not "remember the numbers correctly" — it is *never hold the numbers outside this repo, and
open the rubric before judging a role.*

**What gets written *as* the seeker is spread over four files, and they are deliberately separate:**
`bullet-bank.md` holds the **claims** (what is true, with evidence); `docs/knowledge-base/personal/tailoring-playbook.md` holds
the **strategy**, including the binding *"Cover letters — Ben's preferences"* list; `docs/knowledge-base/personal/ben-voice.md`
holds the **voice**; and **`letters/` holds the letters actually sent** — the corpus the voice file is a
lossy summary of, and the thing that keeps it honest as the voice moves. `cover-letter.json` is the
standing letter. `/cover-letter` reads all of them, and `cv/scripts/make_cover_letter.py` is the only
renderer.

**That list is also a warning.** On 2026-07-27 an agent asked to "save cover letter examples somewhere"
built a second voice file and a second renderer beside the existing ones, because it designed a home for
the material before searching for one. The rule that would have prevented it: **when asked where
something should live, grep for it first — a repo this documented has usually already answered.**

The rubric is the exception inside the exception: `profile/rubric.md` has **no schema and no
validation**, deliberately. It is a prompt, it is the file edited most, and nothing may be able to
stop the tool booting by being wrong about it. (`profile/profile.yaml` is unvalidated for a milder
reason — its accessors default to empty, so a missing key costs a blank field, not a wrong number.)

## Code layout

- `core/` — the shared layer: `models.py` (the one `Job`), `fetch.py` (the JD-fetch chain), and
  `index.py` (the retrieval core — corpus → documents → an offline embedded index, MMR retrieval),
  and `cluster.py` (free-text corpus fields grouped into ideas, so an aggregate over them isn't a lie),
  and `llm.py` (**the single generation path** — the one place a model client is constructed, with the
  provider read from `config/settings.yaml`. Never build a second one; that is what this file exists
  to prevent), and `scrapers/` (the seven agency job scrapers, plus the JSON-LD and posting helpers they
  share — here rather than in a leaf because they have two consumers, see below).
  **One requirements file:** every leaf pulls `-r ../core/requirements.txt`, so a leaf that needs
  none of it still installs all of it. That is the deliberate trade — one dependency file to reason
  about beats a per-leaf split.
- Leaf packages: `triage/` (the daily pipeline), `cv/`, `research/` (the company-research agent, plus
  `research/sources/` — **where market data comes from**, the mirror of `triage/channels/`, *where my
  jobs come from*; the market report joins it in stage 5). The original Sheets pipeline was gutted for
  parts in stage 5 and deleted: its three key-gated feeds are `research/sources/`, its six keyless
  agency scrapers are **`core/scrapers/`**, its rate extractor is `core/rates.py`, and everything else
  is in git history.

  **Why the agency scrapers sit in `core/` and the rest of the sources do not.** They are the one part
  of the old pipeline with *two* consumers: `research/sources/` registers them as market supply, and
  `triage/channels/agencies.py` reads them as job input. A leaf may not import another leaf, so code
  wanted by two leaves goes to `core/` — that is the layering rule producing the answer, not an
  exception to it. Everything key-gated or market-only (BLS, CALC+, Adzuna, JSearch, TheirStack,
  Himalayas, Remotive) stays in `research/sources/`, which keeps the *market data* vs *my jobs*
  distinction intact.

  **The agency scrapers are rot-prone** — they parse live HTML and fail by returning zero, not by
  raising; `core/scrapers/__init__.py` says so, and **that docstring is the authoritative account of
  scraper health — read it before concluding anything about a count.** **No counts are quoted here on
  purpose:** this file states rules, and a measurement in a rules file is a rot timer. Twice an agent
  has quoted a stale gloss from this paragraph and had to reverse itself. The docstring is the primary
  source; a summary that can outlive its correction is worse than no summary.

**The market report is a separate command, `python -m research.market`** — monthly, never a flag on
the daily run (11 s of clustering first-party, ~83 s with the keyless baselines). It writes two dated
files into `data/reports/` and **nothing else, ever**: the numbers are machine-owned and the narrative
in `docs/knowledge-base/personal/market/market-insights.md` is human-authored and never overwritten. A claim in that file
cites the numbers file by metric name — the convention, and the reasoning, are in
`docs/operating/market-report.md`. Its config is the `report:` block of `config/settings.yaml`.

**The layering rule, and it is live:** a leaf may import `core/`; a leaf never imports another leaf;
`core/` imports nothing local. A leaf that needs a sibling's code is telling you that code belongs in
`core/`.

There is no exception any more — the one that stood while `core/` was pending (`research/` importing
`triage/fetch.py`) is spent, and `research/` now imports `core.fetch`. The rule is enforced by
`core/test_layering.py`, so widening it fails the suite rather than passing review.

## What is actually enforced

<!-- RULES:BEGIN — generated by `python -m core.rules --write`; edit the tests, not this -->

**20 rules in this repo are enforced by a test.** If a rule is in this table, do not report it as unenforced — read the test. If a rule is *not* here, it is prose and holds only as far as the reader's attention does.

| the rule | enforced by |
|---|---|
| A role routed to the Claude Code CLI bills the subscription: no API key reaches the subprocess. | `core/test_claude_cli.py` |
| Reasoning has one home, `docs/knowledge-base/`; it is flat apart from `personal/`, and the filename prefix carries the kind. | `core/test_docs_layout.py` |
| The shipped example is a fictional seeker, and it is the fixture the suite runs against. | `core/test_example.py` |
| A leaf may import `core/`; a leaf never imports another leaf; `core/` imports nothing local. | `core/test_layering.py` |
| Every attributed source reaches both the registry and `NOTICE`, and no `CONTRIBUTING.md` exists. | `core/test_licensing.py` |
| Workflows are Agent Skills under `.claude/skills/`; no `.claude/commands/` directory exists. | `core/test_portable_workflows.py` |
| The rubric guide still quotes the rubric it explains. | `core/test_rubric_guide.py` |
| `systems.md`, `services.md` and `data-map.md` name every system, workflow, channel, source, scraper, provider and directory the tool actually has. | `core/test_service_map.py` |
| `config/settings.yaml` is schema-validated on load, so a misspelled key names itself instead of silently defaulting. | `core/test_settings.py` |
| There is exactly one generation path — `core/llm.py` is the only place a model client is built or called. | `core/test_single_path.py` |
| `tuning.md` still describes the numbers the code actually uses. | `core/test_tuning.py` |
| The DO-NOT-CLAIM list is enforced against the documents that actually get sent. | `cv/test_claims.py` |
| A PDF render that wrote nothing fails loudly instead of returning the previous one. | `cv/test_render.py` |
| Extraction is a default-deny allowlist: an unclassified path aborts rather than being guessed. | `scripts/test_extract.py` |
| The guards run before the commit, nothing reaches a remote unbidden, and a re-run overwrites rather than merges. | `scripts/test_extraction.py` |
| No tracked path outside the personal directories carries the owner's identifiers. | `scripts/test_leaks.py` |
| No denied personal value reaches the copied output, and the denylist itself never ships. | `scripts/test_scan.py` |
| Nothing leaves the inbox without a look at who sent it — a named human sender is held back. | `triage/test_archive_guard.py` |
| The `gmail` channel stays off — the stub raises rather than returning an empty list that reads as a quiet inbox. | `triage/test_gmail_stub.py` |
| `/setup` shows the channel menu before anything is fetched. | `triage/test_setup_skill.py` |

Regenerate with `python -m core.rules --write`. A test joins this table by declaring a module-level `RULE` string; see `core/rules.py`.

<!-- RULES:END -->

## Where documentation lives — one root, four kinds

**Every document is under `docs/`, and which subfolder it is in says what kind of thing it is.** There
is no fifth place; if you are about to create one, the answer is already below.

| | what goes there | rots? |
|---|---|---|
| `docs/operating/` | **how it works now** — **`systems.md` (the map — read it first)**, the operator's guide (`triage.md`), `tuning.md`, `services.md`, `data-map.md`, `rubric.md`, `scheduling.md`, `channels-boards.md`, `market-report.md` | yes — present tense |
| `docs/knowledge-base/` | **why it is that way** — `log.md` (the running record), `decision-*.md`, `research-*.md`, `plan-*.md`. Flat, prefix carries the kind. Read its README first | no — dated history |
| `docs/knowledge-base/personal/` | **the owner's decision-support context** — job-search strategy, market reasoning, call prep. Read for questions about *the search*, never as documentation of the code | n/a |
| `docs/agents/` | agent conventions — test policy, issue tracker, triage labels | rarely |

`docs/philosophy.md` holds the goals and the reasoning behind every refusal; the README lists the
non-goals and links there, so a new refusal is argued in one file and listed in the other. Résumé
tooling lives in `cv/`. A package `README.md` is a front door — it points at the operating doc and does
not restate it.

**`docs/knowledge-base/personal/` is the privacy seam, and it is the one place the extraction allowlist
is deeper than a top-level name.** `docs/` ships whole; that subtree does not. `scripts/extract.py`
names it in `PERSONAL_SUBTREES`, `is_personal()` is the single definition, `_copy_ignore()` prunes it
from the staging copy, and `scripts/test_leaks.py` imports the same function rather than restating the
rule. **One level up is published; inside is not.** An inbox address, a Sheet id, an absolute
`/Users/...` path or a personal filename goes inside it — or in `profile/`, for the files the tool
reads by path.

**After any change to how the tool behaves, append a dated entry to `docs/knowledge-base/log.md`
before the session ends; that is an obligation, not a courtesy.** `.scratch/` is untracked local
scratch for work in flight, and reasoning never goes there.

## Licence, attribution, and the public snapshot

`LICENSE` is MIT and `NOTICE` carries what a licence doesn't: the five market sources whose terms
require attribution, the per-user-key rule, and the fact that no cached source data is committed.
`research/sources/__init__.py` enforces attribution on each *record*; `NOTICE` is the reader-facing
half, and `core/test_licensing.py` fails when a new attributed source reaches one and not the other.

**Do not add a `CONTRIBUTING.md`** — the same test fails if one appears. The contribution policy is
three sentences in the README (*fork it and make it yours · issues welcome · PRs by exception — new
functionality, tested*), and a dedicated contribution file signals a maintained project taking
submissions, which is the expectation the policy exists to avoid setting. The reason is mechanical:
the public repo is a **one-way, point-in-time snapshot** produced by `scripts/extract.py`, so an
accepted PR must be re-applied by hand here or the next extraction overwrites it. The README is
written for that public reader — it is the one tracked file whose audience is not you.

## This repo's own workflows — all ten are skills

**Every workflow here is a skill, and none is a slash command.** Slash commands are a dead end for
this repo: Claude Code has merged commands into skills, and every other agent's custom-prompt format
is user-level only and explicitly not shared through a repository — so a `.claude/commands/*.md` file
is readable by exactly one client and portable to none. A skill is the same prose under
`.claude/skills/<name>/SKILL.md` with a `name:` in its frontmatter, still invoked as `/<name>`, and it
follows a published open spec that around forty clients read. Converting cost nothing and bought
everything. Do not add a new `.claude/commands/` directory; `core/test_portable_workflows.py` fails if
one appears.

- `/setup` — the front door for a new user: résumé → bullet bank, an interview for whatever the résumé
  can't back, then the profile, the rubric and the settings, with the channel menu shown **before**
  anything is fetched. The seeding half is `python -m core.example`. **`python -m core.setup` is the
  same front door for someone with no agent** — a wizard that seeds, asks the five things with no
  sensible default and validates what it wrote, and deliberately writes *no* rubric.
- `/job-triage` — run the job-triage pipeline end to end. (Named `job-triage`, not `triage`, so it
  doesn't collide with the vendored engineering `triage` skill below.)
- `/research-company` — pre-apply research on a company, a job URL, or the top picks of a run; the
  engine is `research/`, driven as `python -m research`.
- `/sync-applied` — sync the applied-jobs sheet into the dedup cache.
- `/evaluate-role` — work through **one** job in depth and record the decision: what it actually is, fit
  against the bank, the interview loop, the trade. **The evaluation system's process half** — it consumes
  triage's output and `/research-company`'s brief and replaces neither. Its anchor is
  `docs/knowledge-base/personal/roles/preferences.md`, and its output is one dated file per role beside
  it. It **proposes** preference updates and never writes them.
- `/cover-letter` — write a letter, recruiter reply or form answer in the seeker's own voice, anchored to
  letters actually sent. `cv/scripts/make_cover_letter.py` is the only renderer.
- `/tailor-cv` — build a JD-tailored résumé, for **one** posting.
- `/tailor-cv-batch` — build **several** at once, one agent per job, all launched together. This is
  the default for a triage run's picks and `/job-triage` step 9 calls it: every expensive step of
  tailoring is per-job and independent, so N résumés serially is N round-trips for nothing. The
  mechanical half is `cv/batch.py` — the work list off the apply doc, the render-and-tighten loop,
  and the gloss substitutions that have no honest rewrite. **Batch agents are read-only on
  `profile/bullet-bank.md`**: they propose new bullets and the accepted ones are applied once,
  serially, afterwards, because N agents appending to the bank concurrently corrupts it for every
  application in the run.
- `/publish` — re-publish the public `job-hunt-kit` snapshot: pre-flight suite, the settings-substitution
  check, dry-run, review, **cold-clone check, then push (with a gate)** — the gate runs before the
  irreversible step, not after it. `scripts/EXTRACTION.md` remains the
  *first-time seeding* page; this is the repeat path, and it exists because "what does the public repo
  need" was being re-derived every time.

**`.claude/skills/` holds two different kinds of thing, and the difference is machine-readable.** The
nine above are this repo's product. The rest are **vendored** third-party engineering skills, and
`skills-lock.json` names every one of them — *a skill is vendored if and only if its directory name is
a key in that file.* That is the rule the extraction allowlist uses to ship the six and redistribute
none of the twenty.

**`.agents/skills` is a committed symlink to `.claude/skills`.** The Agent Skills spec fixes the file
format and not the path: some clients look in `.claude/skills/`, some in `.agents/skills/`. One
symlink in git is the entire cross-agent gap, and it costs 17 bytes. The support matrix — which agent
is tested, which is merely spec-compliant, and what a reader with no agent at all loses — is in the
README under *Which agent runs the workflows*.

## The suite ships, and part of it skips on a stranger's clone

`pytest -q` on a fresh clone must read **`passed` and `skipped`, never `failed`** — the suite is in the
public snapshot as evidence of how this was built and as a forker's safety net, and fourteen red lines
tells a reader the project is broken. Tests that pin the **owner's** tuned values (rubric text, identity,
`window_days`, `max_workers`) carry `owner_only` or `needs_profile` and skip when `profile/` is absent or
holds the example seeker; tests that state a **rule about the code** (`gmail` stays off — the stub raises)
carry no marker and run everywhere. Never pin a config value that states no rule: it is a photograph,
and it breaks the moment anyone configures anything. Full policy, and the skip-message rule:
`docs/agents/tests.md`.

**`config/settings.yaml` is the one file whose public content differs from this repo's.** The extraction
ships `config/example/settings.yaml` in its place — the owner's operational config has `mail` on (macOS
only), `agencies` on (a ~130 s scrape) and `boards` on with *no companies named*, which as a stranger's
default is a two-minute first run that finds nothing. The example is already the good first run and is
the suite's fixture, so it cannot rot. Consequence, accepted: the public tree holds a settings file this
suite never ran against, and the cold-clone check in `scripts/EXTRACTION.md` step 5 is the only thing
that tests it. See `THE SETTINGS SUBSTITUTION` in `scripts/extract.py`; there should not be a second one.

## Vendored engineering skills

Engineering workflow: **grilling → `/to-spec` → `/to-tickets` → `/implement` → `/code-review`**.

### Issue tracker

Specs and tickets are local markdown under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` at the root and `docs/knowledge-base/`, both created lazily by `/domain-modeling`. See `docs/agents/domain.md`.
