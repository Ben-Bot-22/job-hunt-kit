# Log — what changed, and what it cost to learn

The running record for the whole repo: **what we learned and what it cost to learn it**, so the same
mistakes stop recurring. `docs/operating/` is the *how it works now*; this is the *why it's that way*.
Append a dated section per working session, newest first. Open bugs live at the bottom.

Named `triage-engineering-log.md` and filed under `docs/operating/` until 2026-07-30, when it moved
here — the scope was never triage-only, and it was buried among fourteen reference manuals. See
[the README](README.md) for what else belongs in this folder.

---

## 2026-08-06 — the publish path had a gate after the door, and a value with two owners

**What happened.** Evaluating the first publish since 2026-07-24, the repo's suite was green and a fresh
clone of the same tree read `2 failed`. Found only because the extraction was run into a throwaway clone
off-script — the checklist's cold-clone check was **step 6, after the push**. Run as written, the publish
would have shipped a broken first impression and then measured it.

**Three fixes, and only one of them is a bug fix.**

- **`triage/store.py` resolves the corpus path per call.** `SEEN = CORPUS_DIR / "seen.json"` was bound at
  import, so a test redirecting `config.CORPUS_DIR` at a temp directory redirected the readers and not the
  writer. `triage/test_merge.py` (2026-07-31) did exactly that and wrote three fixture ids into the live
  `data/corpus/seen.json` — a month of judgments, and the one directory `AGENTS.md` says must survive —
  and on a clone created a `data/` that made `triage/test_paste.py` fail. `CORPUS_DIR` is now the single
  knob; the two tests that also patched `store.SEEN` no longer need to know it exists.
- **`needs_profile` on `triage/test_unscored.py`.** Added 2026-07-30, it calls `analyze()` for real,
  which injects the rubric — green on the owner's checkout from day one and red on every clone since.
- **Model ids stopped having two owners.** `model()` was the ONE accessor with no code-side default
  (`cfg()["models"][role]` raised), so every settings file had to spell all five ids out, so
  `config/example/settings.yaml` carried a second copy. On 2026-07-29 `analyze` moved to Sonnet on cost
  here and the example kept an older Opus: for a week every new user's default was a model nobody had
  chosen. Now `core.settings.DEFAULT_MODELS` owns them, `core.settings.model()` is the one accessor
  (`cv/` used to reach into the settings dict directly — a third site), the example names none, and two
  tests hold it. The publish checklist's *"diff the two settings files and use your judgement"* step is
  deleted, because it was the thing that failed.

**The lesson, and it is about process rather than code.** *A check that runs after the irreversible step
is a receipt, not a gate* — the cold-clone check is now step 5 and the push is step 6. And *a value
duplicated across two files with a human diff between them will drift*; the fix is to move it into the
code, never to sync the copy. Both are written into `.claude/skills/publish/SKILL.md`, which also grew a
**step 0 (required reading)** and a **publish log** — because the same session burned Ben's time asking
him two questions the repo had already answered in writing: whether the open-source product was
incomplete (it is not — `config/example/` is a complete seeded configuration) and how far to scrub his
name (`scripts/publish-denylist.txt` defines what personal means and deliberately excludes the first
name). The reading list is the mitigation; the log is so the next publish starts from this one.

---

## 2026-08-06 — the rubric learns which lane Ben actually wins in, and it is not the years number

**What changed.** Three prose edits to `profile/rubric.md`, no code and no test. Market feedback said
Ben competes better for mid-level roles than for senior ones, and the apply doc was not reflecting it:

- **IDEAL ROLE grew a `MID-LEVEL IS THE PREFERRED LANE` bullet.** Mid titles and roughly-3-6-year bars
  score at the top of their band. He can only send so many applications a day, so the ranking has to
  put the winnable ones where he reads first.
- **DOWNRANK grew `SENIOR ROLE DEMANDING TEAM LEADERSHIP`.** Ranks lower, `held_back_reason` stays
  `""`, tell quoted. **It excludes nothing** — Ben's explicit constraint: *"do not exclude roles - the
  changes are only reflected in ranking prioritization."*
- **The closing `CANDIDATE:` line was rewritten.** It opened "senior full-stack dev", and it is the
  last thing the analyzer reads before scoring — it was aiming the model at the wrong lane. It now
  names all three cases: mid is the strongest lane, senior individual-contributor is fully in play,
  senior-with-team-leadership is where the missing enterprise history costs him the interview.

**The correction that shaped it, and it is the whole point of the entry.** The first version of this
change turned the existing `7+ years is a caution` line into a verdict cap. Ben killed it with a fact:
he had just interviewed for a 7+ year req at Commence, and it was the *recruiter* who suggested a mid
role might fit better. **So the years bar is not the discriminator — the DUTIES are.** A senior title
over ordinary build-and-ship work is a pay band, not a different job. The rule fires on mentoring, a
named tech-lead responsibility, cross-team architecture ownership and direct reports, and on nothing
else. `EXCESSIVE SENIORITY BAR` was left exactly as it was.

**What it does not do.** Channel tier is still sort key #1, so an agency contract senior role still
reads above a direct-employer mid role — that is unchanged and Ben confirmed it is correct
(*"tiers are fine - agencies still win tier 1"*). This re-sorts *within* a tier. Frozen verdicts in
`seen.json` keep their old ranking until a job is re-analyzed.

---

## 2026-08-05 (evening run) — the run defaults stop asking, and a background agent blocked on a prompt nobody was there to answer

**What shipped.** Two workflow defaults changed, at Ben's instruction (*"when i say run triage we need to
make assumptions - i will tell you in the first message if i want to change anything"*):
- **`/job-triage` step 0 now syncs the applied sheet unconditionally** instead of asking. The ask was the
  guard against a stale dedup cache; the cost of asking is a blocked run, and the cost of a redundant sync
  is seconds. The auto-memory `sync-applied-before-triage` was rewritten to match — it had encoded the ask.
- **Step 2's browser preflight takes the connected browser and proceeds.** It previously opened with an
  instruction to tell Ben to quit the desktop app; that is now reactive, raised only when
  `list_connected_browsers` returns empty. This was already the standing rule in memory
  (`browser-pick-dont-ask`, 2026-07-29) and the skill had not been updated to match it.

**THE FAILURE, and it cost about fifty minutes of wall-clock: a background subagent blocked on a
permission prompt while the user was away.** Ben said "I am stepping away — handle it", so mail archiving
(step 5) was fanned out as a background agent. Its first `unlabel_thread` call raised a permission prompt.
Nobody was at the keyboard. The agent sat on the prompt while the rest of the run completed around it, and
the state on disk was **22 threads labelled `jobs-triage` and still in INBOX** — a half-applied archive that
looks identical to a stalled one. Two rules follow:
- **A step that can raise a permission prompt must not be backgrounded when the user has said they are
  leaving.** Either run it in the foreground before they go, or defer it to their return. Backgrounding is
  what turned a one-click approval into a fifty-minute stall.
- **Pre-approve the mechanical mail calls.** `label_thread`, `unlabel_thread`, `search_threads`,
  `get_thread`, `list_labels` are routine and already guarded by `triage/test_archive_guard.py` and the
  `_is_correspondence` / `has_human_display_name` filters. They are now in `.claude/settings.local.json`
  (untracked, globally gitignored). Ben, on the interruption: *"this wastes my time and my focused energy."*

**Second failure, same step: the archiving agent skipped the per-thread sender check.** It called
`get_thread` **once** across ~24 threads and the harness flagged it. The repo's rule — *nothing leaves the
inbox without a look at who sent it* — exists because Gmail archives per **thread** while the list is per
**message**. The outcome was verified clean afterwards (searched for any `jobs-triage` thread containing a
SENT message: zero; the Commence thread with a live 8/06 interview and the Sun Technologies recruiter both
stayed in INBOX), **but the check ran after the fact rather than before, which is the wrong order.** The
batch prompt for that agent needs the per-thread inspection stated as a step it must *show*, not a rule it
must remember.

**Third, smaller: a cover-letter agent reported a PDF it never rendered.** The Apex letter came back
reported as docx *and* PDF, and only the `.docx` existed — `make_cover_letter.py` needs an explicit
`--pdf` and the agent omitted it. Same failure as the TCS letter on 2026-07-31, so it is now twice.
Re-rendered by hand. The later SeatGeek letter agent was given "pass `--pdf` and verify both files exist on
disk before reporting" and complied, which is the wording the batch prompt should carry.

**Run result:** 96 analyzed · 34 couldn't-fetch · 23 mail threads archived · 4 résumés · 4 letters. **Six of
24 carried roles closed overnight, Mitratech (fit 85) among them** — a finished package built 8/03 and never
sent. Research killed both First American entries (one req, CA-residency-only) and demoted Syndesus (an EOR,
not the employer). Detail in `personal/market/market-insights.md`.

**Two bullet-bank additions were proposed by CV agents and NOT applied**, per the standing rule that only
Ben approves a claim about himself: a composite shared-library/factory-pattern line (Apex + SeatGeek both
wanted it), and a distributed-systems-debugging line from the event-loop-blocking fix. Both compose existing
`[high]` entries and extend nothing. Awaiting his yes.

---

## 2026-08-04 (evening run) — one client, five metros: what a posting count hides

**Nothing shipped in code this session; the findings are about how to read the output.** The 2026-08-04
intensity rule ran for the second time and needed no change.

**The lesson worth keeping: a posting count is not a req count, and the gap can be 5×.** Three of the
four agency contracts that scored today were the *same* Motion Recruitment req — identical $80–90/hr,
identical stack, identical "12+ years desired" bar — posted against Charlotte, Providence and Worcester.
Checking the corpus rather than the picks found two more cities for it, **Nashua NH and Boston**. Four of
the five are New England, which makes Charlotte the outlier and suggests a New England client with a
Charlotte site. Consequences, both acted on:
- **Only one package was built** where a naive read of the apply set would have built three. Applying to
  more than one of five postings from one agency reads as spray to a single recruiter.
- **The "hybrid" label is now suspect.** Five genuine hybrid offices for one small ML hire is an
  implausible footprint. That is a question to ask, not a fact to plan a relocation around.

**Research posted its highest kill rate yet: the build set went 11 → 6.** Worth recording because each
kill was a *fact the posting concealed*, not a taste judgment:
- **Scion Staffing, fit 82 → struck.** The end client is almost certainly OrthoMed Anesthesia, who posted
  the same req directly on 2026-07-20 where it scored **LOW_FIT 45**. The agency rewrite omitted the
  5-day-onsite Addison TX requirement that failed it. **A 37-point swing on one job**, purely from who
  wrote the posting. **The generalisable rule: an agency repost needs the same duplicate check against
  the corpus that a direct posting gets** — matching on company name alone will never catch this, because
  the company name is the thing that changed.
- **Netflix, 76 → 56.** Real Netflix (own Workday, JR41877), but SE5 is their 6–8+ year senior band at
  $388k–$558k. A brand-name req that scores well on stack and is unwinnable on level.
- **scalr, 74 → 62.** Not a company: `scalr.pro` is a nine-month-old solo recruiting shop, so the
  employer, stage and equity behind "$200k–$350k + early-stage equity" belong to an unnamed client. Also
  name-collides with the Terraform-automation Scalr that NetApp acquired in 2023.
- **4MindsAI's "reposted 2 hours ago" was false** — the same URL sat in `master-worklist-2026-07-06` at
  LOW_FIT 42. **Repost timestamps are marketing; the corpus is the record.**

**A documentation bug in yesterday's apply doc cost real work and was caught by the batch, not by a
human.** Brighterway and Jobgether had documents built on 2026-08-03 but no `Résumé:` line recorded, so
`cv.batch worklist` derived fresh dated folders, `existing` read false, and both would have been rebuilt
from scratch. This is exactly the failure the runbook's carryover rule warns about, one run after it was
written. **The rule needs to be checked at write time, not trusted:** after writing an apply doc, run
`cv.batch worklist` and confirm every carryover shows `existing: true`.

**The six résumé agents refused 52 grader fixes between them and accepted no false claim.** The pattern
worth noting is that the grader's pressure is *specific and repeated*: it offered four different vector
databases to name (plus a fictional "Firestore vector index"), pushed Google ADK on the one req where ADK
was the most-stressed must-have, and asked for invented metrics on every single job. One agent also cut a
claim nobody challenged — `& audit trails` came off a skills line because Firestore access tracking is
not a compliance audit trail and "would not survive ten minutes of questions." That is the standard
working as intended.

**Also learned, filed to the playbook by the agents themselves:** a *Desired* years bar is answered with
silence including in the letter (naming it is what turns a soft bar into a gate); a Google ADK req is the
rare one where GCP is the core rather than a translation, and ADK still stays off the page; "multi-agent
systems" is a different must-have from "agent orchestration"; and a disjunctive must-have list
("any/many of the following") inflates the absent count when the parser flattens it.

**New open bugs from this run:** a LibreOffice contention flake in `cv.batch fit`, and a stray
`research_stderr.log` at the repo root (removed). Filed under Open bugs.

---

## 2026-08-04 — intensity stops removing jobs and starts sorting them

