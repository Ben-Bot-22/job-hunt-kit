---
name: job-triage
description: Run the full job-triage pipeline end-to-end — analyze, verify liveness, archive mail, write the apply doc, then research, tailor a résumé and draft a cover letter for every pick worth applying to, and commit
---

Run the triage tool end-to-end and hand Ben a digest. Do ALL steps — do not stop after the script. The
script does the bulk; you (Claude) do what it can't: Tier-2 browser JD retrieval, moving processed mail,
merging carryovers, and building the application package. Full reference: `docs/operating/triage.md`.

**"Run triage" means all THIRTEEN steps below, ending with a full application package per pick and a
commit.** Do not stop at the digest and do not ask Ben whether to do a step that is listed here — it is
all standard. The only questions worth asking are Step 0 (applied-sheet sync) and a CAPTCHA click in
Step 2.

**THE APPLY SET — one set, three artifacts, and this is the whole point of the run.** Steps 7, 9 and 10
all operate on the *same* list: **every pick worth applying to.** For each one the run produces a
**company brief**, a **tailored résumé** and a **cover letter**.

**SHOW EVERYTHING, BUILD `fit >= 70` (2026-08-04).** Two separate decisions, and conflating them is
what the old ten-cap got wrong:

- **The apply doc lists every live pick, ranked, with its link and its research.** Nothing is dropped
  for being eleventh. Ben: *"i want optionality and some days are slower than others."*
- **Documents are built for `fit >= 70`.** A score gate, not a position gate — it keeps every role
  worth the tokens and drops only the ones that were not, where a positional cap punishes a good job
  for its rank. Ben: *"for good fits (>70) you should probably build anyway."*
- **Everything below 70 stays in the doc marked "build on request"**, one word away.

```bash
.venv/bin/python -m cv.batch worklist <apply doc> --min-fit 70
```

**is** that set. Do not assemble it by hand and do not re-derive it per step; the three steps must not
disagree about which jobs are in. An entry whose line printed **no** score is kept — absence of a
number is not evidence of a low one.

Measured over 19 run-files, `>= 70` is **~14 roles per run**, and on 2026-08-03 it built 21 of 23. If
a run returns far more than that, say so before building rather than silently spending an hour.

**Never pad.** A gate is not a quota: a run where four roles clear 70 gets four packages.

**WHICH MODEL EACH FAN-OUT USES (2026-08-04, and this is a cost decision with one exception that
matters).** Pass `model` on the `Agent` call:

| step | model | why |
|---|---|---|
| 7 · company research | **`sonnet`** | search-and-summarise against sources. ~60k tokens each and little judgement — 20 of them was 1.26M tokens on 2026-08-04 |
| 9 · résumés | **inherit (Opus)** | **do not downgrade this one.** These agents' real job is refusing the grader — on 2026-08-04 they declined SQL, CI/CD, Kubernetes, Java, Copilot and invented metrics, several of them three times against escalating pressure. That is judgement under adversarial push, and `cv/test_claims.py` only catches a fixed list. A model that accepts one plausible-sounding fix puts a false claim in a document Ben sends to an employer |
| 10 · cover letters | **`sonnet`** | tightly constrained — two paragraphs, no numbers, checked against `plan.json`, and the voice files do the work |
| 5 · mail archiving | **`sonnet`** | mechanical: three API calls per email against a fixed guard list |

Measured baseline: the 2026-08-04 run was **~6.15M subagent tokens across 58 agents, and the CV agents
were 55% of it.** The split above plus `MAX_PASSES = 2` is roughly a 40% cut without touching the part
that protects him.

**Say "Step N (description)" when reporting progress — never a bare "Step 4".** Ben has no idea what a
bare number refers to.

**Announce the plan first.** Before starting, post the thirteen step names so Ben can see the shape of
the run.

