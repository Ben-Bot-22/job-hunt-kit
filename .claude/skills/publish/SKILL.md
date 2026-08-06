---
name: publish
description: Re-publish the public job-hunt-kit snapshot from this repo — dry-run the extraction, review what changed, cold-clone check, then push. Use when asked to publish, re-extract, update the public repo, or ship changes to job-hunt-kit.
---

Re-publish `job-hunt-kit` — the public, one-way snapshot of this repo. `scripts/EXTRACTION.md` is the
**first-time seeding** procedure (create repo → private → flip to public) and is done. This skill is the
**repeat** path, which is the one that happens often enough to be worth a checklist.

## Read this before running anything

**The public repo is a snapshot, not a mirror.** Re-running the extraction **overwrites the whole public
tree**. It is not a merge, not an update, and there is no cadence — you publish when a stale snapshot
starts bothering Ben, never because something told you to. Consequences that follow, and that you must
state to Ben if he seems to expect otherwise:

- **An upstream PR merged into `job-hunt-kit` is destroyed by the next publish.** That is why the repo has
  no `CONTRIBUTING.md` (and `core/test_licensing.py` fails if one appears).
- **`config/settings.yaml` is substituted**: the public tree ships `config/example/settings.yaml` in its
  place. So an edit to the real settings file **does not** reach the public repo, and an edit that should
  be public has to be made in the example too. This is the single most common way the public tree goes
  quietly stale — check it every time (see step 2).
- **`profile/`, `matches/`, `applications/`, `data/` never ship.** They are the privacy seam.

## 0 · Required reading — four files, before you form an opinion about anything

