---
name: setup
description: Set up jobs-db for whoever is sitting there — read their résumé into a bullet bank, ask about anything it can't back, write the profile, the rubric and the settings, and present the channel menu before anything is fetched. Use on a fresh clone, when someone asks how to configure this tool, or when a profile needs rebuilding from a new résumé.
---

# Set up jobs-db

The tool needs three things it cannot infer: **who you are** (`profile/profile.yaml`), **what a 10/10
job looks like to you** (`profile/rubric.md`), and **how the run should behave** (`config/settings.yaml`).
Hand-editing those cold, from an empty clone, is the worst version of this. You are the interview
instead.

**Three rules. They are the shape of the whole skill, not decoration.**

1. **Nothing is fetched until the user has seen the channel menu and chosen.** Not a board listing,
   not a mailbox, not a URL. A tool that reaches out before you have told it to is a tool you have to
   audit before you can trust it, and the first five minutes is exactly when nobody has the patience.
2. **No OAuth at any point.** Never send anyone to a Google Cloud project or a consent screen. The
   Gmail channel is an unbuilt stub for precisely this reason — `paste` covers the cold start with no
   key beyond the model provider's, and `boards` is a keyless watchlist once the user names their
   target companies (it moves the cold start one step, it does not solve it).
3. **Ask, never invent.** Everything you write into the bullet bank becomes a claim the user has to
   defend in an interview. A résumé is thin on purpose in places; where it is, that is a question, not
   a gap for you to fill in with something plausible.

Résumé only. **A LinkedIn export is not accepted** — a scraped profile is not evidence, and half of it
was written by a recruiter.

## 1. Seed the shipped example, and find out what is already here

```bash
.venv/bin/python -m core.example
```

This copies `config/example/` — a complete configuration for a fictional seeker (Robin Doe) — into
`profile/` and `config/`. **It never overwrites a file that already exists**, and it prints what it
wrote and what it kept.

Read that output before doing anything else:

- **all five written** → an empty clone. You are writing everything from scratch.
- **some or all kept** → this clone is already configured. Say so, name the files, and ask which the
  user wants to rebuild. Then edit those files in place. **Never delete one to make the seeder
  rewrite it** — `profile/rubric.md` on a used clone is months of calibration and there is no undo.

The seeded files are Robin's, not the user's. Everything below replaces them. Anything you leave
un-replaced is a fictional Chicago backend engineer's answer standing in for theirs, so say plainly at
the end which files you touched.

## 2. Read the résumé

Ask for a path. Then read it:

| format | how |
|---|---|
| `.pdf` | read it directly — you can |
| `.md`, `.txt` | read it directly |
| `.docx` | `.venv/bin/python -c "import docx,sys; print('\n'.join(p.text for p in docx.Document(sys.argv[1]).paragraphs))" <path>` |

`python-docx` is declared in `cv/requirements.txt` (pulled in by the root `requirements.txt`). If that
one-liner fails, the install is incomplete — ask the user to export to PDF or paste the text rather
than installing anything to work around it.

