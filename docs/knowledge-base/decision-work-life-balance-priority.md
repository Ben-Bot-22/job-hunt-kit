# Decision — Work-life balance as priority #2: held back, not skipped

**Date:** 2026-07-30
**Status:** Accepted
**Deciders:** Ben, with the priority order stated directly and three agent proposals reversed
**Extends:** [the body-shop decision](decision-body-shop-skip-or-cap.md) — same principle, third tier added

## Context

Asked whether to spend study time on a BJAK coding assessment, the tool's own history was checked and
found to have already flagged the company (`docs/knowledge-base/personal/market/market-insights.md`, 2026-07-28). But three
CVs had been built for it on 2026-07-24 regardless. Pulling the thread exposed a structural problem
rather than a one-off miss.

Ben stated his priority order:

> 1. **Channel** — contract is highly desired (compressed start time, less interview BS)
> 2. **Work-life balance** — "I cannot work an always-on job — my priorities are Neon Buffalo and Reazy"
> 3. **Fit** — only apply to jobs he has a chance at
> 4. **Remote** — desired, but doesn't matter much; less competition for onsite offsets it
> 5. **Rate** — matters least

`triage/rank.py:34-42` sorted `tier → verdict → fit → intensity → completeness`. **Work-life balance
was 4th and structurally dead**: intensity only broke a tie between two jobs sharing tier, verdict
*and* a 0-100 fit score, which essentially never happens. `profile/rubric.md` called low intensity
"non-negotiable" while the code made it the weakest constraint in the file. In `triage/analyze.py:59`,
intensity 4-5 cost exactly one verdict bucket — **the same price as "rate not posted."**

Rate had the opposite problem: `UNDISCLOSED RATE → cap at FIT` demoted jobs below the apply set for a
missing field.

## The measurements

Over 1,399 analyzed jobs, `data/corpus/state-2026-07-2*.json`:

| finding | number |
|---|---|
| a real posted dollar figure | **18%** |
| explicitly "undisclosed" | 9% |
| rate completely blank | **73%** |
| scored **intensity 3** | **78%** (1,092) |
| scored intensity 1-2 | 3% (44) |
| scored intensity 4-5 | 19% (263) |
| intensity 4-5 **still in the funnel** (not SKIP) | **222** |

Two things follow. The undisclosed-rate cap was **measuring our scraping, not the market** — it
demoted four jobs in five for a field we fail to collect. And the scorer **parks on intensity 3**,
which means promoting intensity in the sort ranks almost nothing on its own.

## Options considered

**(a) Hard-skip intensity 4-5.** Strongest protection, and it is what "I cannot work an always-on job"
sounds like it asks for. Rejected on the body-shop decision's principle *and* by Ben directly:

> "I don't want you to skip — I want to see it, but it doesn't go in the prioritized rankings, it gets
> a rejected-because section. I want to see all the rejected because of X ones."

**(b) Cap at LOW_FIT**, matching mandatory-tech-gap and role-shape. Better, but it conflates "this is
a poor fit" with "this is a good fit Ben has chosen not to prioritize" — and it leaves those roles
buried in a 700-line flat rejection list rather than readable as a group.

**(c) Held back — a third tier.** Out of the ranked list, into a dedicated visible section, reason
attached, nothing deleted. **Chosen.** (Amended 2026-07-30 — it is a third *tier of refusal*, not a
third *section*. See the amendment under Consequences.)

**(d) Also downrank "enterprise-shaped" roles** as low interview-win probability, on the theory that
Ben's lack of enterprise/team coding experience makes them hard to win. **Proposed by the agent and
reversed by Ben** — see below.

## Decision

**(c), plus a reordering, plus a demotion of rate.** New sort order:

```
1. channel tier   2. verdict   3. intensity   4. fit score   5. JD completeness
```