**Read these before step 1, every time, and do not ask Ben anything they answer.** They are here
because on 2026-08-06 an agent evaluating a publish told him the open-source product looked incomplete
(it isn't) and asked him to decide how far to scrub his name (already decided, in writing). Both
answers were in files that had not been opened. He is not in the weeds of this repo; the repo is, and
a question it has already answered costs him time and reads as homework not done.

| read | it settles |
|---|---|
| `scripts/publish-denylist.txt` | **What "personal" means here** — surname, email addresses, sheet and label ids, home-directory paths, secret values. Read them there; **do not restate a denied value in this file**, which ships — the guard caught exactly that while this step was being written. The **first name is deliberately not on the list**: the docs and skills are written as instructions about the person who runs the tool, and every publish so far has shipped it that way. Adding to the list is a real change; do not treat the current line as an oversight. |
| `docs/agents/tests.md` | **Why a stranger's clone skips tests, and what clean looks like** (`passed` and `skipped`, never `failed`). A skip is the suite working. Also the rule a new skip must satisfy: say what is missing and how to get it. |
| `config/example/README.md` | **What a new user actually receives** — a complete fictional-seeker configuration (profile, rubric, bullet bank, CV, settings) that seeds itself with `python -m core.example`. The public product is *not* missing a profile; `profile/` is the owner's copy, and the example is the shipped one. |
| the last entry of **§8 · Publish log** at the bottom of this file | what went wrong the previous time |

## 1 · Pre-flight — the suite and the leak test

```bash
.venv/bin/python -m pytest -q
```

Must read `passed` and `skipped`, **never `failed`** — a stranger's fresh clone showing red lines is the
thing the public suite exists to prevent. `scripts/test_leaks.py` runs as part of this and is the one that
matters most: it asserts no tracked path outside the four personal directories carries Ben's identifiers.
**If it goes red, fix the file it names — never the test.**

## 2 · The settings substitution — now a test, not a judgement call

The public tree ships `config/example/settings.yaml` as its `config/settings.yaml`, so anything stated
in the example becomes every new user's default. This step used to read *"diff the two files and decide
which differences are facts about the tool rather than Ben's preferences."* That is judgement, made from
memory, once per publish — and it failed exactly as you would expect: the model ids were duplicated in
both files, Ben moved his to Sonnet on cost on 2026-07-29, the example kept an older Opus, and for two
weeks every new user's default was a model nobody had chosen.

**The fix was structural.** Model ids now live in `core.settings.DEFAULT_MODELS` and any settings file
that stays silent inherits them; `core/test_settings.py` asserts every role has a default and
`core/test_example.py` asserts the example names none. Step 1 covers this.

**What is left for a human, and it is small:** skim the example's *comments* for a claim about the code
that has gone stale — a count, a source list, a runtime. A comment saying "six staffing firms" when there
are seven ships a lie to every reader. **Never quote a measurement you have not just taken.**

**And the standing rule this step now carries:** if you find another value duplicated between the two
files, do not fix the copy — move it into the code and delete the copy, the way `models:` was. A second
source of truth in a file nobody diffs is the failure this whole step exists to catch.

## 3 · Dry-run and read the summary

```bash
.venv/bin/python scripts/extract.py ../job-hunt-kit --dry-run
```

Read the classification summary in full. **An unclassified top-level path aborts the run** — that is the
allowlist working, and the fix is to classify the path deliberately, never to loosen the guard. New skills
ship automatically (a skill is vendored iff its directory name is a key in `skills-lock.json`), so a new
product skill needs no allowlist edit but **should be sanity-checked as "ours" in the summary**.

## 4 · Extract for real, then review the diff as a stranger

```bash
.venv/bin/python scripts/extract.py ../job-hunt-kit
cd ../job-hunt-kit && git diff HEAD~1 --stat && git log --oneline -3
```

Then actually read the diff of anything under `docs/`, `README.md` or `NOTICE`. You are the last reader
before the internet. Two specific things to confirm:

- **`NOTICE` still names every attributed market source.** `core/test_licensing.py` guards this, but the
  reader-facing half is prose and can drift.
- **No absolute `/Users/...` path, inbox address, sheet id or personal filename** appears anywhere in the
  diff. The leak test covers tracked paths; your eyes cover phrasing.

## 5 · The cold-clone check — **the gate, and it runs BEFORE the push**

**This step used to be step 6, after the push, and that was the process bug in this file.** The only
test of what a stranger actually receives ran *after* the irreversible act — a receipt rather than a
gate. On 2026-08-06 the repo's own suite was green while a fresh clone read `2 failed`; it was found
only because the agent improvised a throwaway clone off-script. **Run as written, that publish would
have shipped a broken first impression and then discovered it.**

The public tree is the one thing this repo's own suite never runs against — it ships a substituted
settings file, and it has no `profile/` at all. Both are why this cannot be skipped.

Extract into a **throwaway** clone of the public repo and run its suite there:

```bash
S=$(mktemp -d)
git clone -q ../job-hunt-kit "$S/cold" && .venv/bin/python scripts/extract.py "$S/cold"
cd "$S/cold" && python3 -m venv .venv && .venv/bin/pip install -q -r core/requirements.txt
.venv/bin/python -m pytest -q
```

**Must read `passed` and `skipped`, never `failed`.** `owner_only` and `needs_profile` tests *should*
skip — that is them working. If anything fails: **fix it here in `jobs-db` and re-extract.** Never
patch the public clone; the next extraction overwrites it.

Two more things to confirm while you have a stranger's tree in front of you:

- `python -m core.example` then `pytest -q` again — a seeded clone must also be clean.
- The shipped default run is sane for someone with no configuration. **Do not quote a wall-clock
  number from this file; take the measurement or say nothing.**

## 6 · Push

```bash
cd ../job-hunt-kit && git push
```

**Ask Ben before pushing** — this is the irreversible, outward-facing step, and approval on one publish
does not carry to the next. Do not reach this step with a failing cold clone behind you.

## 7 · Report

Tell Ben: what shipped (a one-line summary of the diff, not a file list), that the cold clone passed
**before** the push, and anything you found in step 2 that had gone stale. If you fixed a drift between
the two settings files, say so — and say whether you moved the value into the code or merely synced it.
Syncing it means it will drift again.

## Rules

- **Never push without asking.** Steps 1–5 are safe and reversible; step 6 is not.
- **Never loosen the allowlist to make a run pass.** An unclassified path is a decision, not an obstacle.
- **Never edit `scripts/EXTRACTION.md` to match a shortcut you took.** If the procedure changed, change it
  deliberately and say why.
- The public repo is written for a reader who is not Ben. `README.md` is the one tracked file whose
  audience is a stranger — read it as one.
- **Do not ask Ben a question step 0's four files answer.** Read them, then state the answer flatly.
- **A duplicated value is a bug, not a chore.** Move it into the code; do not sync the copy.

## 8 · Publish log — append one entry per publish, before you report

Two or three lines: what went wrong, and what changed so it cannot recur. **Step 0 requires reading the
last entry**, so this is the only part of the file that gets better on its own. Newest first.

### 2026-08-06

- **Two tests failed on a fresh clone while the repo's own suite was green**, and the check that would
  have caught it ran *after* the push. One test (added 2026-07-30) called the scorer for real and needed
  the owner's rubric, with no `needs_profile` marker. Another (added 2026-07-31) redirected
  `config.CORPUS_DIR` but not the writer, which was bound at import — so it wrote fixture ids into the
  owner's live `data/corpus/seen.json` **and** created a `data/` directory that broke a third test on a
  clone. Fixed: `triage/store.py` resolves the corpus path per call, so `CORPUS_DIR` is the single knob;
  the marker was added. **The cold-clone check moved from step 6 to step 5, before the push.**
- **The model ids were duplicated between `config/settings.yaml` and the example**, and had drifted
  since 2026-07-29. Fixed structurally: `core.settings.DEFAULT_MODELS` owns them, the example names
  none, two tests enforce it, and the manual diff step is gone.
- **The agent asked Ben two questions the repo had already answered** — whether the open-source product
  was incomplete (it is not; `config/example/` is a complete seeded configuration) and how far to scrub
  his name (`scripts/publish-denylist.txt` defines it and deliberately excludes the first name). Fixed:
  **step 0 exists because of this.** Read the four files, then speak.
