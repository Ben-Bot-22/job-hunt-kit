---
name: tailor-cv
description: Tailor Ben's CV to a specific job description — verified bullets from the bank, present options for approval, then generate docx + PDF into a per-application folder
---

Given a job description, produce a tailored version of Ben's CV. Adapt only as much as the JD needs
(Ben applies to roles that already fit), draw every claim from verified evidence, get Ben's approval on the
proposed changes, then render `docx + PDF` into a clean per-application folder.

> **More than one CV? Use `/tailor-cv-batch` instead.** This file is one job followed end to end, and
> running it N times is N serial round-trips through a loop whose every expensive step — parsing,
> drafting, rendering, grading — is per-job and independent. `/tailor-cv-batch` fans this same skill
> out one agent per job and returns a single table. It is the default for a triage run's picks;
> reach for this file directly when there is exactly one posting.

**Inputs.** The user passes a JD as pasted text, a file path, or a URL. If a URL, fetch it (WebFetch); if it
needs a login/paywall, ask Ben to paste the text. If nothing was passed, ask for the JD (and the company +
role title, if not obvious from the JD).

**Sources of truth (read these first, every run):**
- Base CV: `profile/cv-base.docx` — never edited in place; it's the template.
- Bullet bank: `profile/bullet-bank.md` — the ONLY place claims may come from. Obey its DO-NOT-CLAIM list.
- **Playbook: `docs/knowledge-base/personal/tailoring-playbook.md`** — reusable STRATEGY: general principles, the Founder-framing rule,
  and per-target playbooks (e.g. Braintrust). Read it and apply anything relevant to this target.
- Renderer: `cv/scripts/render_cv.py` — applies a JSON edit-plan to the base, preserving all formatting.

## 0. Identify the target & pull its context
Before touching the JD, classify what you're tailoring for:
- **A specific job/company** (normal case) → proceed to §1 with the JD.
- **A platform / talent marketplace** (Braintrust, Gun.io, Toptal, etc.) → there may be no single JD; it's a
  *positioning* résumé. Check `docs/knowledge-base/personal/tailoring-playbook.md` for that target's section and apply it.
  - If the platform has **no playbook section yet**, do a quick research pass (WebSearch/agent: how the platform
    matches talent, client type, what a strong profile emphasizes) BEFORE drafting, then **append a new target
    section to `docs/knowledge-base/personal/tailoring-playbook.md`** so it's reusable next time (the playbook grows, like the bank).
Apply the playbook's Founder-framing rule when setting the Reazy header (`experience[].title` override): drop
"(Founder)" for perm/big-co, add "Founder &" for startups/founding-eng, keep "(Founder)" for contract markets.

## 1. Understand the JD — READ IT IN FULL, FIRST, and write it to `jd.txt` before drafting
**Mandatory and non-negotiable.** Read the whole posting to the end before a word of the plan is written,
and save it to the application folder as `jd.txt` — the folder is the record of what the CV was written
against, and a plan with no `jd.txt` beside it cannot be checked later.

Never write from a run summary, a worklist `why:` line, or the scorer's one-line verdict. Those are
lossy by construction, and on 2026-07-28 the summaries were wrong three times in one run: Warp was
scored "remote" and is on-site Los Angeles; Provenir's AI requirements are all *preferred, not required*
(a backend Python role, easier than it scored); and the "A1" correspondence is BJAK in Malaysia, a
non-US hard filter, whose only link is an assessment-upload page.

Extract: role title, company, seniority, must-have skills/tech, nice-to-haves, domain, remote/cadence, and the
5–10 keywords an ATS/screener will look for. Note anything the JD stresses that the base CV buries or omits.

## 1b. Parse the posting into `jd.json` — ALWAYS, before drafting

```bash
.venv/bin/python -m cv.jd_parse <folder>/jd.txt      # writes <folder>/jd.json
```

This is the artifact the CV is written against and later graded against. **Two passes over the same
posting by the same context agree with each other by construction, which is worth nothing** — that is
why the brief is a file and the grader is a separate program.

It extracts screenable keywords (`must_have` / `nice_to_have`) and the pitch (`stresses`, `worries`,
`lead_with`). It deliberately drops **years-of-experience and degree bars** — Ben does not state a
years number anywhere, so a years row can only ever be failed or fudged. Do not add them back by hand.

Read `lead_with` and `worries` before drafting. `must_have` tells you what to cover; those two tell
you what to open with.

## 2. Decide tailoring depth (adaptive — default LIGHT/MODERATE)
- **Light** (JD closely matches the base): rewrite the summary to mirror the JD; reorder the skills lines so the
  most-relevant lead; light reword of a few bullets. Leave bullet *content/count* alone.