And: contract regains real weight over an equivalent perm role (retiring the 2026-07-27 merit-only
rule at Ben's request); the undisclosed-rate cap is deleted; the `< $40/hr` floor survives.

> **AMENDED 2026-07-30, after review — intensity is #3, not #2.** This decision originally shipped
> `tier → intensity → verdict → fit`, on the reasoning that work-life balance is priority #2 and the
> sort key should say so positionally. That was wrong about where the hard gates live. **The gates are
> in the VERDICT, not in the score**: a coordinator title or a mandatory-tech gap is capped at LOW_FIT
> however high the keyword match ran (`profile/rubric.md`, NON-ENGINEERING ROLE SHAPE / MANDATORY-TECH
> GAP). Capped roles are also *undemanding*, so they score LOW intensity — which means putting
> intensity above the verdict inverts every cap into a promotion. Measured on the real
> `data/corpus/state-2026-07-29-144502.json` run, the shipped-as-designed key floated a LOW_FIT role
> at fit 32 / intensity 2 ABOVE two STRONG_FIT roles at fit 85 in the same tier. Ben's call: **quality
> grade first, then hours, then score.** Intensity still sits above the fit SCORE, which is the change
> that mattered — it was fifth, below the score, and therefore dead. Pinned by
> `triage/test_rank.py::test_a_capped_low_fit_role_never_floats_on_being_undemanding`.
>
> The priority *order* in the rubric is unchanged and still correct. A priority list is not a sort key:
> "work-life balance outranks fit" means it outranks the fit **number**, not the fit **judgment**.

### Why held back rather than skipped — this is the body-shop decision's principle, extended

The body-shop decision established: **"Hard-skip when the criterion is factual and checkable; cap when it is
inferred."** Intensity is the most inferred signal in the analysis — a model's read of prose, with no
ground truth in the posting. By 0001's own rule it cannot be a hard filter, and that conclusion held
independently of Ben's preference, which is the useful part: two lines of reasoning met at the same
answer.

What 0001 did not have was a tier for *"correctly scored, genuinely interesting, and deprioritized
anyway."* That is what held-back adds. The distinction it encodes:

| tier | criterion is | example |
|---|---|---|
| SKIP | factual, checkable | non-US, rate under floor, clearance |
| CAP AT LOW_FIT | inferred, and the role is a poor fit | role shape, mandatory-tech gap |
| **HELD BACK** | inferred, and the role is a **good fit Ben is choosing against** | intensity 4-5 |

### Why no fit-scoring change, and the reversal that produced that

The agent proposed (d), downranking enterprise-shaped roles. Ben reversed it:

> "I want enterprise roles — enterprise is where work life balance is good — scoped tickets — these are
> highly desired — this is the wrong take away... startups are more likely to go for AI agentic
> engineering but at the cost of high intensity — this is a tradeoff and you are a filter and
> prioritization tool. I need to see the reqs to evaluate because the tool is imperfect."

He is right on both counts. Enterprise means scoped tickets and sane hours — that *is* priority #2, so
downranking it would have fought the very change being made in the same edit. And the missing
enterprise credential is what the career-bridge strategy exists to **acquire**, so treating it as a
liability inverts the goal.

The deeper point is that **the startup-vs-enterprise trade resolves itself once WLB is #2**: enterprise
scores low intensity and rises; startups score 4-5 and land in held-back, where Ben makes the
agentic-AI-vs-hours call himself. A separate fit rule would be a second, blunter mechanism duplicating
what the intensity change already does — and it would have removed exactly the roles he wants to see.

**This is the second time in four days an agent proposed a rule that shrank the funnel in the name of
matching Ben's preferences, and the second time he wanted the opposite.** The standing correction: when
a trade is genuinely his to make, surface it with the reason attached — do not make it for him.

### The tells checklist is load-bearing, not garnish

78% of jobs score intensity 3. Promoting a field to sort key #2 accomplishes nothing while
three-quarters of jobs share one value. The INTENSITY TELLS block added to `profile/rubric.md` is what
makes a 3 a judgment instead of a default; the sort change is what makes that judgment count.
**Ship the rubric before the sort** — the reverse order looks like a no-op and invites a rollback of
the wrong change.

## Consequences

- ~222 currently-in-funnel jobs move out of the ranked list into held-back. Nothing leaves the corpus.
- `Analysis` gains `held_back_reason`, a **fixed vocabulary** — free-text `why` cannot be grouped, and
  this doc is read every weekday morning.
- The apply doc's flat `✕ Rejected / skipped` list becomes grouped by reason.

> **AMENDED 2026-07-30, after review — ONE review section, not two.** This decision originally shipped
> two headings: `⏸ Held back — always-on / high intensity` and `✕ Rejected / skipped (why)`. Ben
> collapsed them:
>
> > *"it doesn't matter if they are rejected for intensity as long as i can look at them and audit… i
> > need to review it personally to know so you need to show me. if it is clearly high intensity (4-5)
> > you need confidence to exclude - it should go in the review section with rejected jobs and the
> > reason."*
>
> The page now renders one `## ✕ Review — held back and rejected (why)`, with a `###` sub-heading per
> `held_back_reason` and a count. The distinction between the three tiers of "no" is **preserved and
> in fact sharpened** — it moved off the section heading, where it was implicit, and onto the group
> heading, where it is named. Two consequences:
>
> - **`_is_held_back` is verdict-blind now.** It used to require `verdict != "SKIP"` so that a SKIP had
>   somewhere else to go; there is no elsewhere, and an intensity-5 role must leave the rankings
>   whatever its verdict says. A SKIP filed under `intensity` is therefore correct, not a bug.
> - **Grouping runs over the whole refused set, not over SKIPs alone.** That is what makes `role-shape`
>   and `years-bar` reachable at all: both are *caps at LOW_FIT* and are never SKIPs, so while grouping
>   ran over the SKIP list the vocabulary named two buckets that could not exist.
>
> The invariants, verified against the real 135-job `data/corpus/state-2026-07-29-144502.json` render
> and not only in tests: every job appears **exactly once** somewhere on the page (135/135, 0 missing,
> 0 duplicated), and **0** intensity-4-5 jobs reach the ranked tiers or Focus.
- **Accepted cost:** this fights the runway goal. `profile/rubric.md` still says money-soon has real
  value and speed to a signed role is the point. Reordering and holding back cost no *recall* — nothing
  is deleted — but they do change what Ben reads first each morning, and a crunch role that would have
  closed fast now sits below a sane one that may not close at all. Chosen knowingly.
- **Revisit trigger:** the first two runs after 2026-07-30. Read the held-back section. If Ben is
  routinely pulling roles *out* of it to apply to, intensity is scoring too hot and the tells need
  tightening. If it is never read, the section is theatre and these roles should cap instead.
- Rate-floor inconsistency found in passing and fixed: `triage/analyze.py:62` said `< $50/hr`,
  `profile/rubric.md` said `< $40/hr`. The rubric is authoritative.

## References

- `docs/knowledge-base/decision-work-life-balance-priority.md` — spec and the three implementation tickets.
- `docs/knowledge-base/decision-body-shop-skip-or-cap.md` — the factual-vs-inferred principle.
- `docs/knowledge-base/log.md`, 2026-07-30 — the session record.
- `docs/knowledge-base/personal/market/market-insights.md`, 2026-07-28 — the BJAK identification this started from.
