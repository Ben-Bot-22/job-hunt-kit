---
name: sync-applied
description: Sync Ben's applied-jobs Google Sheet into the triage dedup cache (applied.json) so already-applied roles never resurface
---

Pull Ben's applied-jobs Google Sheet, normalize its messy rows, and write them into the triage dedup cache
(`data/corpus/applied.json`) so the ranker never re-surfaces a job he has already applied to. Full
reference: `docs/operating/triage.md § the applied-sheet sync`.

The sheet is free-form and inconsistent — company is often blank, the **title lands in whichever column
Ben pasted into** (`job-id` OR `description`), and identity is sometimes only inferable from the link
domain. That mess is why this step uses your judgment to normalize, not a column map.

## 1. Read the sheet
Load the Drive tool once: ToolSearch `select:mcp__claude_ai_Google_Drive__read_file_content`.
Read `profile/profile.yaml → applied_sheet` for the id, then `read_file_content(fileId: <that id>)`.
(The id is never written down here — it is one user's Sheet, and a skill that ships must not carry it.
If the read fails because it's a fresh/headless session
with no Google connector, tell Ben and ask him to paste a CSV export instead — then normalize that.)

## 2. Normalize every non-empty row → JSON
For each row that has any of company / title / link, produce ONE object. Reconcile the mess:
- **title** — take the real role title, wherever it sits (`job-id` col like "Sr. Software Engineer, Studio",
  or the `description` col like "Software Engineer III"). Strip req numbers / locations mashed into it
  (e.g. `Python developer (BBBH1688426) Georgia, USA` → title "Python Developer", city "Georgia").
- **company** — use the `hiring company` col; if blank, infer from the link domain
  (`careers-gotyto.icims.com` → Tyto; `recruiting.ultipro.com/HEA1015` → All One Health) or leave blank.
- **city** — only if clearly present (e.g. "Broad Run, VA", "Dayton"); else "".
- **url** — the raw link as-is (the tool re-normalizes LinkedIn/Indeed tracking cruft; don't hand-edit).
- **confidence** — `high` when company+title are clear (clean or confidently inferred); `medium` when one
  was inferred with some doubt; `low` when the row is genuinely ambiguous (a bare HN/company link, no real
  title). **Only `high`/`medium` auto-block; `low` is surfaced for Ben, not silently hidden** — so when in
  doubt, use `low`. A false dedup (hiding a job he never applied to) is worse than one resurfacing.
- **note** — one short phrase: how you inferred it, or why it's low.
- **row** — the sheet's `No`.

Write the array to a scratch file, e.g. `<scratchpad>/applied-rows.json`:
```json
[{"row":29,"apply_date":"6/30","company":"NationMind LLC","title":"AI Engineer Developer","city":"","url":"","confidence":"high","note":"clean company+title"}]
```

## 3. Persist into the cache
Run from the repo root:
```bash
.venv/bin/python -m triage --sync-applied <scratchpad>/applied-rows.json
```
It computes the canonical keys (same `composite_id` the ranker uses, plus a normalized-URL key), REPLACES
`applied.json` (the sheet is the source of truth), and prints how many were auto-blocked vs held for review.

## 4. Report to Ben
Give a tight summary: N records synced, N auto-blocked, and **list the "held for review" rows** (the
low-confidence ones) by row number + best-guess so he can eyeball or clean them in the sheet. Mention that
keeping the sheet's `hiring company` + `title` columns clean on new rows makes future syncs bulletproof.

## Rules
- Read-only on the sheet — never write back to Google.
- The sheet fully replaces `applied.json` each run; don't try to merge by hand.
- The sync runs ONE WAY: the Sheet is Ben's own dashboard and nothing here ever writes to it.
