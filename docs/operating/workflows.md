# The five workflows, and your equivalents of them

> The Python is general. The five prose workflows in `.claude/skills/` are not — they were written as
> one person's runbook, and they still read that way: a named user, a Gmail label, a Google Sheet, a
> Mac. This maps each assumption onto what yours would be.

**They are meant to be edited.** The contribution policy is *fork it and make it yours*, and these
five files are the most fork-shaped thing in the repo — prose, no schema, nothing parses them, and
changing one cannot break the pipeline underneath. Rewriting the second person out of them and
putting your own rules in is not a modification of the tool; it is how the tool is used.

Read the skill you care about first (`.claude/skills/<name>/SKILL.md`); this page is the diff between
its author's setup and a stranger's.

| workflow | what it assumes | your equivalent |
|---|---|---|
| **`/setup`** | nothing — it is the front door | as shipped |
| **`/job-triage`** | Apple Mail on macOS · a Gmail label to archive into · Chrome for walled JDs · an applied-jobs Google Sheet · one person's pay floor and ranking rules | your enabled channels · your label, or nothing · `--no-browser` · skip step 0 · **your `profile/rubric.md`** |
| **`/sync-applied`** | a Google Sheet, read through a Drive connector | any spreadsheet, any CSV, or nothing — `profile/skiplist.md` is the keyless path |
| **`/tailor-cv`** | a `.docx` base CV with a known layout · a bullet bank · LibreOffice | your own base and bank; LibreOffice only for `--pdf` |
| **`/research-company`** | nothing configured at all | as shipped |

## `/job-triage`

Nine steps, of which the script is one. Four assumptions to translate.

**Where mail comes from.** Step 1 is `python -m triage`, and what it reads is whatever is enabled
under `channels:` in `config/settings.yaml`. `mail` is Apple Mail and macOS-only; if you are not on a
Mac, turn it off and the same nine steps run over `boards`, `agencies` and `paste` unchanged. The
workflow does not know or care which channel produced a job.

**Archiving.** Step 5 labels each processed thread and removes it from `INBOX` through a Gmail
connector in your agent — it is prose, not Python, so it needs both a Gmail account *and* a client
with that connector. Without either, delete the step. The cost is named in the README's tier 3: the
run is unaffected, dedup means no duplicate output, but **processed mail stays in your inbox**. The
label id is not written down anywhere in the skill; it is looked up by name at run time, so pointing
it at a label you created is a one-word edit.

The backstop in that step is worth keeping whatever you do with the rest of it: **skip any thread
containing a sent message.** Gmail archives per thread and the list is per message, so archiving one
line of a live conversation removes the whole conversation — replies and unread mail included — from
your inbox. That rule exists because it happened once, to an interview thread.

**The browser.** Step 2 pulls walled JDs through a logged-in Chrome, which needs a browser-driving
tool in your agent and a human nearby for the occasional CAPTCHA. `--no-browser` is the supported way
to skip it; those jobs are scored from the title and whatever the listing gave up, and land in the
worklist's manual-check list rather than vanishing.

**The ranking rules, and this is the one that actually matters.** Step 6 writes the apply document and
restates a specific person's standard inline: a pay threshold, *rank on drain not comp*, *a good perm
wins*. **Your version of those lines belongs in `profile/rubric.md`, which is the file the scorer
actually reads** — the whole rubric is injected into the analyzer, whereas the skill's copy only
shapes how the day's picks are written up. If you change one, change both, and prefer the rubric: a
rule in the rubric applies to all ~350 jobs, a rule in the skill applies to the five you were already
shown.

Step 0 (sync the applied sheet) and step 7 (tailor résumés for the top picks) are just the two
workflows below, called. Drop step 0 if you have no sheet.

## `/sync-applied`

The point of this one is dedup against jobs you have already applied to, and the Google Sheet is an
implementation detail of one person's habit. **The real contract is a JSON array**, and anything that
can produce it works:

```bash
.venv/bin/python -m triage --sync-applied rows.json
```

Each row is `{company, title, city, url, confidence, note}` (plus an optional `row` and `apply_date`).
Python computes the canonical keys — the same `composite_id(company, title, city)` the ranker uses,
plus a normalized-URL key — and **replaces** `data/corpus/applied.json` wholesale; the source is
treated as the truth, so there is no merge to get wrong.

Three ways to feed it, in order of how little you need:

- **Nothing.** `profile/skiplist.md` is a hand-edited list of ids that never surface again. If you
  apply to two jobs a week, this is the whole feature and it needs no connector, no sheet and no
  model call.
- **A CSV.** The skill already falls back to this when there is no Drive connector: export whatever
  you keep, paste it, and the agent normalizes it into the array above.
- **A spreadsheet through a connector.** What the skill does by default. The sheet id is read from
  `profile/profile.yaml → applied_sheet` rather than written into the skill, so pointing it at yours
  is one line in your profile.

Why a model normalizes the rows rather than a column map: real applied-logs are free-form. In the log
this was built against, the company column was blank on about half the rows and the title landed in
whichever column got pasted into. `confidence` is how that mess stays safe — only `high` and `medium`
auto-block, `low` is surfaced for you to eyeball, because **a false dedup hides a job you never
applied to**, which is worse than one resurfacing.

**The sync runs one way and never writes back.** Your log is your dashboard.

## `/tailor-cv`

Three inputs, all in `profile/`, all yours: `cv-base.docx` (the template — never edited in place),
`bullet-bank.md` (the only place a claim may come from, including its DO-NOT-CLAIM list), and
`notes/tailoring-playbook.md` (reusable positioning strategy, which grows as you use it).

What generalizes cleanly: the output filename is built from `profile/profile.yaml → identity.name`,
so a recruiter sees your name; the per-application folder is `applications/<date>_<company>_<role>/`
and holds the docx, the PDF, the exact `plan.json` used, the JD and a README saying why. The approval
gate before anything renders is deliberate and is where you get a say.

What needs your attention: the renderer applies an edit-plan to *your* base docx, so it depends on
that document's structure (an experience section whose entries it can reorder and reword). Start from
the shipped base's shape or expect to adjust. `--pdf` shells out to LibreOffice (`soffice`) and fails
with a message naming it if it is not installed — the docx renders fine without it. The one-page
check uses `pdfinfo`, and skipping it costs you a check, not a document.

The playbook's rules — a Founder-framing rule, a never-state-a-years-number rule, per-platform
sections — are one person's, arrived at for reasons that may not be yours. They are prose in
`profile/notes/`, which is the configuration surface, not the code.

## `/research-company` and `/setup`

Nothing to translate. `/research-company` is the one thing that runs on a fresh clone with no inbox,
no corpus and no key — anything it cannot reach becomes a labelled open question rather than an
invention, and your own history with a company simply reads empty until you have some.

`/setup` is the front door: it seeds `config/example/` into your own `profile/` and `config/` without
ever overwriting a file that exists (`python -m core.example` is the same thing without the
interview), reads your résumé into a bullet bank, asks about anything the résumé cannot back, and
shows you the channel table **before** anything is fetched.

## If you have no agent at all

All five are prose. The Python underneath is not, and none of it needs an agent: `python -m triage`,
`python -m research`, `python -m research.market` and `python -m core.example`. What you lose is the
browser fetch and the mail archiving — the README's *Which agent runs the workflows* section is
precise about both, and [`scheduling.md`](scheduling.md) covers what that leaves you when the run is
unattended.
