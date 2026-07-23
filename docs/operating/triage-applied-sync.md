# Applied-sheet sync — dedup the worklist against what Ben already applied to

> Why a job Ben already applied to no longer shows up in the worklist, and how the sync that makes that
> happen works. Companion to `triage-operating.md` (the run) and `triage-plan.md` (the design).

## The problem it solves
Ben logs every application in a Google Sheet. The triage ranker, run separately, kept re-surfacing jobs he'd
already applied to (e.g. NationMind on 7/6, applied 6/30) because nothing connected the sheet to the ranker's
dedup. This closes that loop **without** Ben hand-copying ids into `skiplist.md`.

## How dedup already worked (the seam we plugged into)
The ranker blocks a candidate **before** any fetch/analysis if its identity is in a `blocked` set. That set
was `seen.json | skiplist.md`. We added a third source:

```
blocked = seen.json | skiplist.md | applied.json
          (analyzed)   (hand-edited)  (synced from the sheet)   ← new
```

The identity is `models.composite_id(company, title, city)` — legal-suffix-stripped company, normalized
title, e.g. `nationmind|ai engineer developer|`. The sync's whole job is to turn each messy applied row into
*that exact string* so it collides with the ranked job for the same posting.

## Why it needs a model call (not a column map)
The sheet is free-form. Observed reality:
- `hiring company` is **blank on ~half the rows**.
- The `job-id` column is a junk drawer — it holds a req#, a *location* (`Broad Run, VA`), a title+req+location
  mash (`Python developer (BBBH1688426) Georgia, USA`), the actual **title**, and sometimes a **company**
  (`tyto`).
- The real title sometimes lives in `description` instead.
- Company is often only inferable from the **link domain** (`careers-gotyto.icims.com` → Tyto).

You can't map column→field — the title is in a different place per row. So `/sync-applied` has **Claude
normalize each row in-session** (using judgment about link domains, mashed fields, etc.) into clean
`{company, title, city, url, confidence, note}`, then hands those to Python.

## Architecture (who does what)
```
Google Sheet ──Drive MCP──▶ Claude normalizes ──▶ python -m triage --sync-applied ──▶ applied.json ──▶ ranker
 (messy, 18 cols)  (in-session)  (row → clean fields)     (computes keys via composite_id)   (dedup cache)  (unions)
```
- **Read** — `/sync-applied` reads the sheet via the Drive connector (`read_file_content`, which supports
  Google Sheets natively). Interactive-session only; the connector is absent in headless/cron runs (paste a
  CSV export as the fallback).
- **Normalize** — Claude, not the Python, untangles the mess. This is the robust-against-messy-data step.
- **Persist** — `applied.py` computes the keys (so they always match the ranker's `composite_id`, never a
  caller's guess) and writes `data/corpus/applied.json`. **The sheet is the source of truth**, so each sync fully
  REPLACES the file — edit a row in the sheet, re-sync, and the cache tracks it.
- **Dedup** — `__main__._phase1` unions `applied.load_blocked()` into `blocked`.

## Two keys per record (belt and suspenders)
A candidate is skipped if **either** matches:
- **composite key** — `composite_id(company, title, city)`. The primary; matches how the ranker keys jobs.
- **url key** — `'url:' + normalized apply URL` (LinkedIn/Indeed tracking stripped). Catches the case where
  the model's company/title differ slightly from how the ranker normalized the same posting.

## Confidence gating (guards against false dedup)
Each normalized row carries a confidence. **`high`/`medium` auto-block; `low` is stored but NOT blocked** —
it's reported back to Ben for review instead. Rationale: silently hiding a job he *didn't* apply to (a false
dedup) is worse than one occasionally resurfacing, so ambiguous rows (a bare HN link, no real title) fail
open. `data/corpus/applied.json` keeps every record; only the `high`/`medium` ones feed `blocked`.

## Running it
- **On demand:** ask Claude to run `/sync-applied` (see `.claude/commands/sync-applied.md`).
- **Before a triage run:** `/job-triage` step 0 asks whether to sync first — say yes when you've applied to
  things since the last sync (usually).
- **Under the hood:** `.venv/bin/python -m triage --sync-applied <rows.json>` (Claude writes `<rows.json>`
  from the normalized sheet; you rarely call this directly).

## Keeping it cheap going forward
The model handles the legacy mess, but two habits make future syncs deterministic and near-free:
1. Keep **`hiring company`** filled.
2. Put the **title** consistently in one column (its own, not `job-id`).
With those clean, rows normalize to `high` confidence trivially and nothing needs a judgment call.

## Files
- `triage/applied.py` — record schema, key-building, `sync_from_rows`, `load_blocked`.
- `data/corpus/applied.json` — the cache (git-ignored, like all of `data/`).
- `triage/__main__.py` — `--sync-applied` mode + the `blocked` union in `_phase1`.
- `.claude/commands/sync-applied.md` — the read+normalize+persist skill.
- `profile/profile.yaml → applied_sheet` — the sheet id.
