---
name: publish
description: Re-publish the public job-hunt-kit snapshot from this repo — dry-run the extraction, review what changed, push, and cold-clone check. Use when asked to publish, re-extract, update the public repo, or ship changes to job-hunt-kit.
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

## 1 · Pre-flight — the suite and the leak test

```bash
.venv/bin/python -m pytest -q
```

Must read `passed` and `skipped`, **never `failed`** — a stranger's fresh clone showing red lines is the
thing the public suite exists to prevent. `scripts/test_leaks.py` runs as part of this and is the one that
matters most: it asserts no tracked path outside the four personal directories carries Ben's identifiers.
**If it goes red, fix the file it names — never the test.**

## 2 · The settings-substitution check (do not skip)

Diff the two settings files for anything that is a *statement about the tool* rather than a personal
choice — counts, source lists, comments describing behaviour:

```bash
diff config/settings.yaml config/example/settings.yaml
```

Ask of each difference: *is this Ben's preference, or a fact about the code?* Preferences (his channel
enables, his window, his agencies) are supposed to differ. **Facts must match** — a comment saying "six
staffing firms" when there are seven ships a lie to every reader. Fix the example file before publishing.

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

## 5 · Push

```bash
cd ../job-hunt-kit && git push
```

**Ask Ben before pushing** — this is the irreversible, outward-facing step, and approval on one publish
does not carry to the next.

## 6 · Cold-clone check — the only test of what a stranger gets

The public tree ships a settings file this repo's suite has never run against, so this is the only thing
that exercises it:

```bash
cd /tmp && rm -rf jhk-cold && git clone <public-url> jhk-cold && cd jhk-cold
python3 -m venv .venv && .venv/bin/pip install -q -r core/requirements.txt
.venv/bin/python -m pytest -q
```

Expect `passed` and `skipped`, no `failed`. The owner-tuned tests (`owner_only`, `needs_profile`) **should**
skip here — that is them working, not a problem.

Also sanity-check the shipped default run is sane for someone with no configuration. Note that as of
2026-07-24 the `agencies` channel defaults to **seven** live scrapers and takes roughly 200 s wall-clock,
so a stranger's first run is no longer instant — if that ever becomes hostile, the fix is the example
settings, not the code.

## 7 · Report

Tell Ben: what shipped (a one-line summary of the diff, not a file list), whether the cold clone passed,
and anything you found in step 2 that had gone stale. If you fixed an example-settings drift, say so —
that is the recurring failure mode and it is worth him knowing it recurred.

## Rules

- **Never push without asking.** Steps 1–4 are safe and reversible; step 5 is not.
- **Never loosen the allowlist to make a run pass.** An unclassified path is a decision, not an obstacle.
- **Never edit `scripts/EXTRACTION.md` to match a shortcut you took.** If the procedure changed, change it
  deliberately and say why.
- The public repo is written for a reader who is not Ben. `README.md` is the one tracked file whose
  audience is a stranger — read it as one.
