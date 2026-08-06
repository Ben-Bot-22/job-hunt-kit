---
name: cover-letter
description: Write a cover letter, recruiter reply, or application-form answer in the seeker's own voice — bare, two paragraphs, tailored to the posting itself and anchored to letters actually sent. Use whenever something is to be written in the first person as them.
---

Write outbound prose as Ben. Not "professional writing about Ben" — **his voice**, which is far barer
and shorter than the default. This covers recruiter replies, form free-text and outreach too, not just
letters: the failure mode is identical in all of them.

**Everything about voice and rules already exists in this repo. Read it — do not re-derive it, and do
not add a parallel file for anything below.**

---

## 0. Read the posting IN FULL. First. Before drafting a word.

**This step is first because it was once skipped, and skipping it is the failure this skill exists to
prevent.** On 2026-07-27 a letter for Atlas Tech was drafted from the partial JD text the triage run
had captured. The full posting said **"US citizenship is a requirement for this position"** and
**"ability to work onsite with customers approximately 25% of the time"** — a hard gate and a logistics
term, neither of them in the snippet, both cheap to answer in four words.

- Fetch the JD from the posting itself. **A triage worklist entry, a `why` line, or an emailed digest
  is a snippet and is routinely truncated mid-requirement.** If the page needs a login, ask for a paste.
- Read all the way to the end. Requirements sections put the gating lines last.
- Pull out, explicitly:
  - **Gating requirements** — citizenship, clearance, work authorization, location, onsite/travel
    percentage, employment type (1099 / W2 / perm). These are pass/fail and usually screened first.
  - **Core stack**, in their words.
  - **The one thing they stress** — the line that tells you what they actually care about. That is the
    tie-in candidate.
- Note which stack items have **no** backing in `profile/bullet-bank.md`. Those are gaps to leave out
  of the letter and record in the application folder's `README.md` — never claims to stretch.

## 1. Research the company

Run **`/research-company`** (engine: `python -m research`) unless it was already run for this role this
cycle. It answers things the posting will not: agency vs direct employer, what else is on their board,
whether Ben has a history with them, and whether the same req is being shopped by multiple agencies.

Two things this changes about the letter:
- **A duplicate agency req means do not cold-apply** — it can cut across a process already in motion.
- It supplies the honest, specific tie-in that keeps the letter from reading generic.

Do not put the research in the letter. It decides *what to lead with*, and that is all.

## 2. Tailor by SELECTION, not by accretion

**This is the rule that resolves "keep it bare" against "tailor it to them."** The letter stays two
paragraphs whatever the target. Tailoring means **choosing which true fact leads** — not adding a
sentence to cover another requirement.

- Their stack is Python-first? Lead the build sentence with Python.
- Mission-driven or defense? Lead paragraph 2 with the Air Force decade.
- AI-native product? Lead with training and running the models.
- **Every requirement you "cover" by adding a clause makes the letter worse.** If the letter is growing,
  you are answering the JD line by line, which is what makes a letter read as machine-written.

## 3. Answer the gating requirements — briefly, and only those

Gating requirements are the exception to bareness, because they are pass/fail and cost almost nothing:
citizenship or work authorization, location, willingness to travel, employment type. **One clause,
folded into an existing sentence** — never a new paragraph and never a bulleted list.

> *"I'm a US citizen, OKC based, but willing to travel to fulfill duties."*

Everything else — a missing cloud, a missing database, a framework he has not used — stays out. Those
are conversation, and they belong in the application folder's `README.md`.

---

## Sources of truth — read all of these, every run

| File | What it gives you |
|---|---|
| **the posting itself** | **The requirements.** See §0. Nothing below substitutes for it. |
| `docs/knowledge-base/personal/tailoring-playbook.md` → **"Cover letters — Ben's preferences"** | **The rules.** The binding list. |
| `docs/knowledge-base/personal/ben-voice.md` | **The voice** — verbatim samples and the traits distilled from them. |
| `profile/letters/` | **The corpus** — letters actually sent. Outranks the trait list wherever they disagree. |
| `profile/cover-letter.json` | **The standing letter.** Copy it and edit; it is the shape a letter should be. |
| `profile/bullet-bank.md` | **The claims.** DO-NOT-CLAIM applies to letters exactly as to résumés. |

If a tailored CV was built for this role, read its `plan.json` too — **the letter must not contradict
the résumé in the same envelope.**

## The five rules that get broken most

In the playbook already; repeated here because each has been violated in a shipped draft.

