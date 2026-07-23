---
name: job-triage
description: Run the full job-triage pipeline end-to-end — analyze, verify liveness, archive mail, write the apply doc, tailor résumés for the top picks, and commit
---

Run the triage tool end-to-end and hand Ben a digest. Do ALL steps — do not stop after the script. The
script does the bulk; you (Claude) do what it can't: Tier-2 browser JD retrieval, moving processed mail,
merging carryovers, and building the tailored résumés. Full reference: `docs/operating/triage-operating.md`.

**"Run triage" means all NINE steps below, ending with tailored résumés and a commit.** Do not stop at the
digest and do not ask Ben whether to do a step that is listed here — it is all standard. The only
questions worth asking are Step 0 (applied-sheet sync) and a CAPTCHA click in Step 3.

**Say "Step N (description)" when reporting progress — never a bare "Step 4".** Ben has no idea what a
bare number refers to.

**Announce the plan first.** Before starting, post the nine step names so Ben can see the shape of the run.

## 0. Ask: sync the applied sheet first?
Ask Ben: **"Want me to sync your applied sheet first, so we don't re-surface jobs you've already applied
to?"** If yes, run `/sync-applied` to refresh `data/corpus/applied.json`. **Skip this without asking if Ben has
already said he didn't apply to anything since the last run.**

## 1. Phase 1 — bulk analysis (the script)
Size the window from the last run: read `data/runs/latest-run.txt`, and pass `--days N` covering the
full gap to today (default is only 3). A 7-day gap needs `--days 7` or jobs fall through the hole.

**Always tee the output — do NOT pipe through `tail`.** `tail` buffers everything until exit, which
leaves you blind for the whole run (this happened on 2026-07-20: 25 minutes with zero visibility):

```
.venv/bin/python -m triage --days N 2>&1 | tee /tmp/triage-run.log
```

Run it in the background and poll the log. Expect ~9-10 min for ~350 jobs at the current 12 workers (measured, not a guess); if
it runs far longer, check whether it is progressing (`%CPU` near 0 with cycling TCP connections is normal
— the work is network-bound) before assuming it hung.

It prints the exact paths it wrote (worklist, state, browser-queue, archive list). Use those paths. If it
says "no new jobs," tell Ben and stop.

## 2. Tier 2 — pull the walled JDs through Ben's Chrome
Read the `browser-queue-<date>.json` the script named. If absent/empty, skip to Step 3 (merge).
Load Chrome tools once: ToolSearch `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__list_connected_browsers`.

**⚠ PREFLIGHT — tell Ben before touching the browser:** *"Quit the Claude desktop app before I start the browser step — it shares this Chrome extension and steals the connection."* Then verify with `list_connected_browsers`:
- If it returns a browser → proceed.
- If it returns `[]` → the extension isn't bound to Claude Code. Usual causes (diagnosed 2026-07): (a) the **Claude desktop app** (or its orphaned `/Applications/Claude.app/Contents/Helpers/chrome-native-host` process) is holding the shared extension `fcoeoabgfenejglbffodgkkbkcdhcgfn` — have Ben quit Desktop; if a stray `chrome-native-host` lingers, `pkill -f "Claude.app/Contents/Helpers/chrome-native-host"`; (b) a **claude.ai auth/service outage** (check status) breaks the extension connection; (c) a **Chrome update** left the extension's MV3 popup blank — the popup being blank does NOT block automation, only the *connection* matters, so ignore blank popups and just re-check `list_connected_browsers`. Reconnect via the extension's Connect button or `/chrome` → Reconnect, then re-verify. Don't start fetching until it returns a browser.

Call `tabs_context_mcp` (createIfEmpty true) to get a tab id. Then for each queued item:
- `navigate` to its `link`.
- **Bot-wall check (always):** if the tab title is "Just a moment…" or the page text contains "Verify you
  are human" / "Additional Verification Required", STOP and tell Ben: *"<site> hit a CAPTCHA — click the
  checkbox in the Chrome window, then say 'done'."* Wait for him. One click usually clears the whole
  session, so you'll rarely ask more than once per run.