## 0. Sync the applied sheet — ALWAYS, DO NOT ASK
Run `/sync-applied` to refresh `data/corpus/applied.json`. **This is a default, not a question**
(Ben, 2026-08-05: *"when i say run triage we need to make assumptions — i will tell you in the first
message if i want to change anything"*). Skip it only if Ben said so in the message that started the run.
The cost of asking is a blocked run; the cost of a redundant sync is seconds.

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

**⚠ PREFLIGHT — take the connected browser and go; never ask which one** (Ben, 2026-08-05). Verify with `list_connected_browsers`:
- If it returns a browser → proceed with it. If it returns several, take the first and say which.
- Only if it returns `[]` is there anything to raise. Usual causes (diagnosed 2026-07): (a) the **Claude desktop app** (or its orphaned `/Applications/Claude.app/Contents/Helpers/chrome-native-host` process) is holding the shared extension `fcoeoabgfenejglbffodgkkbkcdhcgfn` — have Ben quit Desktop; if a stray `chrome-native-host` lingers, `pkill -f "Claude.app/Contents/Helpers/chrome-native-host"`; (b) a **claude.ai auth/service outage** (check status) breaks the extension connection; (c) a **Chrome update** left the extension's MV3 popup blank — the popup being blank does NOT block automation, only the *connection* matters, so ignore blank popups and just re-check `list_connected_browsers`. Reconnect via the extension's Connect button or `/chrome` → Reconnect, then re-verify. Don't start fetching until it returns a browser.

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

## 3. Phase 3 — merge, and the resume path
Run `.venv/bin/python -m triage --merge`. It reads `data/runs/latest-run.txt` to find this run's files,
re-analyzes the browser-fetched jobs with their full JDs, rewrites that run's worklist **and writes the
state file back** — the corpus, not just the page. Files are never overwritten across runs; each run's
`worklist-<run_id>.md` is preserved.

**`--merge` is also how a broken run is picked up, and there is no `--resume` flag by design.** It
re-scores every job whose analysis failed as well as every browser-fetched one. So if Phase 1 reported
`⚠ N job(s) NOT SCORED` — a spend cap, a missing key, a provider outage — fix the cause and run `--merge`
again; those jobs were deliberately left out of `seen.json` and out of the archive list, so nothing was
lost. Repeat until it reports none. Phase 1 also checkpoints every 25 jobs, so a run that died halfway
still has its judgments on disk and `--merge` will render them.

## 4. Re-check the previous run's picks (carryover verdicts)
Open the previous apply doc in `matches/` (`<date>.md`). **Every pick Ben did not apply to must be
re-verified before it is carried forward.** On 2026-07-20 this step found that *all five* 7/13 picks
checkable at their primary source had closed, including the $90/hr top pick.

The script now checks liveness automatically, but it **cannot judge LinkedIn, Indeed, or aggregator
listings** (see `docs/operating/triage.md` → Liveness). Those show as ⚪ UNVERIFIED and need the
browser session from Step 2 — check them there, in parallel where possible.

**If a ⚪ carryover's only link is an aggregator (RVC, Jobright, JobLeads…), search the EMPLOYER before
carrying it forward again** — an aggregator link is evidence of nothing. On 2026-07-28 one search moved
Greenway Health from ⚪ (carried five days) to verified-OPEN at the employer's own feed, and the same pass
killed two others: a "company" posting the identical role at three different salary bands simultaneously
(a repost farm) and an executive-search firm being carried as if it were the employer.

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

Lines are `<message-id> TAB label TAB from TAB subject TAB context`, so the file itself says who each
email is from — copy those two fields into the apply doc's archive section rather than re-deriving them
from the mailbox.

**⚠ Backstop — Gmail archives per THREAD, this list is per MESSAGE.** Two guards already ran in the
script: `channels.common._is_correspondence` keeps classified human conversations off the list, and
`has_human_display_name` holds back anything whose From: header names a person, even when the domain
reads as automated. The subagent must still **skip any thread that contains a SENT message, or any
message not on the list.** Archiving one line of a live conversation removes the whole thread — replies
and unread mail included — from the inbox. This caught Ben's College Board interview thread on 2026-07-20.

**Anything the script HELD BACK is in the worklist under `📥 HELD BACK from archiving` — do not archive
it, and carry it into the apply doc.** It is still in the inbox on purpose: the sender looks like a
person. Read those, and archive one by hand only if it is plainly a blast.

## 6. Write the apply document — a CHECKBOX APPLY-LIST (this is the default format)
Write `matches/<date>.md` — **this is the file Ben actually reads and copies into Obsidian to manage
applying**; the raw worklist is the appendix. **The default and required format is an Obsidian-compatible
checkbox list**, NOT a prose report and NOT tables. Every recommended job is a `- [ ]` item so Ben can
tick it off as he applies; the supporting data sits indented underneath it.

**Per-item shape (exactly this).** The role title carries NO leading number — the batch parser slugs it
into a folder name, and `1 · Lead AI Engineer` becomes a folder called `1-lead-ai-engineer`:
```
- [ ] **<Role> @ <Company>** — <liveness emoji> · fit <N> · <rate/terms> · <one-line lane note>
	- Link: <apply URL>
	- Research: `data/research/<slug>.json` — <the one line that changes what he does> (Step 8)
	- Résumé: `applications/<folder>/` <✅ if built, else "on request">
	- Letter: `applications/<folder>/cover-letter.json` <✅ if drafted>
	- Note: <one short caveat — duplicate-agency, aggregator-unreliable, live-process conflict, etc.>
```
The `Research:` and `Letter:` lines are written by Steps 8 and 10; leave them out on the first pass
rather than writing a placeholder that later reads as done.

**Top of file:** a one-line legend (`🟢 verified open · ⚪ unverified — check before effort · 🔴 closed`)
and the liveness caveat if anything is ⚪ UNVERIFIED.

**⚠ THE `##` HEADINGS BELOW ARE A FIXED VOCABULARY — USE THEM VERBATIM.** This file stopped being prose
for Ben alone the moment Steps 7/9/10 took their work list from it: `cv/batch.py` reads the headings to
tell the apply set apart from the audit sections, which are also full of `- [ ]` lines. It classifies by
name, a `###` subsection inherits from the `##` above it, and **an unrecognized `##` raises rather than
guessing** — because both guesses are wrong (build documents for jobs he must not cold-apply to, or
silently build none and report success). Invent a subsection heading freely; do not invent a `##` one.

**Grouped in this order (each a `##` heading, every entry a checkbox):**
- **`## Tier 1 — remote + contract`.**
- **`## Tier 2 — remote perm`** ("a good perm wins" — never downrank a strong remote perm).
- **`## Carryover`** from Step 4: dead ones struck through (`~~...~~`) with evidence; survivors as live checkboxes.
- **`## ⏸ Held back for review`** — REQUIRED whenever anything was held. **Only two things reach it**:
  stated travel over 40% (`travel`) and a posting claiming the whole person at the BJAK bar
  (`intensity`). Every entry carries **its apply link, its fit score, the quoted tell, and anything
  research turned up that Ben should weigh** — the section exists so he can pull one back in, and a
  line he cannot act on defeats it. No documents are built for these unless he asks. Ben, 2026-08-04:
  *"you still need to add links to the hold line so i can evaluate and include anything important you
  found for my consideration."* The heading matches `cv/batch.py`'s skip list on the words *held back*,
  which is what keeps these out of the batch — do not rename it to something that loses them.
- **`## 📬 Reply, don't cold-apply`** — the worklist's "Live correspondence" roles a human emailed Ben about;
  never apply targets (a duplicate agency application can cut across a direct process). Still `- [ ]` items,
  but the action is "reply", stated in the line.
- **`## ⚠ Check by hand — could not fetch automatically`.** LAST section, and it is REQUIRED, not optional.
  Copy the worklist's "⚠ Couldn't fetch" block across verbatim: every link, with its failure reason. The
  tool already generates that list (`triage/__main__.py:220`, `needs_manual_review`), so the only way it
  reaches Ben is if this step carries it — and it must, because **these jobs are marked `seen` and will
  never appear in a future run.** Today's link is the only chance he gets to look at one.
  Standing instruction (Ben, 2026-07-29): *"if you have to skip due to JD retrieval issues, i want to
  see those links so i can check it out for myself in the output"* — and he asked for it at the bottom,
  framed as "check out — could not fetch automatically". Note that a `linkedin guest fetch exhausted`
  reason is RATE-LIMITING, not a dead link: those are worth opening, they were merely throttled.
- **`## 📥 Mail` — REQUIRED, and now COPIED, not reconstructed.** The worklist renders both halves and the
  script fills them: `📥 HELD BACK from archiving` (emails whose sender names a person — still in the
  inbox, needing his eyes) and `📥 Archived this run` (what Step 5 moved, each with **sender and
  subject**). Copy both across. Put HELD BACK *above* the fetch list — it is the only one that needs a
  decision. On 2026-07-29 this table was assembled by hand from a subagent's mailbox report, which does
  not scale and does not survive a forgetful session; it is generated now, so do not rebuild it.
- **`## 📋 Every job looked at` — REQUIRED, last section.** All analyzed jobs, one line each: score, verdict,
  company, title, link. Generate it from that run's `data/corpus/state-<run_id>.json`, sorted by score
  descending so the tail is skimmable.

**Why those last two exist, and it is the same reason as the fetch list: THIS FILE IS THE ONLY AUDIT
SURFACE.** Ben reads the apply doc and nothing else — the `jobs-triage` label is write-only in practice
(*"i don't check the folder"*), and `data/runs/` is disposable. So anything a reader would need to catch
a mistake has to be in here, or it is invisible. He asked for this directly on 2026-07-29 after a live
recruiter email was archived and only surfaced because a subagent happened to mention it: *"it is clear
we need logs to trace what you are doing b/c there is data slipping through. I need to be able to audit
you… we need to upgrade the system to make it debugable and allow us to catch errors."* The three
sections answer the three audit questions — what did you fail to read, what did you touch in my mail,
and what did you actually see.

Recommend the real apply set (not a fixed count) — put the strongest, verified-open, in-lane roles first.
**Document order is rank order.** No job is dropped for being ranked low, but the order is what he reads
down when he has time for three applications and not nine, so it is a decision rather than a formatting
choice. Every checkbox MUST carry a working apply link.

**Every checkbox MUST also carry `fit N`** — `cv/batch.py` reads that number to decide what gets
documents (`--min-fit 70`). Bold it if it deserves attention (`fit **85**`); the parser tolerates
emphasis. A line with no score is treated as unscored and kept, so omitting one silently promotes a
weak job into the build set.

**Carryover entries MUST carry the `Résumé:` line pointing at their ORIGINAL folder.** They already
have documents from the run that first surfaced them; without that line the batch derives a fresh
dated folder, `existing` reads false, and every carryover is rebuilt from scratch every morning. That
happened on 2026-08-03.

**A role with hours risk is RANKED, not hidden (2026-08-04).** On-call rotations, 24/7 uptime, incident
response, cross-team ownership, sprints and travel up to 40% are ordinary conditions of employment —
they sort the role below equal-fit sane-hours roles and put the quoted tell on its line, and that is
all. Only stated travel over 40% (`travel`) and a posting claiming the whole person at the BJAK bar
(`intensity`) still leave the ranked list, and both land in `## ⏸ Held for review` **with their links
and whatever research found**, because the point is that Ben can pull one back in. Full rule:
`profile/rubric.md` §INTENSITY.

Rank on **drain, not comp** — pay is a threshold (≥$115k / ≥$50/hr), energy is priority #1.

**Carry the worklist's "📬 Live correspondence" section into the apply doc as its own block — never as
apply targets.** Those are roles a human emailed Ben about, and some are processes he is already in.
Check the thread (and his live interviews) before recommending any action; a duplicate agency
application can cut across a direct process.

## 7. Fix the apply set, then research every company in it — IN PARALLEL
First, take the set once and reuse it for the rest of the run:

```bash
.venv/bin/python -m cv.batch worklist "matches/<date>.md"
```

**If that command raises**, it has found a `##` heading it cannot classify — fix the heading in the
apply doc to one of Step 6's, do not work around it, and do not hand-assemble the list instead. The
error names the heading.

Then **fan out one `/research-company` agent per company, all launched in a single message.** The
engine is `python -m research`; the agent's job is the half the engine cannot do — closing the brief's
`## Open questions` with its own web search and writing the answers back with `--answer`.

- **Research runs BEFORE the résumés and letters on purpose.** It is the step that changes *whether to
  apply at all*: agency-not-employer, the same req shopped under three names, a company already on the
  skiplist. Finding that out after ten résumés are built wastes the ten.
- **Deduplicate by company first.** Three Apex Systems roles is one brief, not three — briefs cache to
  `data/research/<slug>.json` and three concurrent agents on one slug race each other.
- **Each agent returns the one line that changes what Ben does**, not the brief. Those lines are what
  Step 8 writes into the apply doc.
- A brief younger than 14 days is served from cache and costs nothing, so do not skip a company to
  save time.

## 8. Revisit the rankings with what research found — then update the apply doc IN PLACE
**This step is why research runs mid-run rather than at the end, and it is Ben's standing instruction
(2026-07-30): *"after the company reports you should revisit rankings at the end with the new info and
update notes on the triage document."*** The apply doc written in Step 6 was ranked on the posting
alone. Now there is more.

Re-read the set with the briefs in hand and **edit `matches/<date>.md` in place** — not a second file,
not a chat summary that leaves the doc stale:

- **Reorder** Tier 1 and Tier 2 where a brief changed the picture. Say in the digest what moved and why.
- **Add the `Research:` sub-bullet** to every entry: the cache path plus the one line that matters.
- **Strike through (`~~...~~`) anything research killed** — the same req already applied to under
  another company name, a listing that is an executive-search firm rather than the employer, a
  skiplisted company — with the evidence, exactly as Step 4 does for dead carryovers. A struck entry
  drops out of Steps 9 and 10 automatically, which is the point.
- **Move a cold-apply into `## 📬 Reply, don't cold-apply`** when the brief shows a process already in
  motion. Do not leave it in a tier with a warning note; the tier is what the batch reads.
- **Re-run the worklist command after editing** and use *that* output for Steps 9 and 10. The set may
  legitimately have shrunk, and a job promoted from eleventh into the top ten gets a package too.

## 9. Tailor a résumé for every job in the set — STANDARD, DO NOT ASK, AND IN PARALLEL
Run **`/tailor-cv-batch`** over the Step 8 set. This is not optional and does not need Ben's go-ahead;
it is what makes the list actionable. Three rules:
- **Parallel is the default, not an optimisation.** `/tailor-cv-batch` builds the work list from the
  apply doc this run just wrote and fans out one agent per job. Running `/tailor-cv` N times serially
  is the old behaviour and it made Ben wait through six round-trips on 2026-07-28. Use `/tailor-cv`
  directly only when the run produced exactly one pick.
- **Refresh stale ones.** A tailored CV built before a `profile/bullet-bank.md` change is out of date — rebuild
  rather than reuse it. `.venv/bin/python -m cv.batch worklist <apply doc>` reports which folders exist.
- **Skip anything confirmed DEAD** in Step 4, struck through in Step 8, or conflicting with a live
  interview process.

Give each agent the company brief from Step 7 — it is the honest, specific tie-in, and an agent
without it writes a generic document.

The bullet choices come back for post-hoc edit — that is where Ben gets a say, not whether to run it
at all.

## 10. Draft a cover letter for every job in the set — IN PARALLEL, AFTER the résumés
Fan out one **`/cover-letter`** agent per job in the same set, all in a single message. This runs after
Step 9 and not beside it: the skill requires the letter to read that job's `plan.json`, because **the
letter must not contradict the résumé in the same envelope.**

Every agent prompt must carry, because each is a rule the skill states and an agent under batch
pressure drops:
- **Read the posting IN FULL** from `applications/<folder>/jd.txt` — the gating requirements
  (citizenship, clearance, onsite %, W2/1099) are what a letter is *for*, and they sit at the end.
- **Two paragraphs, bare, no numbers, no telling the employer about themselves.** A longer letter is
  the failure mode, not the safe choice.
- **Read-only on `profile/bullet-bank.md`**, same as the CV batch, and for the same reason.
- **Build first**: render to `applications/<folder>/cover-letter.json` via
  `cv/scripts/make_cover_letter.py`, then report the body text.
- **Do not append to `profile/letters/`** — that directory is the corpus of letters actually *sent*,
  and a batch draft is not a sent letter.

**Paste the bodies of the TOP THREE into chat and no more.** Ben rewords letters from chat rather than
by opening the docx, so the top ones must be there — but ten letter bodies in one message is a wall
nobody reads, which defeats the purpose. The rest are listed by folder as drafted, and he asks for any
of them. Add the `Letter:` sub-bullet to each entry in the apply doc.

## 11. Deliver the digest
Present a tight digest in chat: the **Focus picks** (title @ company, why, apply link, liveness, and
the one research line), then a one-line-each ranked rest, then the "couldn't-fetch / manual check" list.
Say **what Step 8 re-ranked or killed** — a silent reorder is invisible to a reader of the final doc.
Close with: `N analyzed · N archived · N manual-check · N researched · N résumés · N letters`.

Say how many packages were built and that the number is the real recommendation — there is no cap,
so a short list means the run found that many worth his morning, not that it gave up early.

## 12. Update the run log and commit
**Docs are updated BEFORE the commit, never after — and lessons get written down, not left in commit
messages where nobody finds them.** Three files, in order:

1. `docs/knowledge-base/personal/market/market-insights.md` — a dated entry: counts, what shifted in the market, rates seen,
   carryover verdicts, and any tool change made during the run. Standing instruction, unprompted.
2. `docs/knowledge-base/log.md` — **if anything was learned or fixed**, append it: what shipped
   (with commit hashes), the lesson and what it cost to learn, and any new open bug. Also close out
   entries in its "Open bugs" list that this run resolved.
3. `docs/operating/triage.md` — if tool *behaviour* changed. This runbook — if the *process* changed.

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