1. **BARE, and no more than two paragraphs.** Ben, verbatim: *"anything more than this, it is obvious
   you are an AI."* A longer letter is the failure mode, not the safe choice.
2. **No numbers.** No user, subscriber or revenue counts — he rejected "500+ paying subscribers".
3. **The video goes inline in a sentence, never in a header or links block.** Write it as a body segment
   list so *"3-minute introduction video"* is the clickable text. **Add nothing to the header** — Ben on
   a links line someone added: *"this looks stupid."*
4. **Never tell the employer about themselves.** No "your team", no "the mission you're building for",
   no "your stack". State a fact about Ben and stop. Ben: *"do not tell them how their team works — that
   is horrible."* **Note the tension with tailoring and resolve it the same way every time: tailoring
   changes which fact about *him* you lead with, never adds a claim about *them*.**
5. **One JD tie-in, plainly — or none.** A list of matches reads as AI. Own words, never mirror the JD.
6. **No interpretive payoff clause — state the fact and stop.** A sentence that follows a concrete fact
   and explains what it *meant* is the loudest AI tell in the letter. Ben cut this one on 2026-07-27,
   after a paragraph naming Tinker, the Pentagon and the F100 engine: *"That job was turning what the
   mission needed into what had to get built."* His verdict: *"this screams AI and i hate this
   sentence."* **Test: delete it. If the paragraph still says everything factual it said, it was
   interpretation — leave it out.** The urge to write one comes from wanting to connect his experience
   to their posting; that connection is the reader's to make.

## Build first, then show — do not gate on approval

**Render the letter before showing it.** Write the JSON, run the renderer, then put the body text in
chat for Ben to reword. His rule, verbatim: *"make it first just in case it is good and there is no
delay."* Most letters are close enough to send, and waiting for sign-off on a draft costs a round-trip
every time.

**Always paste the body text into the message** — he rewords from chat, not by opening the docx — and
re-render on his edit. This is the same build-first default `/tailor-cv` uses.

## After rendering — the AI-gloss pass, then the check

**Run the AI-gloss pass before showing Ben anything** — `docs/knowledge-base/personal/tailoring-playbook.md` →
**"THE AI-GLOSS PASS"**. Open it; do not work from memory. A letter is more exposed to gloss than a CV
because it is prose, and the same nine tells apply. The three that recur here: **negative parallelism**
(`not just X, it's Y`), **em-dash payoff clauses** bolting a moral onto a fact, and **defensiveness** —
any sentence that reads as a reply to an objection nobody raised. Delete rather than rewrite; rewriting
is how a hedge becomes a different hedge. Say what was cut.

State plainly, in chat, in two lines:
- **which gating requirements the posting names, and whether the letter answers each**;
- **which stack items they asked for that have no bullet-bank backing**, so he goes in knowing the gaps.

**Do not assert anything about the posting you have not read.** If a requirement is inferred from
framing rather than quoted from the page, say "inferred" — a confident guess about a hard requirement
is worse than no guess.

## Render it

**`cv/scripts/make_cover_letter.py` is the renderer. There is no other one — do not write one.**
The letter is JSON (date, salutation, `body`, closing); the name/title/contact header comes from
`profile/profile.yaml → identity`, not from the letter file.

```bash
.venv/bin/python cv/scripts/make_cover_letter.py \
  --letter applications/<folder>/cover-letter.json \
  --out    applications/<folder>/<name>_cover_letter.docx --pdf
```

A body paragraph is either a plain string or a list of segments, where a segment is a string or
`{"text": ..., "url": ...}` — that is how a link becomes clickable inline.

## After it is sent

Append the letter to `profile/letters/` as `<YYYY-MM-DD>_<company-slug>.json`. Reusable *positioning*
lessons go to `docs/knowledge-base/personal/tailoring-playbook.md` — write those unprompted.

**A new verified fact about Ben goes to `profile/bullet-bank.md`, which is PROTECTED: read it freely,
ask before you write, every time.** Propose it in chat with its evidence and apply it only on his yes.
A "yes" to *write a letter* is not a yes to edit the bank; see the notice at the top of that file.

**And this whole section is for a letter that was SENT.** If Ben is exploring — asking for options, a
few angles, something to paste into a form — the answer is the chat message and nothing else. Do not
create a file in the application folder for it. *(2026-07-30, Sift: an agent turned "give me some
options" into a saved `form-answers.md` plus two documentation edits, none of them asked for.)*

`profile/` is classified PERSONAL by `scripts/extract.py`, so nothing there is ever published.