- Once past, `get_page_text`. **Dice `elinks` links** often land on a listing/company page with no JD —
  in that case navigate to `https://www.dice.com/jobs?q=<title>+<company>`, open the matching posting,
  then `get_page_text`.
- Keep the page's job-description text only if it's really a JD (has responsibilities/qualifications/
  requirements and >~200 chars). If the page is empty/blocked and unrecoverable, skip it — it stays in the
  worklist's "manual check" list.
Write the results as a JSON object `{ "<composite id from the queue>": "<jd text>", ... }` to the
**`browser-jds-<run_id>.json` path Phase 1 printed** (each run has a unique `<run_id>` = date+time; the
browser-jds file must use the SAME run_id as that run's `browser-queue` file, so `--merge` picks it up).

## 3. Phase 3 — merge
Run `.venv/bin/python -m triage --merge`. It reads `data/runs/latest-run.txt` to find this run's files,
re-analyzes the browser-fetched jobs with their full JDs, and rewrites that run's worklist. Files are
never overwritten across runs — each run's `worklist-<run_id>.md` is preserved.

## 4. Re-check the previous run's picks (carryover verdicts)
Open the previous apply doc in `matches/` (`<date>.md`). **Every pick Ben did not apply to must be
re-verified before it is carried forward.** On 2026-07-20 this step found that *all five* 7/13 picks
checkable at their primary source had closed, including the $90/hr top pick.

The script now checks liveness automatically, but it **cannot judge LinkedIn, Indeed, or aggregator
listings** (see `docs/operating/triage-operating.md` → Liveness). Those show as ⚪ UNVERIFIED and need the
browser session from Step 3 — check them there, in parallel where possible.

Mark each carryover **DEAD** (with the evidence) or **still listed**. Never silently carry one forward.

## 5. Archive processed emails → jobs-triage
Read the `archive-<date>.txt` the script wrote. Get the `jobs-triage` label id via `list_labels`. For each
`<message-id>` line (tab-separated; first field is the id):
- `search_threads(query: "rfc822msgid:<id>")` → take the thread id
- `label_thread(threadId, ["<jobs-triage label id>"])`  — add the label
- `unlabel_thread(threadId, ["INBOX"])`  — **this is what archives it**
Skip any that error. Count how many moved.

**This is 3 calls per email and runs to 100+ emails — delegate it to a subagent** (`Agent`, general-purpose)
with the file path and these rules, and carry on with the next steps while it runs. Only add the label and
remove INBOX: never mark read, never delete, never touch another label.

**⚠ Backstop — Gmail archives per THREAD, this list is per MESSAGE.** The script now holds human
correspondence off the list automatically (`channels.common._is_correspondence`), but the subagent must still
**skip any thread that contains a SENT message, or any message not on the list.** Archiving one line of
a live conversation removes the whole thread — replies and unread mail included — from the inbox. This
caught Ben's College Board interview thread on 2026-07-20.

## 6. Write the apply document — a CHECKBOX APPLY-LIST (this is the default format)
Write `matches/<date>.md` — **this is the file Ben actually reads and copies into Obsidian to manage
applying**; the raw worklist is the appendix. **The default and required format is an Obsidian-compatible
checkbox list**, NOT a prose report and NOT tables. Every recommended job is a `- [ ]` item so Ben can
tick it off as he applies; the supporting data sits indented underneath it.

**Per-item shape (exactly this):**
```
- [ ] **<Role> @ <Company>** — <liveness emoji> · fit <N> · <rate/terms> · <one-line lane note>
	- Link: <apply URL>
	- Résumé: `applications/<folder>/` <✅ if built, else "on request">
	- Note: <one short caveat — duplicate-agency, aggregator-unreliable, live-process conflict, etc.>
```

**Top of file:** a one-line legend (`🟢 verified open · ⚪ unverified — check before effort · 🔴 closed`)
and the liveness caveat if anything is ⚪ UNVERIFIED.

**Grouped in this order (each a `##` heading, every entry a checkbox):**
- **Tier 1 — remote + contract.**
- **Tier 2 — remote perm** ("a good perm wins" — never downrank a strong remote perm).
- **Carryover** from Step 4: dead ones struck through (`~~...~~`) with evidence; survivors as live checkboxes.
- **📬 Reply, don't cold-apply** — the worklist's "Live correspondence" roles a human emailed Ben about;
  never apply targets (a duplicate agency application can cut across a direct process). Still `- [ ]` items,
  but the action is "reply", stated in the line.

Recommend the real apply set (not a fixed count) — put the strongest, verified-open, in-lane roles first.
Every checkbox MUST carry a working apply link and, where a résumé was built in Step 7, its folder path.

Rank on **drain, not comp** — pay is a threshold (≥$115k / ≥$50/hr), energy is priority #1.

**Carry the worklist's "📬 Live correspondence" section into the apply doc as its own block — never as
apply targets.** Those are roles a human emailed Ben about, and some are processes he is already in.
Check the thread (and his live interviews) before recommending any action; a duplicate agency
application can cut across a direct process.

## 7. Tailor résumés for the top picks — STANDARD, DO NOT ASK
Run `/tailor-cv` for the **top 3–5 picks worth applying to** from Step 6. This is not optional and does
not need Ben's go-ahead; it is what makes the list actionable. Two rules:
- **Refresh stale ones.** A tailored CV built before a `profile/bullet-bank.md` change is out of date — rebuild
  rather than reuse it.
- **Skip anything confirmed DEAD** in Step 4, and anything conflicting with a live interview process.

`/tailor-cv` has its own approval gate for the bullet choices — that gate is where Ben gets a say, not
whether to run it at all.

## 8. Deliver the digest
Present a tight digest in chat: the **Focus picks** (title @ company, why, apply link, liveness), then a
one-line-each ranked rest, then the "couldn't-fetch / manual check" list.
Close with: `N analyzed · N archived · N manual-check · N résumés built`.

## 9. Update the run log and commit
**Docs are updated BEFORE the commit, never after — and lessons get written down, not left in commit
messages where nobody finds them.** Three files, in order:

1. `profile/notes/market-insights.md` — a dated entry: counts, what shifted in the market, rates seen,
   carryover verdicts, and any tool change made during the run. Standing instruction, unprompted.
2. `docs/operating/triage-engineering-log.md` — **if anything was learned or fixed**, append it: what shipped
   (with commit hashes), the lesson and what it cost to learn, and any new open bug. Also close out
   entries in its "Open bugs" list that this run resolved.
3. `docs/operating/triage-operating.md` — if tool *behaviour* changed. This runbook — if the *process* changed.

Then commit. Never commit `data/`, `matches/` or `applications/` — they are git-ignored.

**Rules for this step, learned the hard way:**
- **Never claim a doc is updated without verifying it.** Use the Edit tool (it errors when the target
  text isn't found); a scripted string replace fails silently and produces a commit message that lies.
- **Quote measured numbers, not estimates.** If a claim about speed or cost hasn't been measured against
  real run data, say it's an estimate or don't make it.

## Rules
- Only ever change mail via Step 5 (archive: label + unlabel INBOX). Never mark read, never delete.
- **Never report a job as available unless it was actually verified.** LinkedIn/Indeed/aggregator
  listings are UNVERIFIED, not open — say so. A false green light on a dead req is the worst output.
- **Never state a years-of-experience number** anywhere in a résumé or application (see bullet-bank
  DO-NOT-CLAIM).
- Never write to the applied-jobs Google Sheet — it is Ben's own dashboard, and the sync runs one way.
- If the browser queue is big, tell Ben the count up front and that one CAPTCHA click covers the session.
