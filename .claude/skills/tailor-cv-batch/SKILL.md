---
name: tailor-cv-batch
description: Tailor several CVs at once — one agent per job, run in parallel, each following /tailor-cv end to end, with a single table of results back. Use when a triage run produced more than one pick worth applying to, or whenever more than one résumé is asked for.
---

Build **many** tailored CVs concurrently. Every CV is still `/tailor-cv`, unchanged — this skill is the
fan-out around it plus the parts that were being re-derived by hand every run.

**When to use this instead of `/tailor-cv`:** whenever the answer is more than one CV. `/tailor-cv` is
the right tool for exactly one job; past that it costs one serial round-trip per job for no reason,
because parsing, drafting, rendering and grading are per-job and independent. The only shared input,
`profile/bullet-bank.md`, is a read.

## 1. Build the work list — do not assemble it by hand

```bash
.venv/bin/python -m cv.batch worklist "<path to the dated apply doc>" --min-fit 70
```

Returns JSON: company, role, folder, link, `has_jd`, `existing`. Three things it filters, and each is
a job that must never be rebuilt:

- **ticked boxes** — applications already sent;
- **struck-through entries** (`~~...~~`) — duplicates the run resurfaced, which usually means Ben is
  already in that process under another company name;
- **every section that is not the apply set** — the apply doc's audit blocks are full of `- [ ]` lines
  too, and `📬 Reply, don't cold-apply` is the expensive one to get wrong: those are live conversations.

`--min-fit N` is the gate `/job-triage` uses, and it is **70** (2026-08-04). It filters on the score
the apply doc printed rather than on position: a positional cap (`--top N`, still available) drops the
job at N+1 for being eleventh, where a score gate drops only the ones that were not worth the tokens.
Ben: *"for good fits (>70) you should probably build anyway."* An entry whose line printed no score is
**kept** — absence of a number is not evidence of a low one, which is what carryovers look like.

Either way it is a **gate, not a quota**: a run where four roles clear 70 returns four.

**If the command raises, it found a `##` heading it cannot classify.** Fix the heading in the apply doc
to one of `/job-triage` Step 6's — do not work around it and do not hand-assemble the list instead,
which is how the research, résumé and letter stages start disagreeing about which jobs are in the set.

If there is no apply doc at all, take the list from the user and build the same structure by hand.

Then decide the set, and **say which jobs you dropped and why**. Two rules:
- **`has_jd: false` means there is no posting to write against.** Fetch it first (WebFetch; LinkedIn
  is usually login-walled — ask Ben to paste it) or drop the job. Never write a CV from a run
  summary: on 2026-07-28 the run summaries were wrong three times in one day.
- **`existing: true` is a rebuild, not a skip**, if `profile/bullet-bank.md` has changed since the
  folder was written. `git log -1 --format=%cd profile/bullet-bank.md` against the folder mtime
  answers it.

## 2. Fan out — one agent per job, all launched in a single message

Spawn one general-purpose agent per job, **all in one message so they run concurrently**. Each gets a
prompt that says: work in the repo root in place (no worktree), follow
`.claude/skills/tailor-cv/SKILL.md` exactly and in full, read `profile/bullet-bank.md`,
`docs/knowledge-base/personal/tailoring-playbook.md` and `profile/rubric.md` before drafting, and do not commit.

Four things every agent prompt must carry, because each was a real failure:

1. **The folder and the job link**, and whether it is a rebuild.
2. **Read-only on the bullet bank.** N agents appending to `profile/bullet-bank.md` concurrently is
   how a corrupted bank reaches every application in the run. A genuinely new bullet is *proposed* in
   the agent's return value with its evidence; you apply the accepted ones yourself, serially, in §4.
   Same shape as the grader that reports fixes and never applies them — the machine proposes, the
   step with a human in it disposes.
3. **The refusal list, spelled out.** Reviewer fixes that add SQL, OpenAI, Cursor, Copilot, CI/CD,
   Kubernetes, a years-of-experience number or an invented metric are **refused and reported**. The
   bank and Ben's stated preferences outrank the grader, always.
4. **Build first, report after.** Ben's standing instruction: render, then show what changed for
   post-hoc edit. Do not stop at `/tailor-cv` §4's approval gate.

And what to return: folder, page count, depth, headline changes, the reviewer's four scores and pass
count, refused fixes, what the gloss pass cut, proposed bank additions, and the honest keyword gaps.

## 3. The mechanical steps are code — agents call them, they do not re-derive them

```bash
.venv/bin/python -m cv.batch fit     <folder>   # render, tighten, re-render until one page
.venv/bin/python -m cv.batch degloss <folder>   # the gloss substitutions with no honest rewrite
```

`fit` only ever touches the plan's `tighten` block. **It will not drop a bullet to win a page** —
that is a claim decision, and it belongs to whoever can weigh what is lost. When it exits 3 the
document genuinely does not fit and the agent picks the trim.

`degloss` is deliberately a short list of phrases that carry a stance and no fact. The *judgement*
half of `/tailor-cv` §5b — does this sentence add a fact or a stance? — stays with the agent. A style
ban enforced by a word list is dodgeable by substitution, and this repo already reversed one such
test: `int8-quantized, TorchScript-compiled` duly became the vaguer `size-optimized`.

## 4. Collate, then apply bank changes serially

One table: role · pages · the four scores · passes · refused fixes · keyword gaps. Then **show Ben the
proposed bank additions with their evidence and wait** — `profile/bullet-bank.md` is protected and no
agent writes to it without his explicit yes, orchestrator included. Apply the approved ones one at a
time. (Serial application is the *concurrency* fix; his approval is a separate gate and neither
substitutes for the other. See the notice at the top of the bank.)

**Report a stopped-early CV as partial fit, not as a failure.** When the only sub-bar dimension is
`keyword_coverage` and its misses are terms with no evidence behind them, more passes cannot help —
say how many must-haves are unclaimable. On the Apex req that was 11 of 23, which is a fact about the
requisition rather than a defect in the document.

## Rules

- **Never** let a batch agent write to `profile/bullet-bank.md`, `profile/rubric.md`, or another
  job's folder.
- Every claim still traces to the bank. Parallelism changes the schedule, never the standard.
- Do not commit from inside an agent — one commit at the end, by you, so the run is one change.