**The rule that changed.** `intensity >= 4` used to set `held_back_reason: "intensity"` and pull a job
out of the ranked list. On the 2026-08-03 run that hid six roles for an explicit on-call duty, a 24/7
rotation, incident response with cross-team standards ownership, 20–30% travel, *"move fast, deploy
daily"* and *"fast-moving, execution-oriented"*. **Two of them (Mitratech, Commure at fit 85) were the
joint-highest-scoring jobs of the run, and one (Prosum, 76) was the only live remote agency contract
in it** — the channel that is priority #1 and that the run otherwise reported as empty.

**Why it was wrong, and it is an epistemics point rather than a change of taste.** Ben, 2026-08-04:
*"work life balance is desired - and important for sorting. it is still priority #2, the issue is that
you are infering from text snippets that are not enough evidence… you should not skip them. you should
just rank them lower and name the suspect wording."* Intensity is the least reliable number in the
analysis — inferred from prose, no ground truth — and it was the one making the most irreversible
decision on the page. The same session had already produced the case in miniature: U.S. Bank scored
intensity **2** off its posting and turned out to carry a two-week 24/7 pager rotation. The number is a
hypothesis in both directions.

**What it became.** Intensity 4–5 now sorts a role below equal-fit sane-hours roles inside its own
tier and prints the quoted tell on its line (`_hours_risk`, `_hours_note` in `triage/worklist.py`).
Work-life balance stays priority #2; it just sorts instead of excludes. Two criteria still hold a role
back, both narrow on purpose:

* **`travel`** — a new vocabulary token, for a percentage the posting *states* above the rubric's
  threshold. It earns its own token precisely because it is checkable rather than inferred.
* **`intensity`** — re-scoped to a posting claiming the whole person. BJAK remains the calibration bar
  and nothing milder qualifies.

`_is_held_back()` is now just "did the scorer name a gate" — the second, independent route in (the
bare threshold, which overrode whatever the scorer had recorded) is gone. The old backfill that filed
a blank-reason intensity-5 record under `intensity` went with it: re-deriving it would have kept
hiding exactly the roles this change exists to surface.

**No cap on the apply set** (`/job-triage`). Ben: *"i want optionality and some days are slower than
others so that argues against a cap."* Rank honestly; he decides how many to send.

**What is left out now, in full** — the question worth being able to answer in one breath: the factual
SKIPs (non-US, rate under $40/hr, clearance, drug test, stack mismatch), roles he could not *win*
(non-engineering shape, mandatory-tech gap, 10+ year bar), `no-content` postings with nothing to tailor
against, and travel over his threshold. Ben: *"low fit might be the only reason to exclude… whatever i
apply to - i should be marketable for."*

**The threshold lives in the rubric, not the prompt.** First cut hardcoded Ben's 40% into
`triage/analyze.py`, which *ships* — and would have overridden the example seeker's own stated 10%
limit. Caught by the export check. The prompt now reads the number from the injected goal profile, and
`config/example/rubric.md` states its own; change it there and the tool changes with it.

**Two long-red tests fixed rather than tolerated**, since both were photographs rather than rules:
`triage/test_config.py` asserted the rubric still had a `HARD FILTERS` section that a restructure had
renamed `DISQUALIFIED`, and `scripts/test_extract.py` pinned `.claude/scheduled_tasks.lock` — a file
that exists only while a scheduled task runs — in an exact-equality set, so it was red on any clean
tree including a stranger's clone. **Suite is 765 passed / 0 failed, the first fully green run in
this log.**

No ticket and no new tests beyond the two that replace what the change retired, at Ben's direction.

---

## 2026-08-03 (later, same day) — a triage run, and three gaps it exposed

A normal 4-day run (220 analyzed, 9 packages built) that changed no code, but surfaced three things
worth writing down before they are re-derived.

**1. The cover-letter renderer can report success having written nothing.**
`cv/scripts/make_cover_letter.py → to_pdf()` prints `wrote <path>.pdf` on the strength of
`subprocess.run(..., check=True)` returning 0. LibreOffice on a cold start exits 0 having converted
nothing, so the line is a lie and the previous PDF (or no PDF) survives. This is **exactly** the
failure `cv/test_render.py` pins for the CV renderer — *"a PDF render that wrote nothing fails loudly
instead of returning the previous one"* — and the cover-letter path has no equivalent existence check.
Found by a batch agent during Step 10; it re-ran `soffice` by hand and the PDF exists. **Not fixed
here on purpose:** it is a code change and wants a ticket and a test, and this session was a run.
Filed under Open bugs.

**2. LinkedIn's location field is wrong often enough to be untrustworthy, and it is biased.** Three of
nine researched roles were mislabeled, all in the same direction — every error made the role look
*worse* than it is (Citi "onsite" → hybrid 3/2; Expedia "on-site" → hybrid 3 days; Dayforce "Oklahoma
City" → remote-US, a geo artifact of the logged-out view). Since location feeds the rubric's
location-tier demotion, the scorer is **systematically under-ranking hybrid and remote roles whose
location it read off LinkedIn**. No fix proposed yet; the cheap mitigation is that company research
already checks the employer's own board, so the correction lands in Step 8. Worth considering whether
`liveness` should also reconcile location while it is on the page.

**3. 23 job-shaped links were seen and never fetched**, because their hosts are not in the fetcher's
`_JOB_HOSTS` allowlist: `www.indeed.com` ×12, `apply.indeed.com` ×5, `www.dice.com` ×2,
`recruiting.paylocity.com`, `prod.url.paylocity.com`, `email.mail.paylocity.com`, `tracking.icims.com`.
The warning already names them and tells you to add them. Note that Indeed and Dice are *already*
walled to us (Cloudflare / 403), so adding them buys queue entries rather than JDs — but Paylocity and
iCIMS are first-party ATS hosts and should fetch fine.

Also worth recording as an operational fact rather than a bug: **the agency-contract channel returned
nothing usable this run** — four roles scored, three were already dead when opened, the fourth was a
LOW_FIT with a 10-year bar. The whole apply set is permanent. Channel is priority #1 in the rubric, so
a repeat would be an argument for widening `core/scrapers/` rather than waiting on the current seven.
Detail and rates in `docs/knowledge-base/personal/market/market-insights.md`.

---

## 2026-08-03 — the analyzer now bills a Claude subscription instead of the API key

The API bill was going to a subscription that was already paid for and under-used. Measured the split
before touching anything, because "reduce API cost" has an obvious wrong answer (move everything) and
a much better narrow one: **`analyze` is roughly 43% of the calls and ~70% of the spend**, prefilter
is ~18% of spend across the largest call count, and the CV roles are the rest. Cost is concentrated;
volume is not. So only `analyze` moved.

**What changed is the transport, and nothing else.** New `claude_cli` provider in `core/llm.py`
shelling out to `claude -p`, reached through a new `llm.cli_roles` setting rather than `llm.provider`
— per-role because the trade differs per role. Same prompt, same schema, same per-call-site
fallbacks; the call site cannot tell which transport answered.

**Two things were measured rather than assumed, and both could have killed it.** (1) `claude -p
--json-schema` reaches the same native structured output `method="json_schema"` does, and the
envelope carries an already-parsed `structured_output` object — this is not JSON scraped out of
prose, so the argument in `research-structured-output.md` still holds. (2) A fresh process per job
sounds like it would re-bill the ~5,200-token rubric every time; it does not, because the prompt
cache is keyed on **content**, not on a session. Second and later calls in a run reported
`cache_read_input_tokens: 9525` against a 385-token write — the same economics `analyze.py`'s
`cache_control` marker already bought. Eight concurrent calls: 15.9 s wall, 8/8 valid, no rate-limit
errors; a single call ~9 s, comparable to the API path.

**The failure mode this could have had, and the test that now prevents it.** `api_key_for` calls
`load_dotenv`, which lifts `ANTHROPIC_API_KEY` out of `.env` into `os.environ` for the whole process —
so by the time a run reaches the analyzer, a sibling call site on the `anthropic` provider has already
put the key somewhere a subprocess inherits it. `claude` **prefers an API key over its stored login**,
so inheriting one does not error: it succeeds, bills the API, and is indistinguishable from a working
subscription call. The saving would simply not have happened, silently, and nothing in the run summary
would have said so. `core/llm.py:_cli_env()` scrubs it and `core/test_claude_cli.py` pins that.

Same shape of trap in the CLI's own flags: **`--bare` reads as the lean option** (it disables hooks,
plugins and CLAUDE.md discovery — exactly what this wants) and in the same breath makes auth *strictly*
`ANTHROPIC_API_KEY`, OAuth never read. It would put every routed call back on the bill while looking
like an optimisation, so there is a test asserting it is never passed.

**Why the cheap roles deliberately stayed on the API.** A subscription costs a **rate limit** where a
key costs money, and 2,000 prefilter calls a month would compete with interactive Claude Code sessions
to save a few dollars. Keeping them there also means the API path runs every single morning, so it
cannot rot unnoticed for the stranger whose clone has only that one. Flipping one over later is
editing `cli_roles` in `config/settings.yaml` — no code.

Verified end to end through `analyze.analyze()` on a real job shape: 8.7 s, `analysis_errored=False`,
PRIMARY/STRONG_FIT/fit 90, rate, cadence, employment_type and `is_agency` all populated, intensity 2
rather than the default-3 shrug. Suite: 761 passed, 3 failed — the same 3 that failed before this
session (`test_the_rubric_still_has_its_sections`, `test_no_live_cache_key...`,
`test_the_real_tree_buckets_are_pinned`), confirmed by stashing and re-running.

---

## 2026-07-31 — a worklist rendering bug was silently dropping correspondence jobs entirely

1-day triage run (88 analyzed, 17 archived, 9 researched, 9 résumés, 9 letters). Two things worth
recording beyond the routine run.

**The worklist was losing jobs, not just mis-sorting them.** Investigating why the log's "held back 13
job(s) from human correspondence" didn't match the rendered "📬 Live correspondence" section (only 2
entries), the actual state file showed 7 correspondence-flagged jobs, 5 of which scored SKIP. Those 5
weren't in Live correspondence (a stale verdict filter excluded them), weren't in the ranked list
(correspondence jobs are pulled out before ranking runs), and weren't in the rejected/review section
either (also pulled out before *that* split runs) — they rendered nowhere. Same root cause and same
shape as the 7/30 log entry already flagged as an open bug, just found the hard way (by querying the
state JSON directly) rather than trusted from the rendered file. Fixed in `triage/worklist.py` — see
Open bugs below for the full writeup, including a second related bug (`--merge` never had the archive
plan to pass to `render()`, so a merge silently dropped the HELD BACK section too) found and fixed in
the same pass. Both pinned by new tests; full suite passes except one pre-existing unrelated failure
(`test_the_rubric_still_has_its_sections`, confirmed present before these changes too — a rubric
restructure elsewhere dropped its own `HARD FILTERS` heading name, not something this session touched).

**A liveness check killed the run's own top pick.** Infosoft's Full Stack Developer scored fit 81
(STRONG_FIT, the highest of any fresh posting this run) but had gone to "No longer accepting
applications" by the time it was hand-checked in Chrome before building a résumé for it. Dropped rather
than recommended — the same discipline as the carryover-verdict check, just applied to same-run picks
too. Worth remembering: a fresh fit score is a snapshot of the JD at scoring time, not a live status.

## 2026-07-31 — the rubric's skip list has a name and a marijuana disqualifier now

An Optum/UnitedHealth Group posting disclosed a pre-employment drug test. Ben uses marijuana, holds an
Oklahoma medical card, and is not quitting — pulled UHG's own OK and MN drug-testing addenda directly
to check whether either state carve-out helps: neither does. Both give procedural rights only (retest
window, access to records); Minnesota's rehab-before-discharge protection is for employees, not
applicants. The base policy rescinds any applicant's offer on a positive test, full stop. Confirmed
skip, not inferred.

**What changed in `profile/rubric.md`.** The old `HARD FILTERS (verdict = SKIP): ...` line was one
run-on paragraph — five reasons comma-spliced together, easy to misread or silently drop one while
editing. Ben asked for a `DISQUALIFIED` section with each reason broken out and named, specifically so
this stays auditable. Renamed and restructured, and added **drug test**: a disclosed pre-employment/
random screen with no marijuana exemption is a skip. Silence on drug testing does not fire it — only an
explicit disclosure does, same shape as the other filters (each fires on a stated fact, never an
inference).

## 2026-07-31 — the résumé now translates GCP into whatever cloud the JD names

Ben, on the Motion Recruitment Boston CV: *"they list aws in their jd — if aws is in their jd I need
AWS translations from my GCP experience... update the cv process to ensure we are mapping to whatever
cloud is requested."*

**What was wrong.** A playbook rule written the day before — *"Never put a cloud-translation line on
the résumé"* — classified `GCP maps to AWS: Cloud Functions→Lambda, …` as *defensiveness in any
costume* and cut it. The blind grader asked for the mapping back on all three passes of that run and
was refused all three times, and the refusal was recorded in the playbook as house style outranking
run-to-run noise. **The grader was right.** The rule misread the mechanism: the clause is not a
rebuttal to a human screener, because a résumé is string-matched *before* a human reads it. A document
that never contains the token `AWS` does not reach the person who would have appreciated the honesty.
It is the same ruling Ben already made about `eval` in the bank — *"you need the keyword match"* —
which the cloud rule had contradicted without noticing.

