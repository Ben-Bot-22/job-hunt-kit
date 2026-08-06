---
name: evaluate-role
description: Work through one job in depth — what it actually is, fit against the evidence bank, the interview loop, the trade — and record the decision. Use when a req or JD is pasted, when asked "should I apply / is this worth it / explain this job", or to go deeper on a pick from a triage run.
---

# Evaluate one role, in depth, and record it

Triage ranks the firehose. **This is the other half: one role, in conversation, going deeper than a
score** — what the job really is, who the customer is, what the interview demands, and what trade is
actually on the table. The output is a written decision that survives the session.

**Advisory. Assess and draft in-message; do not apply, send, or create drafts unless asked.**

## 1. Read, in this order — before writing anything

1. **`profile/rubric.md`** — the priority function. **Authoritative over anything you remember**, and
   the only copy that is current. Never judge a role without opening it.
2. **`docs/knowledge-base/personal/roles/preferences.md`** — how the seeker wants to be advised: the
   screening-format calls, the settled questions, the recurring gaps. This is the anchor for *this*
   system.
3. **`profile/bullet-bank.md`** — every fit claim traces here. Obey **DO-NOT-CLAIM**.
4. **`docs/knowledge-base/personal/roles/`** — has this company been evaluated before? Filenames are
   `<date>_<company>_<slug>.md`.

Then check what the machine already knows, so you neither repeat it nor contradict it:

```bash
grep -ril "<company>" data/corpus/state-*.json | tail -2     # the triage record: score, red flags
ls data/research/<company-slug>.json                          # an existing company brief
grep -i "<company>" profile/skiplist.md                       # already applied or rejected?
```

**Read the triage record's `analysis` block, not a summary of it.** A run that hit a provider error
writes a `SKIP` stub with `fit_score: 0` and `analysis_error` in `why` — indistinguishable from a
judgment unless you look. If two runs disagree, the later one wins.

## 2. Get the posting itself

Read it to the **end** — comp, location, eligibility and the seniority bar are usually last.

If the source is an aggregator link, find the employer's own posting. **Employers commonly open the same
role at several grades and in several flavours** (senior/non-senior, frontend/backend/full-stack), and
the JDs are often identical apart from the years bar and the salary band. **Always check the ladder** —
the lower rung may remove the only thing that would screen the seeker out.

```bash
curl -s "https://api.ashbyhq.com/posting-api/job-board/<slug>"   # whole board + compensation
.venv/bin/python -m research --tool list_jobs "<company>"        # or via the engine
```

## 3. Research the company

Run `/research-company` (engine: `python -m research "<company>"`), then **close its open questions with
your own web search** and write them back with `--answer`.

**Verify you have the right company.** A board lookup resolves a name to an ATS slug and will happily
land on a different company with the same name — check the employer's own careers URL, and treat
review-site data as belonging to whichever company the site actually indexed.

## 4. The reply — one message, these sections

1. **What this is** — company, channel, and whether it is the employer or an agency. Verified or
   inferred, with confidence.
2. **What the job actually is** — the day-to-day, in plain terms. Correct the obvious misreading if
   there is one: which layer of the product, which team, what it is *not*.
3. **Who the customer is**, when the role is customer-facing. It changes the job more than the stack does.
4. **Fit** — each requirement, pass or miss, against the bank. Strong signals, honest gaps. Name what is
   underused as well as what is missing.
5. **The interview loop** — find it; many employers publish one. Sizing it is part of the decision.
6. **Against the rubric** — priority by priority, in the rubric's own order. Say which are for and which
   against. Held-back roles are shown with the reason, never hidden.
7. **The recommendation** — answer the question that was asked. Surveying options without a pick is the
   failure mode.
8. **Open questions** — what could not be verified, and what to ask on the first call.

**Label every inference at the point of use.** A guess stated as a fact is worse than no guess, and a
hedge in paragraph one must not become a fact in paragraph five.

## 5. Record it

Write `docs/knowledge-base/personal/roles/<date>_<company>_<role-slug>.md`. Filenames match
`applications/`' `<date>_<company>_<slug>` so one grep finds a role in both places.

Carry the decision, the reasoning, the corrections, and the open questions — **not the whole reply.**
The test of a good record: someone re-pitched this role in two months can read it and not redo the work.

Update it in place as a thread continues; do not open a second file for the same role.

When the decision is final, add the id to `profile/skiplist.md` with a one-line reason — that is the
machine index, and it is what stops the role resurfacing.

## 6. Propose preference updates — never write them

If the session produced a **durable** preference — a screening format that is a dealbreaker, a settled
question, a gap that should always be handled the same way — propose it as one line plus where it came
from, and let the seeker accept it.

**Never edit `preferences.md` unprompted.** Same precedence rule as the CV judge that grades but cannot
rewrite: a system that edits its own record of what someone wants is how a preference they never held
becomes permanent.

**And never move a rubric value into it.** `preferences.md` holds nothing `profile/rubric.md` can hold —
no rates, floors, tiers or scores. A real change to the priority function is a rubric edit.

## Notes

- **Not triage.** This consumes triage's output; it does not re-run, re-score or edit it.
- **Not a CV.** When the decision is to apply, hand off to `/tailor-cv` (one) or `/tailor-cv-batch`
  (several) and `/cover-letter`.
- Everything under `docs/knowledge-base/personal/` is pruned from the public snapshot, so company names,
  comp and personal circumstances belong there and nowhere one level up.
