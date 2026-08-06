---
name: apply-form
description: Fill out a multi-step online job application in the seeker's browser — one page at a time, audited against the CV, with the seeker approving each page before moving on. Use when an in-progress application (Workday, Greenhouse, Lever, iCIMS, Taleo) is handed over to be completed.
---

# Fill out an application form, one page at a time

**The seeker is sitting there watching.** This is not an unattended workflow: they hand over a browser
tab with an application already open and part-filled, and the job is to complete **one page**, hand it
back for a look, and stop. They advance the form, not you.

**Why the skill exists at all:** every ATS offers "autofill with résumé", every one of them mangles it,
and the mangled version — not the attached PDF — is what a recruiter screens on. Fixing that by hand is
mechanical, slow, and exactly the kind of thing that gets rushed at the end of an application.

---

## 1. The tab protocol — read this before touching the browser

**You open the group; the seeker puts their application tab into it; you never close a tab.**

```
1.  tabs_context_mcp { createIfEmpty: true }     → creates the group, with one blank tab
2.  tell the seeker the group is open, and WAIT
3.  they drag/add the in-progress application tab into it
4.  tabs_context_mcp                              → their tab is now listed; work in THAT tabId
```

**Never call `tabs_close_mcp`, and never navigate their tab.** Both have cost a session already:

- **Closing any tab in the group tore the whole group down**, including the seeker's own manually-added
  tab, twice on 2026-07-30. *Mechanism inferred, not confirmed:* the extension appears to track the
  session group by the tab **it** created, so closing that one ends the session even though the seeker's
  tab is still visually in the Chrome group. Whatever the cause, the observable rule holds — **let the
  seeker manage tabs, always.**
- **Navigating to the apply URL to "get back in" started a second application flow** at step 1 while the
  real one sat at step 3. Workday keeps one draft server-side, so a duplicate tab is a way to overwrite
  progress, not recover it. If you have lost the tab, **say so and ask them to re-add it.**

**When the group vanishes mid-run, do not re-create and re-navigate.** Report it, and ask them to quit
the Claude desktop app — it competes with the Chrome extension for the connection, and this drop
pattern is what that conflict looks like.

## 2. Read the whole page before changing anything

Screenshot, then dump every field's real value — `get_page_text` shows labels but **not** what is in the
inputs, so it will tell you a form is empty when it is full of a parser's guesses:

```js
const lbl=el=>{const l=el.labels&&el.labels[0];return l?l.innerText.trim().replace(/\s+/g,' '):(el.getAttribute('aria-label')||el.name||el.id||'?')};
[...document.querySelectorAll('input,textarea')]
 .filter(el=>el.type!=='hidden' && !/dateSection/.test(el.getAttribute('data-automation-id')||''))
 .map((el,i)=>i+' ['+el.type+'] '+lbl(el)+' :: '+JSON.stringify(el.value||el.checked)).join('\n')
```

Dropdowns are often `<button aria-haspopup>` rather than `<select>` — list those separately, and read
the options before assuming a value is available.

## 3. Audit the autofill against the CV — assume it is wrong

The source of truth is the **rendered CV in the application folder**, and behind it
`profile/bullet-bank.md`. The parser's output is a claim to be checked, never a starting point to tidy.

**Failure classes seen in the wild** (all five, Workday, Link Logistics, 2026-07-30 — one résumé became
five jobs):

| what it does | example |
|---|---|
| **Invents a job from a bullet fragment** | "Sole developer" became a job title with a blank company |
| **Uses one job's title as another's company** | Independent Game Developer at *"Economist — US Air Force"* |
| **Loses a required field entirely** | an entry with a blank Job Title and "Pentagon" as the employer |
| **Reads a location as the employer** | Pentagon and Tinker AFB are where he worked, not who employed him |
| **Ticks every box the same way** | *"I currently work here"* checked on all five, four of them ended years ago |
| **Upgrades a degree** | **BBA → MBA** |

**That last one is the one to hunt first.** A parser turning a bachelor's into a master's is a
**false credential on an employer's form**, and once the page is saved it is not a parsing artifact any
more — it is something the seeker asserted. Check degree, dates, titles and employer names against the
CV on every application, every time.