**What replaced it, and the seam that keeps it honest.** The mapping lives on the **Cloud skills
line**, with his vendor as the subject and the requested cloud's names in parentheses:
`Google Cloud — Cloud Run, Cloud Functions, Cloud Storage, Pub/Sub, Firestore (AWS equivalents:
ECS/Fargate, Lambda, S3, SNS/SQS, DynamoDB)`. A skills line is an inventory of vocabulary; a bullet is
a sentence about work done. **So an AWS service name in a bullet or the summary is a false claim**, and
that is now a test rather than a note — `cv/test_claims.py::test_no_cloud_claim_in_an_experience_bullet`
walks `experience[].bullets` and `summary` structurally, because the existing flattened `_plan_text`
check cannot tell a claim from an inventory. Azure is deliberately outside that pattern: the bank has
real evidence (multi-provider TTS benchmark collection from Azure + Google Cloud TTS), and the list
bans what is provably unbacked rather than every foreign vendor.

**Measured on the req that prompted it.** Motion Recruitment (Boston, TypeScript + AWS): AWS moved
`absent → skills_only`, absent count 1 → 0, still one page. `keyword_coverage` stays at 3 — the grader
wants a *bullet*, which would require inventing the work, so 3 is the correct ceiling for this req and
not a defect. The grader's own fix to split the dense `Cloud & Data` line into `Cloud` + `Data` was
taken; the parenthetical had been swallowing the middle of it.

**Ben's scoping, which arrived mid-rebuild and is the rule that matters:** *"my intent is only
services … like the equivalent of what i used on GCP."* The mappable set is exactly his GCP surface —
Cloud Run, Cloud Functions, Cloud Storage, Pub/Sub, Secret Manager, Firestore, Vertex AI. Nothing else
gets a counterpart: `CloudFormation` and any other IaC has none in the evidence and stays a
cover-letter gap. And **one target cloud per req, never a matrix** — a first pass wrote combined
`AWS/Azure equivalents:` clauses onto the four reqs that list all three clouds, which is bloat (a req
naming GCP is already satisfied by it) and pushed two one-page résumés to two pages.

**Two collisions with standing rules, both resolved in favour of the older rule.**
`Google Vertex AI / Gemini (Azure OpenAI / AI Foundry equivalent)` tripped `cv/test_claims.py`'s
OpenAI ban — Ben's standing call that OpenAI is not on any document. **A standing ban outranks a
keyword match**, so the clause became `(Azure AI Foundry equivalent)` and the OpenAI half is a
cover-letter gap. The second: the mapping never touches a bullet, which is the seam the new test
enforces.

**The nine rebuilt, cloud-mapping edit only — no re-tailor.** All ten now render at one page. Apex and
Mercury needed wording trims to get back under (both were already tighter than the documented max
squeeze, so there was no `tighten` headroom; redundant parentheticals went first, per the playbook).
The token now lands: `AWS` reads `skills_only` on chenmed, imcs, openworks, mercury and Motion where
it read `absent` before. **What it does not do is move the grade** — `keyword_coverage` sat still,
because the grader scores *evidence* and correctly refuses to credit a mapping as work. Ranger's
`AWS Bedrock` is still graded `absent` with the token visibly on the page. That is the honest split
worth remembering: **the mapping wins the string match, not the screener's judgement**, and it was
never going to win the second.

Changed: `profile/bullet-bank.md` (new DO-NOT-CLAIM entry — Ben approved),
`docs/knowledge-base/personal/tailoring-playbook.md` (rule reversed, new *Cloud translation* section),
`.claude/skills/tailor-cv/SKILL.md` §3, `cv/test_claims.py`, and ten application folders' `plan.json`
/ `README.md` / renders.

---

## 2026-07-30 — the triage run now ships a full application package, and the apply doc became a machine interface

Ben: *"we want it to do the triage, generate cv for top 10, generate company reports for top 10,
generate cover letters for the top 10"*, and then *"after the company reports you should revisit
rankings at the end with the new info and update notes on the triage document."* `/job-triage` went
from nine steps to thirteen: research (7) → re-rank the apply doc in place (8) → résumés (9) →
letters (10). Only `/job-triage` changed shape; `/research-company`, `/tailor-cv-batch` and
`/cover-letter` are called unmodified.

**No new skill, and no rename.** Folding letters into `/tailor-cv-batch` would have made its name lie,
and a fourth fan-out skill beside three that already fan out is the second-home failure `AGENTS.md`
records. The run orchestrates the three that exist.

**Research runs before the documents, not after.** It is the step that changes *whether to apply at
all* — agency rather than employer, the same req shopped under three names, a company already on the
skiplist. Learning that after ten résumés are built wastes the ten. It is also `/cover-letter` §1's
stated prerequisite. Letters then run after résumés rather than beside them, because the skill
requires the letter to read that job's `plan.json`: the two documents go in the same envelope.

**The cap is a ceiling, not a quota** — "worth applying to, capped at 10", Ben's wording. A run that
recommends four jobs gets four packages. Padding to a fixed ten manufactures work on roles that did
not clear the bar, and the value of the list is that every row on it is worth his morning.

**The real defect this exposed: `cv.batch worklist` was section-blind.** It returned *every* unticked,
un-struck checkbox in the apply doc — including `📬 Reply, don't cold-apply`, which holds processes
already in motion, where a cold application cuts across a live conversation. That was survivable while
a human eyeballed the list and picked three to five; it stops being survivable the moment the batch
takes the top ten as given. Also swept in: the mail audit block and the "couldn't fetch" list, both of
which Step 6 requires the doc to carry and both of which are checkboxes.

`worklist()` now classifies each `##` heading, and **an unrecognized one raises** — the same reasoning
as `scripts/extract.py`'s default-deny allowlist, because both guesses are wrong: treat it as work and
the run builds documents for jobs he must not cold-apply to, treat it as audit and the run silently
builds none and reports success. Plus `--top N`.

**What the run against the ten real apply docs taught, and it changed the design.** The first
implementation used a narrow allowlist (`tier|carryover`) and raised on `matches/2026-07-29.md` and
`matches/2026-07-30.md` immediately: the heading vocabulary is *invented fresh every run* — `▶ Focus
today`, `PRIMARY — agency contract`, `Submit today — cost is near zero`, `Where I'd not spend
attention`. Two fixes, both needed. **A `###` subsection now inherits from the `##` above it** (`###
Strong, but each needs a move` under `## Tier 2` means nothing to a word list, but its parent already
answered), so only a top-level section nobody can classify raises. And **Step 6's `##` vocabulary is
now fixed and stated verbatim in the skill**, because that file stopped being prose for Ben alone the
moment three stages took their work list from it. All ten historical docs parse; the four from before
the checkbox format return 0, correctly.

**Also fixed in Step 6:** role titles must carry no leading number. `matches/2026-07-30.md` wrote
`1 · Lead AI Engineer`, which the parser slugs into a folder called `1-lead-ai-engineer`.

Letters: all of them render, but **only the top three bodies get pasted into chat**. Ben rewords from
chat rather than by opening the docx, so the top ones must be there — and ten letter bodies in one
message is a wall nobody reads, which defeats the purpose of pasting them at all.

Shipped: `cv/batch.py` (section classification, inheritance, `--top`), `cv/test_batch.py` (+3 tests),
`.claude/skills/job-triage/SKILL.md`, `.claude/skills/tailor-cv-batch/SKILL.md`,
`docs/operating/triage.md`, `AGENTS.md`.

## 2026-07-30 (later) — a 1-day agency check, and a correspondence section that renders empty on purpose

Ben asked for a narrow `--days 1` run (last run 7/29 14:45) — mainly an agency check, plus mailbox
cleanup, while he worked down the 7/29 apply doc's top 13 separately. 100 analyzed · 97 skipped
pre-eval · 38 couldn't-fetch · 17 emails archived (0 skipped) · 5 résumés built.

**Bug found: the worklist's "📬 Live correspondence" section can silently render empty even when the
run held mail back from archiving.** The terminal log correctly reported
`archive: held back 2 job(s) from human correspondence — never auto-archived`, and neither of the two
threads (a Motion Recruitment follow-up on the College Board process; a Future Point of View
post-interview thank-you) leaked into the archive list — the *safety* guard worked. But
`triage/worklist.py:219` only renders a job into the correspondence section when
`j.from_correspondence and j.analysis and j.analysis.verdict != "SKIP"` — both held-back jobs scored
SKIP internally, so they vanished from every rendered section, not just correspondence. Nothing in the
worklist told the reader two emails existed that needed a look. Caught by searching Gmail directly for
the window rather than trusting the worklist's silence — the identical failure shape Ben named on
2026-07-29 ("data slipping through... need to be able to audit you"). Filed as an open bug below.

**Confirms the agency channel is the dominant 1-day supply, as expected**: 568 of ~721 raw candidates
(Insight Global 473, TEKsystems 32, Mondo 15, Apex 38, Motion 4, Kore1 6) against 153 from mail and 0
from boards — see `docs/knowledge-base/personal/market/market-insights.md` for the dated numbers.

**A high-rate agency contract still needs a résumé-fit check, not just a rubric score.** Pacer Group's
Lead AI Engineer scored highest on channel+rate this run ($58-69/hr contract) but the tailored résumé
came back below the reviewer's bar on two dimensions — 6 of 14 must-haves (GKE/Kubernetes hands-on, IVR,
contact-center/voice-bot domain) are honestly unclaimable from `profile/bullet-bank.md`. The rubric's
priority order ranks this pick #1 on channel; the résumé build is what surfaced it's actually a stretch.

## 2026-07-30 — a twelve-CV batch, and a stale-PDF bug that grades text nobody wrote

Twelve tailored CVs built concurrently off the re-sorted 2026-07-29 apply doc (one agent per job,
`/tailor-cv-batch`). Two findings outlived the run.

**The bug: `render_cv.py:to_pdf` can silently grade a stale PDF, and a batch run is exactly when it
fires.** `to_pdf` shells out to `soffice --headless --convert-to pdf` with `check=True`, then guards
only on `if not pdf.exists()`. When another LibreOffice instance already holds the lock — routine with
N concurrent agents — **soffice exits 0 without writing the file**, and the guard passes because the
*previous* render is still sitting there. Two agents independently caught it: one graded a PDF 46
seconds older than its docx and quoted three lines it had already deleted. Both worked around it by
`rm`-ing the PDF before each render; neither changed code.

The failure mode is not a crash, it is **a passing score for text that does not exist** — the same
shape as the scraper rot in the 2026-07-24 run, where the tool failed by returning something plausible
rather than by raising. Final deliverables in this run were verified current (every PDF mtime newer
than its docx); what cannot be reconstructed is which *intermediate* passes were graded stale.
Fix candidate: capture the docx mtime before conversion and assert the PDF is newer, or unlink the
target first. Listed under open bugs.

**The reviewer's fix list is an adversary on exactly two axes, and it is consistent about it.** Across
twelve independent runs the grader asked for a forbidden or invented claim in every single one, and the
requests clustered hard: **SQL/Postgres** (asked in 6 runs), **invented metrics** — p95 latency, cost
percentages, documents processed, test counts (asked in all 12, 4–6 times each), **CI/CD** (3 runs, a
standing DO-NOT-CLAIM), **naming a vector-DB product** where the store is an in-memory numpy index
(4 runs), and **OpenAI alongside Anthropic** (3 runs). Two agents were asked to restore the GCP→AWS
translation clause the playbook banned on 2026-07-30 — which that playbook entry had explicitly
predicted. Every one was refused and reported. **The grader is useful and it is not a principal:** the
bank and Ben's stated preferences outrank it, and the refusal list is what makes running it safe.

**A third thing the batch measured that no single run can see: the same gap surfaced five times.**
Independent agents on Garmin, Optum, Rula Health, Mercury and ChenMed each proposed some form of
*technical documentation as a claimable practice*, and each found it stated as a required
qualification. The bank answers it today with a skills-line keyword and no bullet. Five reqs is not a
coincidence; it is the strongest signal this repo has produced that a bank gap is costing applications.
Proposed to Ben with evidence, unwritten — the bank is protected and no agent writes to it.

Two ranking corrections the JDs themselves forced, against a doc that had scored them from run
summaries: **Instrumental Group's HubSpot "gate" does not exist** (the posting says twice that HubSpot
experience is not required and training is provided; the real gap is agency collaboration).
**Torch.AI's clearance is not the rubric's hard skip** — "*some* roles require" plus explicit
sponsorship for eligible candidates, which is conditional, not required. Both had been treated as
disqualifying on title and company alone. The lesson is the one already in AGENTS.md about scraper
counts, in a new place: **a summary that can outlive its correction is worse than no summary** — read
the posting before you rank the job.

---

## 2026-07-30 — an eleventh system (submission), and why an agent must never close a browser tab

`/apply-form` is a new skill and the eleventh system. It drives an in-progress online application in
Ben's own browser, one page at a time, with him approving each page.

### It exists because the ATS parse is what gets screened, and it is always wrong

Filling in a Workday application for Link Logistics, the "autofill with résumé" step turned one résumé
into **five jobs**: it invented a job title out of a bullet fragment (*"Sole developer"*, blank employer),
used one job's title as another's employer (*Independent Game Developer* at *"Economist — US Air Force"*),
read two locations as employers, ticked *"I currently work here"* on all five including four that ended
years ago, and **promoted a BBA to an MBA**.