- **Moderate** (some emphasis shift): the above + reword bullets to echo JD language and reorder bullets within a
  section so the relevant ones lead.
- **Aggressive** (genuine stretch — different stack/domain): the above + swap in/out or add bullets, all sourced
  from `profile/bullet-bank.md`. Only escalate here when the gap is real; say why in the rationale.
Pick the lowest depth that makes the CV land. State which you chose and why.

## 3. Draft the edit-plan (truthful, evidence-backed)
Build the changes, each traceable to a bank entry:
- **Summary** — one rewrite tuned to the JD (offer a 2nd variant if it's a close call). Keep ~2–4 sentences.
- **Skills** — reorder lines and reorder terms within a line to front-load JD keywords Ben actually has. You may
  add a term ONLY if a bank entry backs it (e.g. surface `Vertex AI / Gemini / Genkit` or `FastAPI` for an AI
  role). Never drop a whole line without saying so.
- **CLOUD TRANSLATION — mandatory whenever the JD names a cloud Ben has not used.** Ben's cloud is Google
  Cloud; roughly half the market writes its infrastructure requirement as AWS. The Cloud skills line names
  **his** services first and the requested cloud's equivalents in parentheses, so the token reaches the
  string match without the document claiming the work:
  `Cloud: Google Cloud — Cloud Run, Cloud Functions, Cloud Storage, Pub/Sub, Firestore (AWS equivalents:
  ECS/Fargate, Lambda, S3, SNS/SQS, DynamoDB); Docker, containerized services & autoscaling`
  **Skills line only — a foreign-cloud service name in a summary or an experience bullet is a false
  claim** and `cv/test_claims.py::test_no_cloud_claim_in_an_experience_bullet` fails on it.
  **Map services, and only the ones he ran** — Cloud Run, Cloud Functions, Cloud Storage, Pub/Sub,
  Secret Manager, Firestore, Vertex AI. Nothing else has a counterpart (`CloudFormation` and any IaC do
  not — that stays a cover-letter gap). **One target cloud per req, never a matrix**: Azure req → Azure
  Functions, Blob Storage, Service Bus, Container Apps; a req listing *"AWS, Azure or GCP"* is already
  satisfied by GCP so it gets one clause, not two; no cloud named → no parenthetical. `Azure OpenAI` is
  **never** written even when the req names it (DO-NOT-CLAIM bans OpenAI; use `Azure AI Foundry`).
  Never `cloud-agnostic`, never a standalone mapping sentence. Full rule and reasoning:
  `docs/knowledge-base/personal/tailoring-playbook.md` → **"Cloud translation"**. This is a vocabulary
  bridge, not evidence — still name the gap in the README and the cover letter (§8).
- **Bullets per experience section** — reword/reorder/(if aggressive) swap. Every bullet must map to a bank
  entry; keep Ben-asserted numbers only if already in the base or bank, never invent numbers.
- Respect **DO-NOT-CLAIM**: Reazy AI = Gemini not Anthropic; CI/CD = jobs-db not Reazy; no undocumented metrics;
  reazy-inference is CPU; nvidia-* architectures aren't Ben's; etc.
- **If the plan has an `insert_experience` entry for job-hunt-kit, its `subline` MUST carry the repo as a
  live link** — the project and its URL always travel together (`docs/knowledge-base/personal/links.md`). It is a
  clickable blue `github`, matching the Reazy links, **never a pasted URL in grey text**:
  `"subline": "2026 – Present  |  [github](https://github.com/Ben-Bot-22/job-hunt-kit)  |  <techs>"`.
  The renderer turns any `[label](url)` in a sub-line into a real hyperlink styled from the base
  document's own links. It is never a header link — only on documents that name the project.

## 4. Present options for approval — BEFORE generating anything
Show Ben, in chat, a tight preview he can approve or adjust:
- chosen **depth** + one-line why, and the target **folder name** (see §6).
- the **new summary** (and alt, if any).
- the **skills** block, in the new order (mark what moved / was added).
- a **bullets diff** per changed section: `old → new`, each with a 2–4 word rationale (e.g. "echoes JD 'event-driven'").
- any **flags**: keywords in the JD that Ben has NO evidence for (list them honestly — do not paper over gaps),
  and a note if it's at risk of running >1 page.
Use AskUserQuestion for real either/or choices (e.g. two summary directions); otherwise just lay it out and ask
"approve / tweak?". **Do not render the document until Ben approves.**

## 5. Render (only after approval)
Write the approved plan to the app folder as `plan.json`, then:
```bash
.venv/bin/python cv/scripts/render_cv.py \
  --base profile/cv-base.docx \
  --plan <folder>/plan.json \
  --out  <folder>/<name>_cv.docx --pdf
```
`<name>` is the seeker's own name from `profile/profile.yaml → identity.name`, lowercased and
underscored (`Robin Doe` → `robin_doe`) — the filename a recruiter sees, so it is theirs and not a
literal in this file.
Then **one-page check**: `pdfinfo <folder>/<name>_cv.pdf | grep Pages`. If >1 page, tell Ben and propose
specific trims (usually drop/merge the weakest 1–2 bullets), re-render after he picks. Optionally render a
preview PNG for a visual check: `pdftoppm -png -r 110 -f 1 -l 1 <pdf> <folder>/preview` then view it.

## 5b. THE AI-GLOSS PASS — mandatory, on the rendered PDF, before Ben sees anything
**Read the rendered PDF back** (not the plan — gloss hides in prose that looked fine as JSON) and cut
fluff and AI-sounding writing. The full catalogue, with the research behind it, is
`docs/knowledge-base/personal/tailoring-playbook.md` → **"THE AI-GLOSS PASS"**. Do not work from memory; open it.

The one diagnostic: **does the sentence add a fact, or add a stance?** A résumé line states a fact a
screener can match. The moment it argues, reassures, frames or concludes, it has stopped earning space.

Highest-yield three, do these first:
- **Negative parallelism** — `not just` / `not only` / `more than just` / `isn't about X, it's Y`. Cut the
  negated half, keep the fact.
- **Em-dash payoff clauses** — a dash bolting a *moral* onto a fact. (A dash joining two facts is fine.)
- **Defensiveness in any costume** — if a line reads as a reply to an objection, delete the defence.

Then: rule-of-three padding, the *delve/leverage/robust/seamless/spearheaded* register, abstract-noun
subjects (*delivery, practice, approach*), overspecification (*on the command line, from the ground up*),
invented quantities, and **skills lines that grew verbs** (a skills line is a keyword list — no clauses).

**For each hit ask: does deleting this lose a fact or a keyword? If no, delete — do not rewrite.**
Rewriting is how a hedge becomes a different hedge; that happened three times on 2026-07-28.

**Re-render after cutting, and report the cuts in step 8** so the pass is visible rather than silent.
There is deliberately **no test** for this — see the playbook section for why a style ban is dodgeable
by substitution and was already reversed once.

## 5c. Grade it, fix it, grade it again — max 2 passes
```bash
.venv/bin/python -m cv.review_cv <folder>            # writes review.json, exits 3 if below bar
```
The reviewer sees **only** `jd.json` and the rendered PDF — never the plan, the bullet bank, or a word
of your reasoning, because each of those is a way to argue that a weak CV is fine. It scores four
dimensions 1-5 and the bar is **every** dimension ≥4 (not a mean: a strong keyword match must not
carry a CV that sells nothing).

Loop: **apply the fixes → re-render → re-run.** Stop when it passes or after 2 passes (`cv/review_cv.py → MAX_PASSES`, cut from 3 on 2026-08-04 — measured over 19 documents, the third pass changed nothing on 8 of 10 and was where the grader pushed hardest for the fixes that must be refused).

**Two rules, both learned on the first live run (2026-07-28, the Apex CV):**

- **The bullet bank and Ben's stated preferences OUTRANK the reviewer.** Being blind is what makes it
  useful and is also what makes it wrong sometimes. On pass 1 it proposed adding `SQL`, inventing a
  test count, and renaming the headline to "AI-Assisted" — all three are forbidden (DO-NOT-CLAIM, no
  undocumented metrics, and Ben's AI-native call). **Refuse those fixes and say so in the report;
  never edit the bank to satisfy a grade.** Same precedence as the rubric over retrieved precedent in
  `triage/precedent.py`, and for the same reason.
- **Stop early when the gap is structural, not fixable.** If the only sub-bar dimension is
  `keyword_coverage` and its misses are `absent` terms with no evidence behind them, more passes
  cannot help — the honest fix is a cover-letter gap, not a bullet. Report it as **partial fit** and
  say how many must-haves are unclaimable. On the Apex req that was **11 of 23**, which is a fact
  about the job, not a defect in the document. Do not burn passes writing around it.

Then run **5b (the AI-gloss pass)** on the final render — the reviewer grades readability but does not
know the house style.

## 5d. If you changed the generator, measure it — do not assert it
Changing how CVs are made (a prompt, the plan shape, the bullet-picking rules) is a change whose effect
nobody can see by looking. Before and after:

```bash
.venv/bin/python -m cv.run_eval before-<change>       # then make the change
.venv/bin/python -m cv.run_eval after-<change>
.venv/bin/python -m cv.run_eval --compare
```

Two frozen cases in `cv/eval_set.json`. **The measured noise floor is 0.25 mean points** — the grader
disagreeing with itself over unchanged documents — so **a movement smaller than that is not evidence
of anything** and must not be reported as an improvement. The per-keyword counts are noisier still
(the same résumé scored 1-absent and 5-absent across two identical runs); quote dimension scores, never
a keyword count, as a before/after.

This does not run per-CV. It runs when the machinery changes.

## 6. Naming & storage (folder per application)
Create `applications/<YYYY-MM-DD>_<company-slug>_<role-slug>/` (date = today from context; slugs = lowercase,
hyphenated, e.g. `2026-07-06_acme_senior-fullstack`). Write into it:
- `<name>_cv.docx` and `<name>_cv.pdf` — the deliverables (see the naming rule in step 5).
- `plan.json` — the exact edit-plan used (so a re-render is reproducible).
- `jd.txt` — the job description (or its URL + fetched text).
- `README.md` — company, role, JD link, chosen depth, and a short "why these changes" so the folder is
  self-explanatory months later. This is how Ben remembers why each CV exists.
`applications/` is gitignored — these are local per-application artifacts, and **nothing under it is
tracked**. (Two dozen folders were tracked by accident until 2026-07-24, predating the ignore rule;
they were untracked when the archive landed. Don't `git add -f` them back.)

**Always write a new folder at the TOP level of `applications/`, never into `applications/archive/`.**
The top level is the live set — the jobs on the current apply doc — so it stays scannable. When a run
closes a job out (applied, closed, or superseded), move its folder into `applications/archive/`.
Archiving is **one-way**: nothing comes back out, so the boundary never churns. The archive is flat;
if it ever gets unwieldy, bucket it by month rather than pruning it — a superseded résumé is still the
record of what was sent.

Do not use "current" as a date rule. On 2026-07-24 three still-live jobs had folders dated 07-22 and
07-23, and a pure date cut would have buried them.

## 7. Feed the knowledge back — and "feed" means DOCUMENTATION, not the bank

**A lesson is something you write down so a later run can look it up. It is not a new claim about Ben.**
Route it, and the third row is the one that has been got wrong:

| what you learned | where it goes | ask first? |
|---|---|---|
| strategy, positioning, a target's playbook, a framing rule, what a client type rewards | `docs/knowledge-base/personal/tailoring-playbook.md` | **no — write it** |
| a fact about this one application (a gap, a canary, why a bullet was picked) | that application's `README.md` | **no — write it** |
| **a genuinely NEW bullet, or new evidence for one** | **`profile/bullet-bank.md`** | **YES — propose in chat, wait for Ben** |

**`profile/bullet-bank.md` is protected — see the notice at the top of that file.** You may read it
freely and you must ask before you write, every time, including inside a run Ben started himself.
A "yes" to *tailor a CV* is not a yes to edit the bank. **Propose the bullet in step 8 with its
evidence and confidence; apply it only after he approves.** Same precedence as `cv/review_cv.py`
reporting fixes it never applies, and as `/tailor-cv-batch` agents being read-only on the bank.

**Why it is not merely tidy:** every line in the bank becomes a factual claim about Ben in a document
sent to an employer. He is the only one who can say whether it is true and whether he wants to be asked
about it in an interview. Reverting later does not help — the claim may already have shipped.
*(2026-07-30, Sift: an agent read this step as licence and added a bullet unprompted.)*

## 8. Report
Tell Ben: folder path, page count, depth used, the headline changes, **the reviewer's four scores and
how many passes it took (step 5c)**, **any reviewer fix you REFUSED and why**, **what the AI-gloss pass
cut (step 5b)**,
and any honest gaps (JD keywords with no evidence) he may want to address in a cover letter. Mention the
docx + PDF are ready.

## Rules
- **Truthful only.** Every claim traces to `profile/bullet-bank.md`. Never invent tech, metrics, or ownership. When
  the JD wants something Ben lacks, surface the gap — don't fabricate to fill it.
- **Approval gate is mandatory** — never generate the document before Ben approves the changes (§4).
- **Never edit the base** (`profile/cv-base.docx`) or overwrite another application's folder.
- Refresh the bank (re-mine the repos) if a project changed materially since `bullet-bank.md`'s last-refreshed
  date — note jobs-db's RAG extension is expected to land and should be added when it does.
- Keep to one page unless Ben says otherwise.