**If the résumé is a `.docx`, copy it to `profile/cv-base.docx`** — that is the template `/tailor-cv`
edits in place (preserving the user's own fonts, spacing and links), so their real résumé becomes the
base: `cp <path> profile/cv-base.docx`. If they only have a PDF or text, tell them `/tailor-cv` needs a
`.docx` base and point at `config/example/cv-base.docx` as the structure to match; it is bring-your-own,
never invented. `core.example` does not seed a base résumé — a CV is too personal to hand someone a
fictional one as if it were theirs.

## 3. Mine the bullet bank — and mark what you could not back

**This is the one workflow that writes the bank without asking each time**, because the user is sitting
here being interviewed about every claim — the approval is the conversation. Once it exists the file is
**protected**: every later write, in every other workflow, is proposed and waits for their yes. Say so
when you hand it over, and put the notice at the top of the file you write.

Write `profile/bullet-bank.md` in the shape of the seeded example: identity/summary raw material, one
section per role or project, and a **DO-NOT-CLAIM** list at the bottom. The format carries the
evidence:

- `**[high]**` — they can walk an interviewer through the code. `[med]` — inferred from structure or
  a doc. `[low]` — thin, and say why.
- Numbers in `[brackets]` are **asserted rather than measured**. Every number that came off the
  résumé with no source behind it goes in brackets until the user confirms it in step 4.
- The DO-NOT-CLAIM list is not optional and it is not a formality. It is what stops `/tailor-cv`
  turning a JD keyword into a claim: a technology the user has read about, a leadership scope they
  don't have, a years-of-experience number they don't want to state.

## 4. Ask about everything thin — once, in one batch

Collect the questions as you mine, then ask them in **one message**, each with the reason you are
asking. A drip of one question at a time is how an interview becomes a chore and the answers get
shorter.

What counts as thin, and what to ask:

| what you found | the question |
|---|---|
| a metric with no source — *"improved performance by 40%"* | what was measured, against what, and can you point at where it's recorded? |
| a technology in a skills list with no project under it | shipped it, or read about it? (read about it → **DO-NOT-CLAIM**) |
| *led* / *owned* / *architected* with no scope | how many people, and who carried the pager? |
| a title that doesn't match the duties beneath it | which one would you rather be interviewed on? |
| a consultancy or agency role with the client unnamed | can the client be named, or is it under NDA? |
| a gap or an overlap in the dates | what was happening then — and do you want it on the CV? |
| an open-source or side project | is it public, and is there code a stranger can read? |

Cap it at roughly eight questions. Anything still unanswered after one round stays out of the bank or
goes in at `[low]` with the doubt written into the bullet — **never** promoted to fill the space.

## 5. Write the identity file

`profile/profile.yaml`. Small, and three of its five keys are legitimately empty:

- `inbox:` — leave it blank for now. It is only read by the `mail` channel, and the channel menu is
  step 7. Coming back to it after the menu is the point.
- `archive_mailbox:` — empty means archiving off. Right for anyone not running `mail`.
- `applied_sheet:` — a Google Sheet id, read in-session by `/sync-applied`. Empty is fine; the dedup
  cache then holds only what the tool has seen itself.
- `primary_agencies:` — recruiters who have actually placed them. Empty is fine. Do not seed it with
  famous staffing firms the user has never dealt with; this list promotes a posting to the top tier.
- `secondary_platforms:` — contract marketplaces. The seeded list is real platforms rather than
  invented ones, so it is the one block worth keeping if it fits.

## 6. Write the rubric

`profile/rubric.md` is **the prompt**. The whole file is injected into the analyzer verbatim, nothing
parses it, and no typo in it can stop the tool booting. Write it as prose in the user's own terms,
following the seeded example's section order:

**IDEAL ROLE** — the 10/10. Remote / hybrid / onsite and from where. Permanent or contract, and which
one loses a tie. The **hard floor** on money, stated the way they think about it (salary or hourly —
a rubric that says $130k to someone who bills hourly is a rubric they will not trust). Intensity on a
1–5 scale and what time is protected. In-lane skills. What is adjacent enough to be tailorable.

**DOWNRANK** — shown, ranked lower. This is where most of the user's real opinions live, so ask for
them rather than reasoning them out: what makes a posting worth seeing but not worth wanting.

**HARD FILTERS** — SKIP outright. Keep them to facts you can check and be right about (location,
  a posted rate below the floor, a required clearance, a primary stack they do not have). The example: it keys on the
tells (concatenated EAD categories, a vendor that withholds the client outright, in-person-only as a
*corroborating* signal) and never on "is this a staffing firm", because for many people agencies are
the best supply channel there is. Add the user's own: a clearance they don't have, a stack they refuse.

**CALIBRATION** — leave it near-empty with a note. It is the section that fills itself in: after a few
runs the user will disagree with a score, and the fix is to write that case down here in the form
*"this job, scored X, should have been Y, because …"*. Say that out loud during setup — an anchor with
no worked examples is the single biggest source of scores people don't recognize.

Do not copy Robin's numbers, cities or stack across. If a section ends up sounding like the example,
you guessed instead of asking.

Point the user at **`docs/operating/rubric.md`** before moving on. It is the manual for the file you
have just written for them — the section vocabulary, the downrank / cap / hard-filter distinction,
and how to change it when they disagree with a score. Writing someone's rubric and not telling them
where that is documented is how it stops being edited after week one.

## 7. The channel menu — present it before anything runs

This is the gate. Show the table, in full, and let the user choose. **Every channel is skippable, and
`paste` works with nothing configured at all**, so "none of them" is a real answer and not a failure.

| channel | what it needs | OS | key / OAuth | default |
|---|---|---|---|---|
| **`paste`** | nothing — job URLs on the command line (`--paste URL …`) or a file of links (`--paste-file`) | any | none | **on, always** |
| **`boards`** | Greenhouse / Lever board tokens you name | any | none | **on** — starter tokens below |
| **`agencies`** | nothing — six staffing firms' own boards, scraped | any | none | off — say yes if you want **contract** work |
| **`mail`** | Apple Mail with the account already configured | **macOS only** | none | off — the one channel a stranger may be unable to use |
| **`gmail`** | an OAuth client and your consent | any | Google OAuth | **not built.** A documented stub that raises if enabled — leave it off |

Three things to say out loud rather than leaving in the table:

- **`agencies` is the only channel that returns contract work**, so whether to turn it on follows from
  one question: are they looking for contract or perm? `boards` returns permanent roles at product
  companies; the staffing firms are where contract reqs actually get posted. It costs no key and it
  works on any OS, but it is a *scrape* of six live sites — a minute or two of wall-clock before the
  run starts, and the scrapers break by returning zero rather than by raising. That is why it is off
  by default and why the run summary prints per-source counts: `agencies 45 (insightglobal 30,
  teksystems 15, motion 0 ⚠)`. Tell them to read the parenthetical — it is the only rot detector.
- **`mail` is macOS-only, and it is off by default even there.** It reads a configured Apple Mail
  account over `osascript`. On Linux or Windows it is not a slow path or a degraded path, it is
  nothing. Say so before they choose, not after.
- **`gmail` is deliberately unbuilt**, and it *raises* rather than returning an empty list — an empty
  list would look exactly like a working channel with a quiet inbox. Making someone clear a Google
  consent screen before the tool has produced anything is a worse first run than the macOS limit it
  would fix. If they want it, `triage/channels/gmail_api.py` has the contract, the scopes and the
  functions to reuse.

Write the choices into `channels:` in `config/settings.yaml`. Every channel needs an explicit
`enabled:` — an unconfigured channel defaults to **on**, so a `gmail` block left out prints
`gmail CRASHED` in every run summary.

If they chose `mail`, go back and fill `inbox.account` and `inbox.mailbox` in `profile/profile.yaml`
now.

### Board tokens

A board token is the slug in the board's URL: `job-boards.greenhouse.io/`**`anthropic`** ,
`jobs.lever.co/`**`gopuff`**. Ask for the companies the user actually wants to work for and pull the
tokens out of their careers-page URLs — that is what makes this a watchlist rather than a sweep.
[`docs/operating/channels-boards.md`](../../../docs/operating/channels-boards.md) is the full usage
page — token discovery, the pre-commit verification command, and the cost model — to point the user at
after setup.

For anyone who doesn't have a list ready, `starter-boards.md` in this directory is a set of live,
keyless boards with measured posting counts. **Seed at least two so the channel is not empty on the
first run** — a channel that reports `boards 0` on day one reads as broken.

Say the cost before they pick ten: every posting in the window that survives the cheap screen costs
one Opus call. The measured counts in `starter-boards.md` are per seven days, and they add up fast.
Two or three boards is a good first run.

## 8. The key

One line in `.env` at the repo root, and nowhere else:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`anthropic` is the tested provider; `openai`, `google` and `ollama` are registered and untested — see
the README's provider table, and `llm.provider` in `config/settings.yaml`. Never echo a key back into
the conversation, never write one into a settings file, and never commit one.

Check the config loads before anything else:

```bash
.venv/bin/python -c "from core.settings import settings; settings(); print('settings ok')"
```

Silence-plus-`settings ok` is a pass. A failure names the offending key and points at
`config/settings.schema.json`, which is the machine-readable list of every setting.

## 9. The first run

Now — and only now — fetch something. Start with a job the user already cares about, because a first
result they can judge is worth more than twenty they can't:

```bash
.venv/bin/python -m triage --paste <a job URL>
```

Then a real window over whatever channels they enabled:

```bash
.venv/bin/python -m triage --days 3
```

Read the run summary with them. The per-channel counts line (`mail off · boards 18 · paste 1 ·
gmail off`) is the thing to point at: `off` and `0` mean different things, and knowing which channel
is actually supplying jobs is how they decide what to fix.

The output is `matches/<date>.md`. Walk them through one entry — the verdict, the fit score, the
`why` line, the red flags — and ask whether they agree with it. **Whatever they disagree with is the
first CALIBRATION entry**, and adding it is a normal markdown edit to `profile/rubric.md`.

## 10. What the second run does that the first one can't

Worth showing, because it is the part nobody expects. At the end of every run the tool indexes what it
just judged into `data/corpus/`. From the second run on, each job is scored with the most similar past
judgments retrieved and placed in front of the model — so the rubric stops being the only anchor and
the user's own accumulated decisions start carrying weight. When it fires, the worklist entry carries
a `precedent:` line naming the job it reasoned from.

That is why the CALIBRATION conversation in step 9 matters more than it sounds: a correction written
down once propagates through every future run that retrieves it.

## Notes

- **Portable on purpose.** This is a skill rather than a slash command so it works in whichever agent
  the user has. Everything here is plain markdown and shell — read
  `docs/knowledge-base/research-cross-agent-portability.md` before changing that.
- **What this skill must never do:** fetch before step 7 · overwrite a `profile/` file that already
  has real content in it · write a bullet the user hasn't confirmed · send anyone to a Google Cloud
  console · put a key anywhere but `.env`.
- The full configuration reference is the README's "Making it yours" section; the operational keys are
  `config/settings.schema.json`; `docs/operating/triage.md` is the runbook once they are set up.