**The degree is the one that matters, and it is a different kind of error from the rest.** A mangled
employer name is embarrassing; a bachelor's rendered as a master's is a false credential, and the moment
the page is saved it stops being a parser artifact and becomes something Ben asserted. So the skill's
first instruction is to audit the parse against the rendered CV rather than tidy it.

The general lesson: **the attached PDF is not the application.** The parsed fields are, because that is
what a recruiter reads. Tailoring the document and then letting a parser rewrite it undoes the work.

### Two browser rules bought the same afternoon

- **Never close a tab in the MCP group.** Closing the one tab the extension had created tore down the
  whole group, taking with it the application tab *Ben* had added — twice. The mechanism is inferred
  (the session appears to be anchored to the extension-created tab, not to the visible Chrome group) and
  the skill says so rather than asserting it. The rule holds either way: **the seeker manages tabs.**
- **Never navigate their tab to "get back in."** Doing that opened a *second* application flow at step 1
  while the real one sat at step 3. Workday keeps one draft server-side, so a duplicate tab is a way to
  overwrite progress, not to recover it. The recovery is to say the tab was lost and ask for it back.

### Where the data went, and the rule that keeps it honest

`docs/knowledge-base/personal/links.md` already held the five links a form asks for — the agent that
went looking found them rather than creating a second home, which is the failure this repo has recorded
before. The one genuinely new fact was **years of experience: 5+**, and it landed there with its scope
spelled out: **a form answer is not a document claim.** `bullet-bank.md` → DO-NOT-CLAIM forbids a years
number on the CV and `cv/jd_parse.py` drops years bars from the brief; a required *Years of experience*
field is a different artifact that a résumé rule cannot answer. Both rules now hold without contradicting
each other, which is only true because the distinction is written down next to the number.

Enforcement rode along: `OWN` in `core/test_portable_workflows.py`, `OWN_SKILLS` in
`scripts/test_extract.py`, the §1 table and a new §11 in `systems.md`, and the heading in `AGENTS.md`.
Suite green at 741.

---

## 2026-07-30 — a tenth system (evaluation), and a map so an agent can find the other nine

Ben, mid-session: *"you have been very confused lately and you need to be more competent with navigating
and understanding this repo."* He was right, and the diagnosis is specific rather than general.

### What was actually missing

`docs/operating/services.md` answers *what does it talk to*. `data-map.md` answers *what does it write*.
**Nothing answered *which system am I in, and what is its anchor?*** — so an agent orienting itself had
to infer the capability map from a services table, a path table, and a rules file. Three times in one
session that produced the wrong move: proposing to bolt a new workflow onto the triage protocol, then
onto the knowledge base proper, before Ben corrected it to a separate system.

`docs/operating/systems.md` is the answer, and **`CLAUDE.md` imports it** (`@docs/operating/systems.md`)
so it loads every session rather than being one more file nobody fetches. That import is the whole
point: the repo's own recorded failure mode is *a stale value that loads automatically beats a current
value that must be fetched*, and the corollary is that a **correct** value that must be fetched loses to
nothing at all.

It is enforced. `core/test_service_map.py` gained a check that the map names every root Python package,
every workflow in `OWN`, and the three anchor files — inventories only, no prose. Its `RULE` line was
widened to cover all three orientation pages, and it imports `OWN` from `core/test_portable_workflows.py`
rather than keeping a second list.

**Measurements taken while writing it, all of which were doc rot:**

* `AGENTS.md` said *"all six are skills"* and listed **seven**. On disk there were **eight** — the list
  had never gained `/cover-letter`, which the same file describes in prose two sections earlier.
* `services.md` §7 said *"the five workflows"* and named five.
* `scripts/test_extract.py` and `core/test_portable_workflows.py` each keep their own product-skill list.
  Both were correct at eight; both had to be edited for the ninth. **Not consolidated** — they test
  different things (extraction bucketing vs. skill format) and importing one test module into the other
  across the `scripts/`↔`core/` boundary buys less than it costs. Noted here so the next person knows it
  is deliberate and that there are exactly two.

### The tenth system

Ben: *"I am going to be applying and asking you to evaluate — you need a process to run and you need a
place to record my preferences. This is using triage data but it is a separate system."*

**Evaluation** is now a peer of triage rather than a step inside it, and it is the second system with no
Python at all (`/cover-letter` was the first):

| | triage | evaluation |
|---|---|---|
| anchor | `profile/rubric.md` | `docs/knowledge-base/personal/roles/preferences.md` |
| process | `/job-triage` | `/evaluate-role` |
| output | `matches/<date>.md` | `personal/roles/<date>_<company>_<slug>.md` |
| unit | a posting in a queue | a session with Ben |

**The risk this creates, and the rule that contains it.** A second file about what Ben wants is exactly
the shape of the 2026-07-27 incident — an agent judged a role against a retired $115k floor because a
stale copy auto-loaded while the rubric had to be fetched. So: **`preferences.md` holds nothing
`profile/rubric.md` can hold.** No rates, floors, tiers or scores; if it needs one, it points. It is safe
only while it holds what the rubric structurally cannot express — how Ben is *screened*, how he wants to
be *advised*, and what he has already *settled*.

**The evidence it was needed** came from the same conversation. Ben asked whether a 60-minute pair-
programming hour was worth preparing for. He had already rejected Toptal on 2026-07-07 over a 90-min
Codility gate — *a preference about screening format, not about a job* — and the only record of it was a
`#` comment in `profile/skiplist.md`, a machine-read config file. Nothing surfaced it; the reasoning was
redone from scratch.

### The stale copy that was already there

`personal/calls/inbound-req-protocol.md` — the file that governs exactly these sessions — carried *"pay
is a ≥$115k threshold; energy for weekend projects + jiujitsu is #1"* in its **step 2, "before writing
anything"**. Both retired by `e4d9a8f`. It did not bite today only because `profile/rubric.md` was read
first. Struck and replaced with a pointer plus the reasoning, and the protocol gained a step 8 (record
the decision) — it had produced no artifact at all, which is why every assessment since 2026-07-14
evaporated with its thread.

### Also written

`personal/roles/2026-07-30_sift_swe-fullstack-agentic-ai.md`, the first role doc, doubling as the format
spec. Two findings in it are about the tools rather than the job and are worth carrying forward:

* **`/research-company` reported `Scored 0 (SKIP)` for a job that scored 80/FIT.** The 13:57 run hit a
  provider spend cap; the error path writes a `SKIP` stub with `fit_score: 0` and `analysis_error` in
  `why`. At the history layer that is **indistinguishable from a judgment**. Read the `analysis` block,
  and prefer the later run.
* **The company-research board lookup resolved the wrong company** — `Sift` → Ashby slug `sift`, which
  is Sift Science (fraud prevention), not siftstack. The same collision poisons review sites. A name is
  not an identifier; verify against the employer's own careers URL.

Neither is fixed in code. The first would want the history line to distinguish an error stub from a
judgment; the second would want board resolution to be confirmed rather than assumed. Both are recorded
in `/evaluate-role` as things the reader must check by hand, which is the honest state today.

---

## 2026-07-30 — one documentation root, and the privacy seam moved a level deeper

Ben asked why the repo is hard to maintain. The measurements: **13,215 executable Python lines against
24,719 lines of prose** (tracked `.md` plus in-code comments and docstrings), **57 test files of which
14 enforce a stated rule — and `AGENTS.md` named 4 of them**. Documentation was spread over `docs/`,
`profile/notes/` and a tracked `.scratch/`, so "where does this go?" had three answers and "is this
still true?" had none.

### What was actually wrong, and what wasn't

Two rounds of findings had to be retracted, and the retraction is the useful part. The first claimed
prose was the enforcement mechanism and rules should become tests — **false**: every rule that *can* be
a test already is one, and `core/test_single_path.py` opens with "There is exactly one generation path,
**as a test rather than a promise**". `AGENTS.md` phrased that same rule as a plea and never named the
test, so an agent reading the entry point infers a gap that does not exist. **Enforcement was invisible
from the only file that loads every session** — that is the defect, not missing enforcement.

The second claimed `docs/operating/` duplicated the skills. Partly false: the skills *cite* the
operator guide. What held up was narrower and sharper — of 12 operating docs, **the 4 checked by a test
had zero stale references and the 8 unchecked held every one of them.**

### The change

**One documentation root.** `docs/` is now the only place documents live. `profile/notes/` was emptied — 32 files moved to `docs/knowledge-base/personal/`, and the directory deleted. The four the tool referenced *by path*
(`tailoring-playbook`, `ben-voice`, `market-insights`, `links`) moved too: every reference turned out
to be a docstring or a test string literal, never a file open, so nothing had to stay behind.

**The privacy seam is now one level deeper, and that is the cost of the trade.** `docs/` ships whole,
so a personal subtree inside it needs the allowlist to name a nested path — the first time it has. The
shape follows `.claude/`'s existing precedent (`CLAUDE_CHILDREN`), and the mitigation against two
sources of truth is that there is exactly one: `extract.PERSONAL_SUBTREES` → `is_personal()`, consumed
by `_copy_ignore()` during staging **and imported by `scripts/test_leaks.py`** instead of restated.
Verified both directions before moving anything: a canary carrying the owner's name and address inside
`personal/` is absent from a staged extraction and passes the leak test; the identical file one level
up fails it loudly.

**Pruned.** `.scratch/` untracked (80 files, 11,716 lines — 41% of all documentation, and the
most-churned path in the repo). `docs/operating/` went 12 files → 8: `agent-workflow.md` deleted (zero
inbound references), `research-company.md` deleted (the skill is the live copy), `workflows.md` folded
into the README's *Which agent runs the workflows*, `triage-applied-sync.md` folded into
`triage-operating.md` — which is now `triage.md`, the single operator reference. `triage/README.md`
went 145 lines → 48 and points at it rather than restating it; its channel list had already rotted
("three built" when there were four plus a stub).

### The lesson, and it is the same one as the entry above

Last entry: *a rubric adjective is not an enforcement mechanism, and the two drift apart silently
because only one of them is executable.* This one is its documentation twin: **a document that makes
present-tense claims and is checked by nothing will drift, and confidence in the prose is uncorrelated
with whether it is still true.** The durable defence chosen here is fewer such documents rather than
more tests over them — Ben's call, and the right one for prose, which has no honest schema.

Open, deliberately not done: the rule→guard-test index for `AGENTS.md` (the fix that would have
prevented the first retracted finding), and `AGENTS.md:117`'s raw scraper counts, which are a
measurement sitting in a rules file three lines after it warns you not to trust exactly that.

---

## 2026-07-30 — work-life balance was 4th and dead; the BJAK assessment is what exposed it

Started as a small question — should Ben spend 2.5 hours warming up for a BJAK coding assessment —
and ended as the largest change to the priority function since the rubric was written. Full decision
record in [the work-life-balance decision](decision-work-life-balance-priority.md); this is what was learned.

### The rubric said "non-negotiable" and the code made it a no-op

`profile/rubric.md` had called low intensity (1-3) *"non-negotiable"* since it was written.
`triage/rank.py:34-42` sorted `tier → verdict → fit → intensity → completeness`, so intensity was the
**4th** key: it only fired when two jobs shared a tier, a verdict **and** a 0-100 fit score. That tie
essentially never occurs. And in `triage/analyze.py:59`, intensity 4-5 sat in a four-way bucket with
*permanent*, *adjacent-stretch* and *rate unknown* — **crunch cost exactly what a missing rate field
cost.**

So the file's strongest word sat on its weakest mechanism, for weeks, and nothing surfaced it. The
lesson generalizes past this one field: **a rubric adjective is not an enforcement mechanism, and the
two drift apart silently because only one of them is executable.** When the rubric makes a
non-negotiable claim, something in `rank.py` or `analyze.py` should be checkable against it.

### Two numbers that changed the design

Measured over 1,399 analyzed jobs from `data/corpus/state-2026-07-2*.json`:

**Rate is collected on 18% of jobs.** A real dollar figure appears in 18%; 9% say "undisclosed"
outright; **73% are completely blank.** The standing `UNDISCLOSED RATE → cap at FIT` rule was
therefore demoting four postings in five **for a field we fail to scrape** — it was measuring our own
collection, not the market. The cap is deleted. The `< $40/hr` floor survives untouched precisely
because it only fires on a real posted number: rare, unambiguous, no false positives. Lowering the
floor was considered and rejected — a rule firing on 18% of jobs does not widen a funnel by being
loosened.

**78% of jobs score intensity exactly 3.** 1,092 of 1,399. Only 44 score 1-2. The scorer was parking
on the default, which means promoting intensity to sort key #2 would have **reordered almost nothing**
and looked like a failed change. Hence the INTENSITY TELLS checklist in the rubric — concrete quotable
signals in both directions — and hence the shipping order: **rubric first, sort second.** The reverse
order produces a no-op and invites rolling back the wrong half.

That sequencing point is the reusable one. *Promoting a field in a sort is worthless until the field
carries signal*, and "does this field actually vary?" is a one-line query nobody had run.

### Held back — a third tier of "no", and the body-shop decision predicted it

Ben's constraint was explicit: *"I don't want you to skip — I want to see it, but it doesn't go in the
prioritized rankings, it gets a rejected-because section."*

