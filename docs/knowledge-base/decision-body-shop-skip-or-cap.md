# Decision — Body-shop postings: hard skip, or a scored cap?

**Date:** 2026-07-22
**Status:** Accepted, with a scheduled revisit
**Deciders:** Ben, with the reasoning worked through in review of stage 4 · 09

## Context

Stage 4 · 09 promoted body-shop detection from "deprioritize but still log" to a **hard skip** in
`triage/prefilter.py:hard_skip`, keyed on how a posting is *written* — `_SHOP_STRONG` (any one is
enough) and `_SHOP_WEAK` (two required) — and mirrored as a `BODY SHOP (verdict = SKIP)` block under
HARD FILTERS in `profile/rubric.md`.

The rule was deliberately never keyed on "is this a staffing firm", because agencies are the PRIMARY
tier of this search and an agency req is the fastest fill. Measured over 1,134 deduped corpus jobs it
cut **7 postings (0.62%)** and **0 of the 41 postings from the 28 named agencies** — so it does not
hit the channel it was most at risk of hitting.

In review, Ben objected to the mechanism rather than to the measurement:

> "I don't think you should cut jobs, you should focus on measuring fit."

The objection is sound, and it sharpens into a distinction the rubric already half-encodes:

**Hard-skip when the criterion is factual and checkable; cap when it is inferred.**

Every other HARD FILTER is factual — non-US, a posted rate below the floor, a required clearance, a
wrong primary stack. You can read the JD and be right. "Is this a body shop?" is a *judgment*
assembled from regex tells that are pinned to 2026-07 vendor boilerplate and will drift silently. The
rubric already handles inferred disqualifiers differently: `MANDATORY-TECH GAP` and
`NON-ENGINEERING ROLE SHAPE` **cap at LOW_FIT** — still scored, still visible, ranked out of the apply
set — rather than skipping.

By that rule, body-shop detection belongs with the caps, not with the hard filters.

## Options considered

**(a) Status quo — hard skip in the prefilter.** Cut before the expensive call. Cut postings still
appear in the worklist's "Rejected / skipped" section with the specific tell named, so they are not
invisible. Saves ~7 model calls per month.

**(b) Demote to a scored cap.** Delete the `hard_skip` arm, `_body_shop_tells` and its two pattern
dicts; change the rubric block from `verdict = SKIP` to `CAP AT LOW_FIT, name the tell in red_flags`;
mirror into `config/example/rubric.md`. Every posting gets a real fit score. Costs ~7 model calls per
month and deletes 6 passing tests in `triage/test_prefilter.py` (the 5 keep-case tests stay valid).

**(c) Split the difference.** Hard-cut only the single unambiguous tell — concatenated EAD categories
(`OPT-EAD`, `GC-EAD`, `H4EAD`), which no direct employer writes — and cap on everything else.

## Decision

**Take (a) for now — status quo — and revisit against real output.** (b) remains the preferred end
state on the principle above.

The reason is sequencing, not disagreement. The branch is being validated by a live triage run whose
purpose is to confirm the **channels** work. (b) changes what the model is told about a whole class of
posting and deletes tested behaviour. Landing it in the same run puts three variables in one
observation, and if the output looks odd there is no way to attribute it.

The deferral is also cheap in a way that a deferral usually is not: because cut postings are printed
under "Rejected / skipped" with the tell named, **the run itself produces the evidence for the
decision**. The seven cuts can be judged in context rather than from a summary.

The specific posting to judge is **Enterprise Mobility Inc**, cut on `any-visa`. The name reads like a
direct employer (the rental-car group); the posting says "Visa: Any workable visa", which no direct US
employer writes. Whichever way that one reads on the real run decides between (a), (b) and (c).

## Consequences

- Up to a handful of postings per month are never scored. They remain visible with a reason.
- The regexes stay a maintenance surface pinned to a point-in-time vendor vocabulary, and drift is
  detectable only by reading the "Rejected / skipped" section. This is the cost being accepted.
- The rubric currently states a rule (`BODY SHOP → SKIP`) whose tier is under review. If (b) is later
  adopted, the change touches `triage/prefilter.py`, `triage/test_prefilter.py`, `profile/rubric.md`
  and `config/example/rubric.md` — four files, and the rubric edits are prose.
- **Revisit trigger:** the first triage run after 2026-07-22, reading the "Rejected / skipped" section.

## References

- `.scratch/PIPELINE-LOG.md` — "Stage 4 · 09 — `body_shop` becomes a hard skip", for the measurement
  and the seven named cuts.
- `.scratch/oss-rag-4-channels-config/issues/09-body-shop-skip.md` — the originating ticket.
- `triage/prefilter.py` — `_SHOP_STRONG`, `_SHOP_WEAK`, `_body_shop_tells`.
- `profile/rubric.md` — the `BODY SHOP` block, and the `CAP AT LOW_FIT` rules it is being compared to.