## 4. Standing data

`docs/knowledge-base/personal/links.md` holds the links, the handles and the answers to fields the CV
deliberately will not carry. **Read it; do not re-ask and do not hardcode any of it here** — a value
copied into this file is a value that goes stale while still loading every session.

**The one that trips agents:** *years of experience.* `profile/bullet-bank.md` → DO-NOT-CLAIM forbids a
years number on the **CV**, and `cv/jd_parse.py` drops years bars from the brief for the same reason. A
required *Years of experience* form field is a different artifact — the number is in `links.md`, given
by the seeker for exactly this use. Type it into the field; never let it reach a document.

**CV prose is not automatically the form answer — check `links.md`'s table before copying it.** A
résumé header can carry a brand or framing choice ("Reazy LLC") that is the wrong thing to type into a
form field asking the same-looking question (a "Company" field, closer to a background-check fact than
a résumé header). Learned 2026-07-30 on the Link Logistics Workday form: an agent copied "Reazy LLC"
from the tailoring playbook into the Company field; the seeker's correction was "the company name is
Reazy, not Reazy LLC." **When a form field and a résumé line look like the same fact, they are not
automatically the same claim** — check `links.md` first; if it's not there, ask rather than copy.

**Degree dropdowns rarely offer what the seeker's diploma literally says.** Ben's UCO degree is a
B.B.A.; most ATS degree pickers offer only BA/BS. This is not solvable by looking anything up — it is a
standing choice the seeker makes once, and `links.md` records the resolved answer (BS) so it is applied,
not re-asked, on every subsequent form. **GPA is the same shape**: never inferred, never left blank
without asking once — the seeker's numbers are in the same table.

## 5. What you may fill, and what you must ask about

**Fill without asking** — anything that is a fact already on the CV or in `links.md`, and any correction
of a parser error back to what the CV says. Names, dates, titles, employers, locations, degrees, role
descriptions lifted from approved CV bullets, the links block.

**Stop and ask** — anything where two answers are defensible or where the answer is not written down:

- Salary expectations, desired rate, notice period, start date.
- Work-authorization and sponsorship phrasing beyond the plain facts.
- Whether a side project counts as *Work Experience* (a real fork: it is on the CV as an entry, and a
  screener reads the parsed form rather than the PDF — but an unpaid concurrent project listed as a job
  invites a question).
- "Why this company", "why are you leaving", or any free-text field that is an argument rather than a fact.
- Which location or office a multi-city req should be submitted against.
- Anything the form asks that the CV, the bank and `links.md` between them cannot answer.

**Ask once, in one message, with a recommendation** — not a survey. Same rule as `/evaluate-role`.

## 6. Free text goes through the voice rules

Any box that takes prose — role descriptions, "tell us about yourself", cover-letter fields, screening
answers — is **writing as the seeker**, so it obeys the same rules as everything else that is:
`docs/knowledge-base/personal/tailoring-playbook.md` → the three-question jargon test, the two
stop-lists, and **THE AI-GLOSS PASS**. Reach for `/cover-letter` for anything longer than a sentence.

Role-description boxes are the exception that is easy: paste the CV's own bullets for that entry. They
are already approved, already plain, and already the thing the attached PDF says.

## 7. Never, on any form

- **No credentials.** Never type a password, never create an account, never complete a CAPTCHA. If the
  form demands one, hand it back to the seeker.
- **Never submit.** Do not click Submit, Continue-to-final, Apply, or any confirm control on the last
  page. *"Save and Continue"* between pages is only ever clicked **after** they have approved that page.
- **No demographic or voluntary-disclosure answers.** Race, gender, veteran status, disability — the
  seeker fills those in themselves, always. Read the page, say it is there, and stop.
- **No invented facts.** A blank required field with no answer in the CV is a question, not a guess.

## 8. Hand it back

After each page: a screenshot, then **what changed and what you refused to guess** — short, one line
each. Name the fields you corrected against the CV and the ones still open. Then stop and wait.

Record the application in the role's file under `docs/knowledge-base/personal/roles/` when it is
submitted — which req, which office, and anything asked on the form worth knowing next time
(a screening question, a required field nothing in the repo answered).