the body-shop decision had already established the governing principle — **hard-skip when the criterion
is factual and checkable; cap when it is inferred** — and intensity is the most inferred field in the
analysis. So two independent lines, Ben's preference and the repo's own prior reasoning, arrived at
the same answer. What 0001 lacked was a tier for *"correctly scored, genuinely interesting, and
deprioritized anyway"*, which is what **held back** now adds: out of the ranked list, into its own
visible section, reason attached, nothing deleted.

### The reversal worth recording: enterprise is not a liability

The agent proposed downranking "enterprise-shaped" roles, reasoning that Ben's lack of enterprise/team
coding experience made them hard to win. Ben reversed it:

> "I want enterprise roles — enterprise is where work life balance is good — scoped tickets — these are
> highly desired — this is the wrong take away."

Two errors in one proposal. Enterprise means scoped tickets and sane hours, so downranking it would
have **fought the very change being made in the same edit**. And the missing enterprise credential is
what the career-bridge strategy exists to *acquire*, so treating it as a disqualifier inverts the goal.

**This is the second time in four days an agent proposed shrinking the funnel in the name of matching
Ben's preferences** (the first: 2026-07-27's onsite/rate skip on a stale memory). The standing
correction — now in the rubric — is that when a trade is genuinely his, surface it with the reason
attached rather than making it for him: *"you are a filter and prioritization tool. I need to see the
reqs to evaluate because the tool is imperfect."*

### Shipped this session

Config only (`profile/rubric.md`) — the code half is tickets 02 and 03 in
`docs/knowledge-base/decision-work-life-balance-priority.md`:

- Priority order stated at the top of the rubric for the first time: channel → **WLB** → fit →
  remote → rate.
- INTENSITY TELLS checklist, both directions, with the BJAK posting as the worked 5.
- Intensity 4-5 → HELD BACK, with the `held_back_reason` fixed vocabulary.
- UNDISCLOSED RATE cap deleted; rate demoted to a tiebreak; `< $40/hr` floor kept.
- Contract beats an equivalent perm again (retires the 2026-07-27 tiebreak-only rule, at Ben's request).
- Enterprise/scoped-ticket roles explicitly marked DESIRED so the reversal above cannot recur.
- Found in passing: `triage/analyze.py:62` says the rate floor is `< $50/hr` while the rubric says
  `< $40/hr`. **Still open** — fixed in ticket 02. The rubric is authoritative.

### The other half of the session: there was nowhere to write this down

Ben asked, twice, where the durable record of changes lived — because the first answer given was a
`.scratch/` ticket. That was wrong, and finding out why exposed a real gap:

- **`AGENTS.md` never mentioned this log.** It loads every session and named `docs/operating/` and
  `docs/adr/` only in passing, with the log invisible. **A convention that exists only in the
  directory listing is a convention no agent follows.**
- **Reasoning was scattered across three places** — this log buried among 14 reference manuals in
  `docs/operating/`, decision records in `docs/adr/`, and in practice whatever `.scratch/` ticket
  happened to be open.

Fixed by consolidating into **one flat `docs/knowledge-base/`** with four filename prefixes
(`log`, `decision-`, `research-`, `plan-`), a README stating the rule at the door, and a one-line
pointer in `AGENTS.md` — one line deliberately, because that file costs context on *every* session and
a 25-line table there was the wrong trade. `core/test_docs_layout.py` now fails if `docs/adr/` or
`docs/research/` reappear.

**"ADR" is gone from every file we own.** Ben: *"no acronyms allowed."* A decision note is now
`decision-<slug>.md` and says what it is without being decoded.

Two process lessons worth more than the reorganization:

- **`grep -v "a\|b"` silently matches nothing on macOS.** BSD grep does not support `\|` alternation
  in basic regex, so a filter meant to protect vendored skills and `.scratch/` filtered *nothing* and
  a bulk `sed` edited 13 files it should not have. Reverted via git. Use `grep -E`, and verify a
  filter excluded something before trusting it.
- **`for f in $VAR` does not word-split in zsh.** The same bulk edit silently no-op'd first time,
  passing the entire file list as one filename. Use `while IFS= read -r`.

### A stale reference is a broken promise, and three classes of them turned up

Auditing the moved docs surfaced references to files that do not exist. They are **not one problem**,
and the distinction is what decides the fix:

1. **Named in order to say it is gone** — `AGENTS.md:141` (*"the exception … `research/` importing
   `triage/fetch.py` … is spent"*), `inbound-req-protocol` (*"`ai_docs/…` (the directory does not
   exist)"*). The sentence is its own correction. **Leave these.**
2. **Named as current, in a document something still sends you to.** `research-cross-agent-portability.md`
   anchors its findings to `triage/ingest.py` and `triage/archive.py`, and **`setup/SKILL.md:266` and
   `research-company/SKILL.md:90` both instruct a reader to open it before changing portability.** The
   modules moved (`triage/channels/mail.py` + `common.py`, `triage/channels/gmail_api.py`), and its
   central finding — *the tool is macOS-only because one file shells out to `osascript`* — **is still
   true**. A reader who cannot find `ingest.py` may conclude the limitation was fixed. It was not.
   **Fixed with a dated header note that maps old path → new path and states the finding still holds**,
   rather than by rewriting the body: a research note is worth keeping only if it records what was
   actually measured against what code.
3. **A wrong name for a real safety net.** `core/settings.py:30` promised
   `core/test_settings_schema.py` guards schema drift. That file has never existed; the guard is
   `core/test_settings.py::test_the_published_schema_is_in_sync_with_the_model`. Anyone verifying the
   claim finds nothing and reasonably concludes the schema is unguarded. **One-word fix.**

### The memory audit: a third of it described a repo that no longer exists

Same failure class, outside the repo. The auto-loading memory store held 32 entries; **nine distinct
paths they cite are gone** — `main.py`, `scripts/add_*.py`, `scripts/backfill_descriptions.py`,
`.claude/commands/`, `cv/bullet-bank.md`, `cv/tailored/`, `triage/data/applied.json`, `ai_docs/`,
`jobsdb/`. Concretely: one memory warned against importing `jobsdb/` (deleted); one protected a column
in a Google Sheet whose pipeline was deleted; one said `/tailor-cv` lives at
`.claude/commands/tailor-cv.md` — **a path `core/test_portable_workflows.py` fails the suite for
creating**; one guarded fetching by naming three scripts that no longer exist, while not naming
`python -m triage`, which is the thing to guard.

**13 deleted, 2 repathed, 17 kept.** The rule this produced, now at the top of the memory index:

> **A memory holds a BEHAVIOR — how to work with Ben. It never holds a fact about the repo. The repo
> describes itself.**

Behaviours don't rot (*don't ask which browser · render the CV first · never archive unanswered
recruiter mail*). Repo facts rot at the next refactor — and memory auto-loads while the repo does not,
so the stale copy is the one in front of the model. That is the 2026-07-27 `$115k`-floor failure
generalized from one value to a whole category.

### The code half, and the spec error an independent reviewer caught

Shipped after the rubric: `held_back_reason` on `Analysis`, the sort change, the review section, and
the analyzer prompt reconciled with the rubric. Written by one fresh agent, reviewed by a second with
no knowledge of the first — and **the review's most valuable finding was that the specification was
wrong**, not the code.

**The spec said `tier → intensity → verdict → fit`. That inverts the caps.** Hard gates live in the
VERDICT, not the score: a coordinator title or a mandatory-tech gap is capped at LOW_FIT however well
its keywords match. Capped roles are *undemanding*, so they score LOW intensity — which means putting
intensity above verdict promotes exactly the junk the caps exist to suppress. Measured on the real
2026-07-29 run: a LOW_FIT role at **fit 32, intensity 2 sorted above two STRONG_FIT roles at fit 85**
in the same tier. That is the Linda Werner failure the rubric's calibration block exists to prevent,
reintroduced by the fix for a different problem. Corrected to **`tier → verdict → intensity → fit`**:
quality grade first, then hours, then score.

**The lesson is about who reviews.** The author's own tests passed, and its self-report was accurate
about everything it had been told to do. What it could not do was question the instruction. Three of
the seven findings were of that kind — defects in the ask, invisible from inside it.

**Two sections became one, at Ben's instruction.** The build had a separate held-back section beside
the rejections. He wanted one place to audit: *"it doesn't matter if they are rejected for intensity
as long as i can look at them and audit… if it is clearly high intensity (4-5) you need confidence to
exclude — it should go in the review section with rejected jobs and the reason."* So intensity 4-5
now leaves the rankings regardless of verdict and lands in a single `✕ Review` section grouped by
reason. Two review findings dissolved with it: a SKIP labelled `intensity` is correct under this rule,
and `role-shape`/`years-bar` became reachable because grouping no longer runs only over skips.

**The invariant that matters is verified on real data, not in a test:** rendering the 135-job
2026-07-29 run places **135 of 135 exactly once**, with **zero** intensity-4-5 jobs in Focus or the
tier lists.

**The same prompt contradicted itself in four places, and one was in the rubric.** Adding rules at the
top of `profile/rubric.md` while leaving `SCORING DISCIPLINE` at the bottom stating the retired
version — STRONG_FIT still requiring `intensity 1-3` and `a credible contract rate` — put both copies
in front of the model at once, since the rubric is injected whole beside the hardcoded text. **Editing
one end of a long prompt and not grepping the other is now a named failure**; the analyzer carried the
same pair, plus a header telling the model to "rank on … intensity" six lines above a block saying
intensity is scored separately from fit.

### The case itself

BJAK, pitched through Next Step Systems on two Dice reqs, is the worked example now in the rubric's
calibration block. Their own posting asks for *"people who work for their passion, not counting
hours"*; the loop promises an offer within a week and prioritizes whoever finishes the assessment
fastest; the parent company sits at **2.0/5 work-life balance, 21% recommending it**. The stack fit is
genuinely good and **three CVs were built for it on 2026-07-24** before anyone read the intensity
language. Under the new rules it is held back, not skipped — Ben still sees it, and still decides.

---

## 2026-07-29 — the API bill, and three wrong diagnoses before the right one

The run died mid-scoring: **134 jobs attempted, 0 scored**, every model call returning
`400 … reached your specified API usage limits`. Not a rate limit — a **monthly spend limit**, which is
a self-set dollar cap in the Console (the tier caps are $500/$1,000/$200,000, so a $100 stop is
always a value someone chose). Spend limits run per calendar month, which is why the message named
the 1st.

### Where the money actually goes: output tokens, not volume

Measured over July: **2,050 jobs scored across 14 runs ≈ $100**, and essentially all of it is
**output**. The input side was already optimised and nobody had written that down — `triage/analyze.py`
puts a `cache_control` marker on the rubric, so its ~2,400 tokens bill at 10% rather than 2,050 times.
So the levers that matter are the ones that shorten *output*: `llm.effort` first, model id second.
`max_workers` and `window_days` do not touch the bill at all.

Shipped: `llm.effort` as a validated setting (`core/settings.py`, threaded through `core/llm.py`'s
single generation path onto langchain-anthropic's `reasoning_effort`), set to `medium`; and
`models.analyze` moved from `claude-opus-5` to `claude-sonnet-5`. Projected ~$100 → ~$25–30.
Both are one-line reverts and `docs/operating/tuning.md` names the tripwire.

### The prefilter is not broken, and I said it was twice

The run summary reads `prefilter: 7 screened out cheaply, 127 sent to opus (5% of Opus calls saved)`,
which looks like a gate doing nothing. It is not. **The Sonnet screen only rejects "clearly out of
lane", and ~95% of what reaches it is in-lane** — the screen is behaving exactly as its docstring
promises. The real waste is elsewhere and larger: **64% of Opus calls (1,002 of 1,560) return a fit
score below 60**, and those are in-lane jobs failing on rate, seniority or role shape. That is rubric
judgment, which is precisely what a regex and a cheap screen cannot do. **Cost is the fix; a stricter
gate is not.**

One real gap did survive the measurement. Of 840 SKIP verdicts, the red-flag categories are
stack-gap 21%, **non-US 8.7%**, body-shop 6.7%, clearance 5.8%, years-bar 4.5%. Body-shop, clearance
and years-bar are already deterministic gates in `prefilter.hard_skip`; **non-US has no gate at all**,
despite being a hard filter in the rubric. Worth ~4% of Opus calls — small, and carrying a real
false-positive risk (a US role at a company with an India office), so it needs a corpus replay before
it ships, not a regex written from a guess.

### The 2026-07-27 correspondence fix had an opposite failure, and it archived a live recruiter

`_AUTOMATED_SENDER` was widened on 07-27 to match job-board domains **with their subdomains**, because
literal `@dice\.com` missed `dice@connect.dice.com` and ~50 Dice blasts were read as human. That fix was
right. It also made **`user.dice.com` — Dice's private recruiter-to-candidate relay — read as automated**,
so `"Akshay Srivastava" <gt4-mu0-nd5@user.dice.com>` (IMCS Group) went on the archive list and out of the
inbox. Proof it is a regression rather than longstanding: the identical shape,
`"Garv Bhalla" <o82-927-r0w@user.dice.com>`, sat correctly under "📬 Live correspondence" in
`worklist-2026-07-22-145611.md`, before the widening.

Fixed with `_PRIVATE_RELAY`, checked **before** the automated test — a relay lives under a domain the
automated pattern matches, so order is what makes the carve-out work. The email was restored to the inbox
with the label removed.

**The failure directions are not symmetric and that is the whole design.** A missed blast costs a crowded
correspondence section for one run. Archiving a human's unanswered mail costs a warm lead permanently,
because the `jobs-triage` label is write-only in practice — Ben: *"i don't check the folder, so if you move
something fresh into it that i haven't responded to, it is a bad thing."*

### `--merge` re-scores, then throws the result away

`_phase3_merge` reads the state file, sets `fetched_jd` / `jd_source="full"` in memory, re-analyzes, and
rewrites **only the worklist** — it never writes the state file back. Verified this run: the worklist
correctly re-scored Insight Global to **SKIP 8** on the real .NET JD, while `state-2026-07-29-144502.json`
still holds `jd_source='title_only'`, empty `fetched_jd`, and the old LOW_FIT 52. The corpus therefore
keeps the judgment the browser step was run to replace. Also quietly undermines any resume-through-`--merge`
design, since a resumed re-score would not persist either.

### Auditability is the actual gap, and the apply doc is the only surface that works

The recruiter email surfaced only because a subagent happened to mention it in a report. Nothing in the
pipeline would have shown it. Ben's conclusion: *"it is clear we need logs to trace what you are doing b/c
there is data slipping through. I need to be able to audit you… we need to upgrade the system to make it
debugable and allow us to catch errors."*

**The design constraint is that Ben reads the apply doc and nothing else.** `jobs-triage` is unread,
`data/runs/` is disposable. So a log file would have failed the same way the label did. Three sections were
made REQUIRED in `/job-triage` step 6, answering the three audit questions: **⚠ could not fetch** (what did
you fail to read), **📥 archived this run** with sender and subject (what did you touch in my mail), and
**📋 every job looked at** (what did you actually see). All three are in `matches/2026-07-29.md`.

Still open (tasks, not shipped): make the archive-list writer carry sender+subject rather than bare
message-ids, and hold any **human display name** out of the archive list for review instead of archiving it.
That second one matters more than the `user.dice.com` carve-out, because a named relay list will always lag
the next board that starts relaying human mail.

### The lesson, which is the same one three times

Three claims were made and retracted in one session: that the agency scrapers were rotted (they were
fixed on 07-24; `core/scrapers/__init__.py` said so), that `core/scrapers/__init__.py` was the stale
file (AGENTS.md was), and that the prefilter was defective (it is not). Every one came from **reading
a summary and reporting it before opening the primary source**. The pattern is cheap to state and was
expensive here: a run summary, a docstring's first paragraph, and an AGENTS.md bullet are all
*summaries*, and each had its correction two to twenty lines further down. Measure, then claim.

---

## 2026-07-28 — a dedup class the applied-cache structurally cannot catch

The run scored **57 jobs** and its top result (STRONG_FIT 86, $130–150k remote) was a job Ben had already
applied to the day before. So was the #4 pick. Neither was a bug in the dedup code; both are outside what
it can see.

### Corporate aliasing defeats both dedup keys at once

**Fullstack Software Engineer @ DATAMARK Technologies** is the **Michael Baker International** req from
`matches/2026-07-27.md`. DATAMARK is Michael Baker's public-safety software arm, and the req is live under
both names with different LinkedIn ids (`4445246208` vs `4444367629`). The applied-cache blocks on two
keys — the `composite_id` (`company|title|city`) and a normalized URL — and **an alias changes both**.
Second instance, same run: **"Atlas Technologies Inc"** is the **Atlas Tech** 1099 req, re-sent by the
recruiter.

Semantic dedup would have caught DATAMARK on JD text alone — the postings are near-identical — but
`triage/dedup.py` runs **within a run, across the jobs being scored**. It never sees `applied.json`, whose
records are company/title/URL only and carry no JD text to embed. So the one mechanism that could catch
this is pointed at the wrong corpus.

**What it cost this run: nothing, because it was caught by hand** — and it was only caught because a commit
message from the day before (`docs(letters): Michael Baker International — DATAMARK fullstack`) happened to
name both. That is not a detection mechanism.

**Fix candidates, cheapest first.** (1) Store the JD text (or its embedding) on applied records written by
`--sync-applied` when the run that produced them has one, and extend the dedup pass to check new jobs against
that corpus — reuses `core/index.py` wholesale. (2) A company-alias map in `profile/profile.yaml`, maintained
by hand; catches the recruiter-alias case (Atlas) that JD-similarity would also catch, and nothing else.
(3) Nothing, and rely on the apply doc's carryover section — which is what happened, and which does not scale
past a reader who remembers yesterday.

**Lesson: two independent dedup keys are not two chances when a single upstream event changes both.**
A rename changes the company name *and* the posting URL, so `composite_id`-or-URL is one key wearing two hats.

### Indeed is now walled in the browser step too, which retires an escape hatch

Both queued Indeed JDs hit `Additional Verification Required` (Cloudflare) **in Ben's own signed-in Chrome**,
and a second attempt after the page settled hit it again with a fresh Ray ID. The 2026-07-23 entry recorded
this for `pagead/clk` trackers; this run it also hit a plain `viewjob?jk=` URL. The standing decision to keep
`www.indeed.com` out of `_JOB_HOSTS` (2026-07-27, Ben's call) is **now better supported, not worse**: adding
the host would convert silent drops into queued items that the browser also cannot fetch.

### What went right, recorded so it isn't re-litigated

- **The correspondence classifier held.** 3 held back, no Dice-blast flood — the 2026-07-27 subdomain-regex
  fix did what it claimed, on live data, one run later.
- **Zero carryover deaths.** All six LinkedIn carryovers from 7/27 were still listed. First run with none.
- **The applied-sheet sync is carrying the run.** 65 rows / 58 auto-blocked produced **217 pre-eval skips**
  against 57 analyzed — a 4:1 ratio.

### A liveness upgrade the tool cannot make on its own

**Greenway Health** had been carried as ⚪ UNVERIFIED for five days because its only known link was a
`remotevibecodingjobs.com` aggregator page. One search found the employer's own Built In posting (8 days old,
no expiry notice) and it verified OPEN. The general shape: **an aggregator-only link is not evidence of
anything, and a title+company search against the employer usually resolves it in one call.** Two other
aggregator-only carryovers resolved the *other* way — "United States Digital Space LLC" posts the same role
shape at $70–100k, $100–130k and $253–299k simultaneously (a repost farm), and Azimuth Partners is an
executive-search firm rather than the employer. **Worth considering as a Step-4 sub-step in the runbook:
for any ⚪ carryover whose only link is an aggregator, search the employer before carrying it forward again.**

---

## 2026-07-27 (later) — the three fixes, and the root cause was narrower than the write-up

Fixed the same day the run surfaced them. One of the three had a different root cause than the morning's
entry claimed, which is worth recording because the wrong diagnosis was the more expensive one.

### The correspondence bug was a regex that could not match a subdomain

The morning entry proposed a content heuristic — *"a no-title/no-company/no-JD posting from a known
job-board sender is a blast"*. That would have worked, and it would have been the wrong fix. The actual
cause: `_AUTOMATED_SENDER` spelled the boards as literals like `@dice\.com`, and Dice sends from
**`dice@connect.dice.com`**. The literal never matched, so every Dice alert fell through to the
default-safe branch and was called correspondence. Same latent hole for `mail.ziprecruiter.com`,
`marketing.dice.com` and anything else on a subdomain.

The fix is `@(?:[\w-]+\.)*(?:dice|indeed|ziprecruiter|glassdoor|linkedin|…)\.com` — match the
registrable domain, not the envelope. Broadening the sender list is safe here **because the `is_reply`
branch is checked first**: if Ben ever replied, `In-Reply-To` makes it a conversation whatever the
sender looks like. That guard is now pinned by a test, as is "a human at a staffing firm is still
correspondence" — the list names job *boards*, not recruiters.

**Lesson: a heuristic that compensates for a broken exact match hides the broken exact match.** The
content heuristic would have suppressed the symptom on Dice and left `mail.ziprecruiter.com` waiting.

### The browser queue exclusion is a list, not a rule

`elinks.dice.com` and `my.greenhouse.io/dashboard` now never enter the Tier-2 queue
(`_BROWSER_UNFETCHABLE` in `core/models.py`). They stay in `_JOB_HOSTS`, because the presence of such a
link is still evidence that an email is job-related — they are only barred from the work list a human
drives. Kept deliberately as a short evidence-backed list rather than a pattern: excluding a *fetchable*
job costs a real JD, so this side must stay conservative.

### Both stale doc claims came from reading a filtered number as a raw one

`core/scrapers/__init__.py` now says outright that the run summary prints **in-window** counts and only
the **raw** scrape count speaks to board health, with the 2026-07-27 raw figures (Insight Global 442,
Apex 493, Motion 268) next to the same run's in-window line (`motion 9`, `scion 0`). `settings.yaml`'s
`sources: []` comment claimed four sources; seven run, and the comment now says so and records that the
version it replaced would have argued for excluding Apex — which returned 44 in-window that day.

Indeed stays out of `_JOB_HOSTS` by Ben's call (2026-07-27): *"indeed usually isn't a good source, but
sometimes it surprises."* The `seen and not fetched` warning keeps counting it, so the decision is
revisitable from data rather than from memory.


---

## 2026-07-27 — the correspondence classifier is the signal-quality bug

Routine run on the surface — 283 analyzed, 4 résumés built, first run on `claude-opus-5`. Three findings
underneath it, none of which cost a line of code this session but all of which cost ranking quality.

### 1. Dice job-alert blasts are being read as human correspondence

~50 entries from `dice@connect.dice.com`, nearly all `Untitled @ unknown` with no title, company or JD
text, landed in the worklist's **"Live correspondence — NOT fresh leads (do not cold-apply)"** block.
That section exists to stop a duplicate agency application cutting across a live human thread; it only
works if a human actually wrote the mail. Two costs: the two genuine leads in the section (TriCom, fit 76;
an unnamed remote contract-to-hire, fit 77) are buried under 50 lines of noise and cannot be trusted as
person-to-person, and `_is_correspondence` holding these back from archiving is what produced
`held back 180 job(s) from human correspondence`. **A no-title/no-company/no-JD posting from a known
job-board sender is a blast, not a person.** That is the discriminator to add.

### 2. The Tier-2 browser queue is structurally, not incidentally, dead

33 of 40 queued items were `elinks.dice.com` wrappers. This was recorded on 2026-07-23 as "7 expired to
error pages" and read as staleness. It is not staleness: one resolved cleanly today to **Dice's own
LinkedIn company page**. These links come from "your profile was viewed" and job-alert *marketing* mail
and never pointed at a posting. Queuing them costs a browser round-trip each and inflates the
couldn't-fetch count with things that were never fetchable. They should be filtered before the queue.

### 3. Indeed is the largest silent leak, and it is growing

`22 job-shaped links on 4 hosts — seen and not fetched`, **18 of them `www.indeed.com`**. The same
warning on 2026-07-23 counted 8. Indeed is absent from `_JOB_HOSTS`, so these are dropped before
scoring — invisible in every downstream count. Adding the host is a one-line change; the reason to be
careful is that Indeed also serves the hard Cloudflare wall that ended the 7/23 browser step (and hit
again today until cleared by hand).

### 4. Two scraper "rot" readings were window artifacts, not rot

`core/scrapers/__init__.py` records Apex 3 and KORE1 2 as "either small boards or already partly rotted".
Today: **Insight Global 442** (was 87), **Apex 44** (was 3), TEKsystems 53, Mondo 13, Motion 9, KORE1 6.
A `scion` source also ran and returned 14 postings, 0 in-window. Two corrections follow: the per-source
counts in that file are **window-filtered**, so they cannot be read as board health, and the
`config/settings.yaml` comment claiming `sources: []` means "the four measured healthy on 2026-07-22" is
**stale — seven sources run**.

### Lesson

Both the scraper "rot" note and the browser-queue "staleness" note were written from a single run's
numbers and read as properties of the world. Neither was. **A count taken through a filter describes the
filter as much as the source** — when recording a health number, record what was filtering it.


---

## 2026-07-24 — the rot run: four scrapers, four different silent truncations

The run that showed the per-source health line is only a detector if somebody reads it *and disbelieves
it*. Triage itself was routine — 64 analyzed, 173 skipped pre-eval, 11 emails archived, 4 résumés built,
first run under the onsite/relocation rubric. The finding was underneath it.

### What shipped

| Fix | What it does |
|---|---|
| `core/scrapers/motion.py` | Lifted our own 6-page (120-href) ceiling on a 797-posting board; swapped the two sub-listings for the combined `/tech-jobs`; stop on "no new hrefs". **19 → 275** |
| `core/scrapers/apex.py` | Off the cookie-gated GET pagination. **3 → 150** |
| `core/scrapers/teksystems.py` | **Check HTTP status** before treating a sub-sitemap as empty, and de-duplicate discovery. **80 unique, correct** (was 84 records over 80 distinct links) |
| `core/scrapers/kore1.py` | List regex anchored on posting rows, not category headings. **2 → 6** (board is 64) |
| `core/scrapers/scion.py` | **New scraper** — the sixth PRIMARY-tier agency. 218 postings walked, **15** after the dev filter |
| `triage/channels/agencies.py` | `DEFAULT_SOURCES` is now the whole registry (7), not a hand-picked 4 |
| `docs/operating/{services,tuning}.md` | Counts, constants and the rot baseline re-measured 2026-07-24 |

Agency supply per run: **~155 → ~630.**

### The lesson, and what it cost

**A small plausible number is the hardest failure to see, because it looks like an answer.** The
2026-07-22 health line read `insightglobal 87 · teksystems 78 · motion 27 · mondo 15 · apex 3 · kore1 2`
and was interpreted — in this log, in `services.md`, and in the `DEFAULT_SOURCES` comment — as four
healthy sources plus two small boards. All four small numbers were bugs, and **no two had the same
cause**: our own page cap, a cookie-gated results table, an unchecked HTTP status, and a regex anchored on
the wrong element. The only thing they shared was the *shape* of the symptom.

**And the first write-up of this entry got Motion's cause wrong, which is its own lesson.** It said the
site had changed its pagination parameter from `?page=` to `?start=`. The live site does behave that way,
but the committed scraper already used `?start=` and already stopped on "no new hrefs" — the diagnosis
came from reading the module's first 40 lines, seeing `MAX_PAGES = 6`, and letting a true site-level
observation fill the gap instead of reading the pagination code underneath it. The real ceiling was ours.
**A plausible external cause is the most comfortable place to stop looking**; the correction is to prefer
the explanation that implicates your own constants until the external one is proven. The verifier that
caught it did so by running the committed code, which is why the workflow had one.

What it cost: Motion is one of Ben's best agency partners and was returning ~2.5% of its dev contract
supply, for at least two days and probably longer. The two live Motion contracts on the 2026-07-24 apply
doc ($75–100/hr and $69.5–76/hr) were both found by hand; the tool could not have surfaced them.

Three corrections now in the code rather than in prose:

1. **A fixed page cap cannot distinguish "the board ended" from "pagination broke".** Motion's loop
   refetched page one six times and reported success. Walks now stop on *no new postings*, and keep
   `MAX_PAGES` only as a runaway guard — so the next paginator change moves the count loudly.
2. **Never treat an exception-free empty response as an empty board.** TEKsystems swallowed 403/503
   sub-sitemaps as zero-`<loc>` documents. Status is checked now.
3. **Excluding a source on a low count is a bet that the board is small.** That bet lost 4/4.
   `DEFAULT_SOURCES` is the full registry; a source leaves it on evidence, never on suspicion.

### Also this run

- **A false alarm worth recording, because the reasoning was wrong in an instructive way.** Five digests
  logged `extractor returned 5 job(s) … but the email carries 27 job link(s)`, and the identical count
  across five emails read as a hard cap. There is none — the prompt forbids truncating and
  `_EXTRACT_MAX_TOKENS` is 20000. Three were the same IntelliSearch template rendering ~5 jobs in the
  body, and one was a **single-job** "Now Hiring" email that also carried 27 links, which is decisive:
  the extra links are related-jobs rails and footer chrome, not postings. The extractor was correct and
  the reconciliation did exactly its job. **The defect is the warning's wording** — "recovering the 22 it
  left out" reads as data loss and cost a round of investigation.
- **`mondo.gosnaphop.com` surfaced in the unclassified-host report** and is already Mondo's own sitemap
  host — no action, the classifier working as intended.

### The second sweep, same day — the caps were the bug the whole time

Ben's rule, on reading the above: *an artificial cap is removed or it justifies itself.* Applying it
found the first sweep had fixed four scrapers and left three ceilings standing.

| knob | was | now | effect |
|---|---|---|---|
| `insightglobal.py` · `MAX_PAGES` | 2 | 60 (guard) | **88 → 432** |
| `apex.py` · `MAX_JOBS` | 150 | 600 | **150 → ~488**, the whole dev slice |
| `agencies.py` · `_MAX_PER_SOURCE` | 200 | 600 | was clipping 432 and 275 *downstream* |
| `agencies.py` · `_DEADLINE` | 300 s | 600 s | Apex's slice is ~317 s |

Agency supply: **628 → ~1,300 per run**, ~320 s wall-clock, Apex the new long pole.

**Insight Global is the one to remember, because nothing about it looked wrong.** Its per-keyword walk
*already* stopped correctly on the first empty page; `MAX_PAGES = 2` was an arbitrary ceiling bolted on
top of working logic, costing 344 postings. It was never examined during the first sweep because 88
reads as a healthy number — the earlier lesson was "distrust a *small* count", and this one was not
small. **The generalised version: distrust any count you have never tried to exceed.** The check is
mechanical and takes a minute — raise the cap; if the count moves, the count was the cap's number and
not the board's. Measured: 2 pages 88 · 6 pages 194 · 10 pages 281 · 20 pages 350 · uncapped 432.

**Apex keeps a cap, and it is the one in `core/scrapers/` that is a real coverage decision.** Its 488
dev postings cost ~317 s, and the channel *abandons* a source still running at `_DEADLINE` — so an
uncapped Apex under the old 300 s deadline returns **zero**, not a partial board. The cap and the
deadline had to move together, and the docstring now states that rather than calling it politeness.

`_MAX_PER_SOURCE` was the third ceiling and the easiest to miss: it clips *after* the freshness window
rather than at the source, so lifting the two scraper caps just relocated the truncation one layer
downstream. **When you lift a limit, look for the next one.**

### The public snapshot had been shipping a red test suite

Building the `/publish` skill and running it for the first time surfaced something unrelated to the
scrapers: a fresh clone of `job-hunt-kit` ran **7 failures**, and had since the repo went public.
Verified against the previous public commit — same 7, so this was not new breakage.

None was a real defect. The extraction substitutes `config/example/settings.yaml` for
`config/settings.yaml`, and seven tests asserted values out of the owner's file — `max_workers == 12`,
an empty boards watchlist, mail being enabled. **AGENTS.md already forbids exactly this** ("never pin a
config value that states no rule: it is a photograph"), and the rule had no enforcement, so seven tests
drifted into breaking it.

Fixed three ways: photograph assertions deleted (the surrounding tests kept — in `test_settings.py` the
line *above* the photograph is the real rule and it always passed); one genuinely obsolete test deleted
outright (`a fresh clone must not hit other people's boards` is false by design now that the example
names boards); and three real rule-tests decoupled by passing `channels.ingest` the `enabled` callable
it already accepted. **No production code changed and no new tests were added.**

The public tree now reads `583 passed, 19 skipped`. Two process lessons:

1. **`pytest` is not in `core/requirements.txt`** — the documented install does not let a stranger run
   the suite the repo ships as evidence. Root `requirements.txt` has it. Not fixed; noted below.
2. **`JOBSDB_CONFIG_HOME=config/example` is not a faithful stand-in for a public clone.** It leaves the
   file at `config/example/settings.yaml` while extraction copies it *to* `config/settings.yaml`, so
   path assertions differ. The only faithful check is running the suite against the extracted tree.

## 2026-07-20 — the staleness run

The run that exposed the tool's biggest blind spot. 358 jobs analyzed over a 7-day window; Ben had
interviewed all week (FPOV 7/15, College Board 7/17) and applied to nothing.

### What shipped

| Feature | Commit | What it does |
|---|---|---|
| Cheap prefilter | `511f1a0` | Regex + Sonnet gates before the Opus analyzer |
| Parallel liveness | `81e719b` | Post-ranking availability check on the ranked jobs |
| Runbook rewrite | `96f1f9d` | 9 steps, ending in tailored résumés + a commit |
| Measured speedup + truncation fix | `6aad993` `b789b59` | Corrected optimistic claims; `max_tokens` headroom |
| Configurable concurrency | `511f1a0` | `max_workers` 5 → 12 in `config.yaml` |
| Alert vs. correspondence split | (this commit) | Human threads never archived, never ranked as fresh leads |

### Lessons — process

**1. Weekly triage cadence is too slow for the Tier-1 contract lane.**
Every one of the five 7/13 picks verifiable at its primary source had closed within 7 days — including
Trident at $90/hr (fit 88) with "100+ applicants". LinkedIn agency contract reqs fill in under a week.
Run every 2–3 days, and apply same-day for Tier-1 contracts. **Ranking quality was never the
bottleneck; latency to apply was.**

**2. Freshness at scrape time ≠ freshness at apply time.**
VortexLink (fit 82) was scraped successfully *during* the run and was already dead when checked minutes
later. Any availability signal has a short half-life; check at the end of the run, not the start.

**3. Delegate high-volume mechanical work to subagents.**
The Gmail archive is ~3 calls × 100+ emails. Run inline it dominates the session; as a subagent it runs
in the background while the main thread continues. It is now the slowest single step (14.5 min for 101
emails) and should be **sharded across several subagents** next.

**4. A runbook that stops early leaves standard work to inference.**
`/job-triage` ended at "deliver the digest", so building tailored CVs for the top picks — which is standard
— read as an open question and got asked about instead of done. Anything standard must be *written in
the runbook*, not left to be inferred. Same for the carryover re-check, the apply doc, and the commit.

### Lessons — engineering

**5. `max_tokens` is headroom, not a target.**
It truncates mid-generation; with structured output that means invalid JSON. It does **not** make the
model terse — the model stops on its own. Unused tokens are not billed, so there is no reason to run
near the edge. Each site's failure mode differs and all of them lose work:

| Site | Was | Now | Failure mode when truncated |
|---|---|---|---|
| `ingest.py` | 8000 | 20000 | a 30-job digest is lost entirely |
| `analyze.py` | 4000 | 8000 | falls back to `verdict=SKIP` — job quietly lands in "Rejected" |
| `prefilter.py` | 200 | 400 | screen fails open — wasted call |

`ingest.py` had already documented this after a previous incident, and it was repeated anyway. **When a
comment in this codebase explains a past failure, read it as a rule, not trivia.**

**6. Validate heuristics by replaying real run data before shipping them.**
The first year-bar regex looked correct and passed hand-written tests. Replayed against the actual 358
jobs it would have killed 5 good ones — it read Darkroom's *"operating for 10 years"* (company age) and
Fractal's *"Experience 5–10+ Years"* (a range) as hard requirements. The fix: count only figures
adjacent to "experience", take the **minimum** stated bar and the **low end of a range**. Pinned in
`test_prefilter.py`. Every state file under `data/corpus/` is a free regression corpus — use it.

**7. A false OPEN is the worst output a liveness check can produce.**
A naive LinkedIn check reported all three reqs confirmed-closed-in-browser as OPEN, because the closed
banner only renders in a signed-in session. The `/jobs-guest/` API is worse — "no longer accepting"
appears in boilerplate on *open* listings and is missing on closed ones. LinkedIn/Indeed/aggregators are
therefore **UNVERIFIED, never OPEN**, and every ambiguous case (timeout, bot-wall, error) resolves to
UNKNOWN. Saying "I don't know" beats a green light on a corpse.

**8. Aggregators never expire listings.** `remotevibecodingjobs.com` and friends show "Apply" forever. A
200 proves only that the aggregator still holds a database row. Resolve to the primary source or mark
unverified — never treat aggregator presence as evidence a req is open.

**9. Bias cheap filters toward KEEP, and fail open.**
A false keep costs one Opus call; a false reject means Ben never sees the job. Those are not symmetric.
The screen prompt says so explicitly, and any API error, refusal, or unparsed response keeps the job.

**10. Measure before claiming a speedup.**
Estimated "~25 min → ~4–6 min"; measured **~9.5 min**. The prefilter removes 28% of Opus calls but adds
a 3.2s screen to the 94% of jobs surviving the regex, netting only ~9% wall-clock. **It is a cost win,
not a speed win.** The runtime lever is `max_workers` (2.4× on its own).

**11. Never pipe a long run through `tail`.**
`tail` buffers until the process exits — 25 minutes with a 0-byte log and no way to tell progress from a
hang. Use `tee`. (Diagnostic while blind: `%CPU` near 0 with *cycling* TCP connections means
network-bound progress, not a stall.)

**12. Use the Edit tool for doc changes, not scripted string replaces.**
A `python3` replace missed because the file used Unicode `≥` and the pattern used ASCII `>=`. It failed
silently and a commit message claimed the doc was updated when it wasn't. Edit errors on no-match;
string replaces do not.

---

### Lesson 13 — the obvious fix was the wrong fix (correspondence handling)

Filed as "triage ingests recruiter reply threads — filter them out." **Filtering them out would have
destroyed real value.** Those emails produced three of the top Tier-1 jobs that run — College Board
(86), Item Cloud Blue (78, 76) — and none of them have a link. They exist *only* because triage read a
recruiter's email body. Extraction was never the bug.

The bug was that one category was being used for **three** purposes with different safety profiles:

| Purpose | Correct behaviour | What was happening |
|---|---|---|
| Extract & rank the job | keep — it's real | ✅ working |
| Put the email on the archive list | never | ❌ would archive a live thread |
| Present it as a fresh lead | never | ❌ College Board at #2, mid-process |

The ranking half was the more dangerous one and wasn't in the original bug report at all. Ben supplied
it in conversation: he was between a 7/17 panel and a 2nd technical interview at College Board while
the tool listed it as a fresh contract to apply to. Cold-applying via an agency there could have cut
across his own live process.

**Generalisable:** when a bug report says "stop ingesting X", check what X is *worth* before filtering
it. The fix is usually to split the downstream uses, not to drop the input. Fixed in `ingest.
_is_correspondence` + a dedicated worklist section; the classifier is default-safe because the two
error directions are wildly asymmetric (misread alert → one email stays in the inbox; misread
conversation → archived and cold-applied to).

---

## Open bugs / next steps

- **[FLAKE · found 2026-08-04] `cv.batch fit` fails roughly 1 run in 3 with a non-zero exit from the
  renderer subprocess**, while the identical render succeeds standalone every time, including under
  `capture_output`. It looks like LibreOffice contention on back-to-back conversions when several batch
  agents render concurrently. **The failure deletes the PDF rather than leaving a stale one, which is
  `cv/test_render.py`'s rule working correctly** — so this costs a re-run, not a wrong document.
  Re-running the command clears it. Fix candidate: serialise the LibreOffice conversion behind a lock,
  or retry once on non-zero exit.
- **[HYGIENE · found 2026-08-04] A stray `research_stderr.log` appears at the repo root** when research
  agents redirect stderr there. Untracked, harmless, removed by hand this run. It should go to
  `data/runs/` or nowhere.
- **[PROCESS · found 2026-08-04] A carryover with documents but no `Résumé:` line is silently rebuilt.**
  Brighterway and Jobgether had 8/03 folders that yesterday's apply doc did not record, so `existing`
  read false and the batch queued both for a rebuild. The runbook already states the rule; nothing
  checks it. **Cheap fix: after writing an apply doc, run `cv.batch worklist` and assert every carryover
  entry reports `existing: true`.**
- **[GAP · reconfirmed 2026-08-04, second consecutive run] `_JOB_HOSTS` still excludes real job boards.**
  211 unclassified links this run, **9 of them job-shaped on `www.indeed.com`** — seen, marked seen, and
  never attempted, so they can never appear again. Same finding as 8/03, unfixed.

- **[FIXED 2026-07-31] The worklist's "📬 Live correspondence" section rendered empty whenever the
  held-back job(s) scored SKIP.** Confirmed live on the 7/31 1-day run: 5 of 7 correspondence-flagged
  jobs (all from "Built In" alert emails) scored SKIP and vanished from every section — not ranked
  (correspondence is pulled out before ranking), not in Live correspondence (the verdict filter), not in
  the review section either (also pulled out before that split runs). `triage/worklist.py:219` now
  renders correspondence off `from_correspondence` alone; verdict never gates visibility, matching how
  the held-back-intensity section already works. Pinned by
  `test_a_skipped_correspondence_job_still_renders_in_live_correspondence` in `triage/test_worklist.py`.
  **A second, related bug found and fixed in the same pass:** `--merge` rewrote the worklist from the
  state file alone and never had the archive plan (`plan.rows`/`plan.held`) to pass to `render()`, so
  every merge silently dropped the "📥 HELD BACK from archiving" section too — Phase 1 only ever
  persisted `plan.lines` (the archive-*.txt file) to disk, not the rows/held that the worklist actually
  renders. Phase 1 now also writes `archive-plan-<run_id>.json`; `--merge` reloads it. Pinned by
  `test_merge_reapplies_the_archive_plan_phase_1_computed` in `triage/test_merge.py`.
- **[BUG · found 2026-07-30] `render_cv.py:to_pdf` silently keeps a stale PDF.** `subprocess.run(...,
  check=True)` then `if not pdf.exists()` — when another headless LibreOffice holds the lock, soffice
  exits 0 writing nothing and the guard passes on the *previous* render. Under `/tailor-cv-batch` this
  means the blind grader can score, and report passing marks for, text that was deleted. Caught twice
  independently in the twelve-CV run; both agents worked around it with `rm` and neither changed code.
  **Fix:** stat the docx before conversion and assert the PDF is strictly newer, or unlink the target
  first. Needs a ticket, a test and a commit — it is code, not configuration.
- **[GAP · found 2026-07-28] Corporate aliasing defeats the applied-cache.** A req re-posted under a parent
  or subsidiary name (Michael Baker → DATAMARK Technologies) changes both the `composite_id` and the URL, so
  neither block key fires; semantic dedup would catch it but runs within-run and never sees `applied.json`.
  Two instances in one run. See the 2026-07-28 entry for fix candidates.
- **[GAP · found 2026-07-28] Indeed is Cloudflare-walled in the Tier-2 browser step**, including plain
  `viewjob?jk=` URLs, not just `pagead/clk` trackers. Retires the browser as an escape hatch for that host
  and strengthens the standing decision to keep `www.indeed.com` out of `_JOB_HOSTS`.
- **[FIXED 2026-07-27] Automated job-board blasts classified as human correspondence.** Root cause was
  a sender regex that could not match a subdomain (`@dice.com` vs `dice@connect.dice.com`), not a
  content-classification gap. Fixed in `triage/channels/common.py`; pinned by
  `triage/test_correspondence.py`.
- **[FIXED 2026-07-27] `elinks.dice.com` marketing wrappers queued for the browser.** Excluded via
  `_BROWSER_UNFETCHABLE` in `core/models.py`; pinned by `core/test_browser_queue.py`.
- **[GAP · found 2026-07-27, growing] `www.indeed.com` is not in `_JOB_HOSTS`.** 18 job-shaped Indeed
  links dropped this run, up from 8 on 2026-07-23.
- **[FIXED 2026-07-27] Two stale claims about the agency scrapers.** Both corrected in place —
  `core/scrapers/__init__.py` now separates raw from in-window counts, and `config/settings.yaml` names
  all seven sources.
- **[OPEN · by decision 2026-07-27] `www.indeed.com` stays out of `_JOB_HOSTS`.** 18 job-shaped Indeed
  links dropped this run (8 on 2026-07-23). Ben's call: Indeed is usually a poor source but occasionally
  surprises, and adding the host without a fetch path only converts silent drops into noisy failures
  behind a Cloudflare wall. The `seen and not fetched` warning keeps the count visible.
- **[GAP · found 2026-07-24] `pytest` is not installable from the documented path.** A stranger
  following the README installs `core/requirements.txt` and gets `No module named pytest` — the suite
  the public repo ships as evidence cannot be run without knowing to install the root
  `requirements.txt` instead. One line in the README or in `core/requirements.txt` closes it.
- **[GAP · found 2026-07-24] Nothing enforces the no-photographs rule.** AGENTS.md forbids pinning a
  config value that states no rule; seven tests broke it and shipped red publicly for weeks. Ben
  declined a guard test for now (see the deferred entry below). The `/publish` cold-clone step is the
  only detector.
- **[DEFERRED · 2026-07-24] A guard test for the above.** An AST-walking test that fails when a test
  reads the real settings file for a *value* would be the same pattern as `core/test_single_path.py`.
  Deliberately not added — Ben's call was "no new tests".
- **[BUG · found 2026-08-04, and it DESTROYS OUTPUT] Concurrent `soffice` calls lose a PDF that was
  already on disk.** Building 10 CVs and 10 letters in parallel, a letter render in the Brighterway
  folder coincided with something re-rendering the CV, and the rendered CV PDF — present and
  correct minutes earlier — **was gone afterwards**. LibreOffice is effectively single-instance per
  user profile: a second invocation attaches to the first and can exit 0 having done nothing, or
  clobber the in-progress conversion. Combined with the `to_pdf()` bug directly below (success is
  never verified), the failure is silent in both directions — the caller is told it wrote a file, and
  a *different* file quietly disappears. Recovered by hand this run; a full audit found all 19
  packages intact afterwards. (Written first with the rendered PDF's literal filename, which put the
  owner's name in a file that ships and turned `scripts/test_leaks.py` red — the guard working
  exactly as designed, on the author of the entry describing another guard.) **Fix:** serialise PDF conversion behind a lock, or give each render its
  own `-env:UserInstallation` profile dir so instances cannot collide. The existence check below is
  what would have caught it.
- **[BUG · found 2026-08-04] `research/history.py` substring-matches company names, and produced a
  FALSE "already applied".** Researching **Compa** reported it as an agency Ben had applied to on
  2026-07-06; both were wrong. `"compa"` matched `"BNSF Railway Company"` in `applied.json`. The rubric
  is explicit that this is the expensive direction — *"A false dedup (hiding a job he never applied
  to) is worse than one resurfacing"* — and the same matcher shape is what the ranker blocks on, so a
  short company name can silently suppress a live job. **Fix:** match on the normalized whole name (or
  the composite key) rather than on substring containment; short names like Compa, Salt, Link and
  Motion are exactly the ones that break it, and three of those are already in the corpus.
- **[FLAKY TEST · found 2026-08-03] `scripts/test_extract.py::test_the_real_tree_buckets_are_pinned`
  pins an ephemeral lock file in an exact-equality assertion.** The expected `EXCLUDED` list names
  `.claude/scheduled_tasks.lock`, which is untracked and exists only while a scheduled task is running.
  With no task running the file is absent and the exact-match assertion fails — so the test is red on a
  clean tree for a reason that has nothing to do with the extraction rule it guards. This also means it
  would go red on a stranger's clone, which the suite's own policy forbids (`pytest -q` must read
  `passed`/`skipped`, never `failed`). **Fix:** drop the lock file from the pinned list, or compare
  against tracked paths only.
- **[BUG · found 2026-08-03] `make_cover_letter.py → to_pdf()` reports a write it did not make.**
  `subprocess.run(soffice ..., check=True)` returns 0 on a cold start that converts nothing, and the
  function prints `wrote <path>.pdf` regardless. The stale (or absent) PDF survives and the caller is
  told it succeeded. `cv/test_render.py` already pins this exact rule for the CV renderer; the
  cover-letter renderer needs the same existence-and-mtime check and the same test. **Fix:** assert the
  output file exists and is newer than the docx after the call, raise otherwise.
- **[GAP · found 2026-08-03] LinkedIn location labels are wrong ~1 in 3, and always pessimistic.**
  Citi, Expedia and Dayforce were all labelled more-onsite than they are. Location drives the rubric's
  location-tier demotion, so this under-ranks hybrid/remote roles. Company research catches it at Step
  8, but only for the ~9 roles that get researched. **Fix candidate:** have `liveness` reconcile the
  location string while it already has the page open.
- **[GAP · found 2026-08-03] `_JOB_HOSTS` misses first-party ATS hosts.** 23 job-shaped links seen and
  never fetched this run; `recruiting.paylocity.com` and `tracking.icims.com` are real ATS hosts that
  would fetch fine. (Indeed and Dice are on the same list but are Cloudflare/403-walled anyway, so
  adding those buys queue entries rather than JDs.)
- **[COSMETIC · found 2026-07-24] The link-reconciliation warning reads as data loss.** `extractor
  returned 5 job(s) for X, but the email carries 27 job link(s) — recovering the 22 it left out` fires on
  every templated digest, where the surplus links are related-jobs rails rather than missed postings. It
  is the tool working correctly, but the wording cost a full investigation this run. Reword to something
  like `22 unclaimed links recovered as bare jobs (may be related-job chrome)`.
- **[DEFERRED · 2026-07-24] No automatic rot detector.** A per-source floor warning when a count drops
  >40% run-over-run was scoped and **deliberately declined** by Ben as likely-flaky for the value. The
  standing mitigation is the health line in the run summary plus the corrected instinct that a low count
  is a hypothesis. Revisit only if a scraper rots again undetected.
- **[GAP · found 2026-07-23] Tier-2 browser queue can be 100% unfetchable — and the runbook oversells it.**
  On the 2026-07-23 run all 8 queued links were dead: 1 Indeed `pagead/clk` tracker → hard Cloudflare wall
  even in Ben's real Chrome; 7 `elinks.dice.com` email-click wrappers → expired to browser error pages, and
  because they never resolved a title/company the `dice.com/jobs?q=` fallback had nothing to search. Two doc
  claims in `triage.md` need caveats: line ~227 "Proven end-to-end on Indeed" (now Cloudflare-walled)
  and line ~200 "Dice is fully automatic" (true for real job pages, false for expired elink wrappers). **Fix
  candidates:** resolve/strip `elinks.dice.com` wrappers before queuing; drop Indeed `pagead` trackers from the
  queue (they redirect to sponsored listings even when cleared).
- **[GAP · found 2026-07-23] Dice JD fetches 429 through the shared `r.jina.ai` proxy** — most of this run's
  32 couldn't-fetch. A public proxy with no per-user budget throttles under load; a stranger cloning the repo
  hits the same wall. Worth documenting as a known external dependency (and a reason to prefer first-party fetch).
- **[NOTE · 2026-07-23] The extractor-undercount recovery path is load-bearing, not a safety net.** Multiple
  multi-job alert emails had the Sonnet extractor return ~5 of 20–27 links; the "recovering the N it left out"
  reconciliation is what makes coverage correct. Backed by the Project-D "silent LLM under-production" bullet.
- **[PERF] Shard the email archive across subagents** — 14.5 min for 101 emails is now the slowest step.
  (2026-07-23: 16 emails via one subagent ran fine, ~3.5 min; the backstop correctly skipped 2 mixed threads.)
- **[PERF] `ingest.py:281` extraction pool is still 6** while the analyze pool is 12.
- **[PERF] Pipeline ingest into analysis** — extraction fully completes before any analysis starts;
  streaming would overlap the two stages.
- **[PERF] Test whether `max_workers` can exceed 12** without hitting Anthropic 429s (16 projects ~7 min).
- **[GAP] Liveness cannot check LinkedIn/Indeed** — those still need the browser (Tier-2) path.
