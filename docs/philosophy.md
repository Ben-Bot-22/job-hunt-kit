# Goals, and why this refuses things

The README lists the [non-goals](../README.md#what-this-is-not). That list says *what*. This file says
*why*, because a refusal without a reason reads as an omission, and an omission is something people
keep asking you to fix.

## What it optimizes for

**Your attention, not your throughput.** A job hunt is not short of postings — a single weekday's
inbox and board sweep here runs to ~350 of them — it is short of the attention to read them honestly.
So every design choice is scored on whether it reduces the number of things a human has to look at
*without* reducing the number of things a human gets to decide.

That is why the output is a ranked markdown file rather than a queue, why the scorer writes down its
reasoning next to every verdict, and why the thing it recommends most days is small. The ranking rule
in this repo's own rubric is *drain, not comp* — pay is a threshold to clear, energy is the axis. The
tool is built to serve that shape of judgment even when your rubric says something else, because the
rubric is yours and the pipeline around it is not opinionated about the answer, only about showing its
work.

## The refusals

### It does not apply for you

The single most requested feature, and the one that would break the thing that makes the rest work.

Three reasons, in order of how load-bearing they are. **The scorer is calibrated by your
disagreement** — every judgment lands in `data/corpus/`, and from the second run on each job is scored
with its nearest past judgments in front of the model. That loop closes because a human read the
worklist and acted differently from it. Auto-apply removes the reader and the loop opens.
**Applications are the part with consequences**: a bad score costs you a scroll, a bad application
costs you a company, and those two error rates do not deserve the same guard. And **the output is
arguable on purpose** — `Analysis.why`, `red_flags` and `precedent` exist so you can tell a wrong
score from a right one; nobody argues with a form that has already been submitted.

What you get instead: it finds, scores, ranks, and builds a JD-tailored résumé for the picks worth
applying to. The last click is yours.

### No web UI, no hosted service

A hosted version would hold your inbox contents, your résumé, your rubric and a corpus of every job
you have judged and why. That is a materially different product with a materially different threat
model, and it is not one that can be run as a by-product of somebody's own job hunt.

Locally, the properties fall out for free: the only outbound call is to the LLM provider whose key
*you* set, `data/` never leaves the machine, and the retrieval half needs **no key and no network at
all** because the embedder (`bge-small-en-v1.5`, via `fastembed`) runs on your CPU. Point
`llm.provider` at `ollama` and nothing about a job you are considering leaves your laptop.

### No installer, and a terminal is assumed

The ramp is short because the audience is narrow: someone who already has a terminal and, ideally, a
coding agent. Widening it would mean owning packaging, updates and a support surface for people who
cannot read a stack trace — for a tool that is a **one-way snapshot** nobody is maintaining as a
shared codebase. Saying so up front is cheaper for everyone than a broken install.

### Not a recruiter tool, and no candidate sourcing

Everything here is one person's judgments about jobs. Turning it around — scoring *people* against a
req — would need other people's data, and would inherit a discrimination surface that a prose rubric
injected whole into a model is exactly the wrong instrument for. The rubric is safe to be
unstructured and unvalidated precisely because the only person it can be unfair to is the person who
wrote it.

### Not career advice

The tool applies the standard you wrote. It has no view on whether the standard is any good. When it
scores a role 90 it means *this matches what you said you wanted*, and if what you said you wanted is
wrong, a confident number is the failure mode rather than the fix — which is why the reasoning is
printed beside the score and the corpus keeps every past judgment retrievable.

### No evaluation harness, no agreement metric

There was one and it was cut. Judging the judge with an LLM produces a number that moves when the
weather changes, and a golden set of "correct" scores is a second rubric maintained by hand to grade
the first one. What replaced it is ordinary engineering: when a model call moved onto a new path, the
change was measured by re-scoring the same 20 stored JDs before and after and reading the diff
against a **measured noise floor** — the same code scored against itself moved `fit_score` on 10 of
20 rows, so the migration moving 8 of 20 was silence, not signal. Numbers you can defend, produced
once, rather than a dashboard that rots.

### Nothing publishes on a trigger

`scripts/extract.py` seeds the public snapshot and it is never automatic — no publish-on-push, no
schedule. A content scan is the only thing standing between a personal directory and the internet,
and an unpublish does not exist. The same asymmetry runs through the whole repo: **the irreversible
step is always a human's.**

## The rules underneath

Five of them, and they explain most of the code that looks over-careful.

**Fail in the cheap direction, and name which one that is.** Every guard in the repo is tuned by
asking what each mistake costs. The prefilter is biased toward *keep*, because a false kill is a job
you never see and a false keep is a few cents of Sonnet. Semantic dedup demands cosine ≥ 0.95 **and**
80% 5-gram overlap **and** refuses to merge two different titles at the same company, because a wrong
collapse deletes a real job silently. Retrospective clustering runs at 0.82 — far looser — because
nothing is deleted there and a missed merge under-counts a finding. Same machinery, opposite tuning,
because the asymmetries point opposite ways.

**Absent out loud, never silently.** The `gmail` channel is a documented stub that *raises* when
enabled, because an empty list looks exactly like a working channel with a quiet inbox. An agency
scraper returning nothing prints `motion 0 ⚠` in the run summary — those scrapers fail by returning
zero rather than by raising, and that parenthetical is the entire rot detector. The market report
renders its external half as a labelled gap rather than shipping a shorter document a reader would
mistake for a complete one. A missing capability that reads as a working one is the failure this repo
spends the most lines preventing.

**Classify once, per directory, never per file.** The four personal directories are named for their
*content*, so a new file inherits its directory's classification and a normal day's work needs no
review. The cost is paid at the only moment it is cheap: a genuinely new top-level path aborts the
publish and names itself.

**One path for anything that matters.** One module builds a model client (`core/llm.py`), so the
provider is a config value rather than a fork. One requirements file, so a leaf that needs none of it
still installs all of it. A leaf may import `core/`; a leaf never imports a leaf. All three are
enforced by tests rather than by review, because a rule nobody can violate is worth more than a rule
everybody agrees with.

**Configuration cannot break the tool.** `config/settings.yaml` is validated against a generated
schema, so a misspelled key is an error naming the key. `profile/rubric.md` is the exact opposite —
markdown, no schema, no validation, deliberately — because it is a *prompt*, it is the file edited
most, and nothing may be able to stop the tool booting by being wrong about it. This repo's own copy
once had a YAML block scalar folding six section headings onto the bullets beneath them, so the
anchor that was written was not the anchor the model read. Nothing parses `rubric.md` now. You cannot
break it.

## Where the reasoning lives

- Non-goals as a list, for a stranger deciding in 90 seconds — [`README.md`](../README.md#what-this-is-not)
- What an agent may edit, and why the boundary is a file — [`AGENTS.md`](../AGENTS.md)
- The daily run, end to end — [`docs/operating/triage-operating.md`](operating/triage-operating.md)
- Running it unattended, and what cannot be — [`docs/operating/scheduling.md`](operating/scheduling.md)
- The five workflows, and your equivalents of them — [`docs/operating/workflows.md`](operating/workflows.md)
- Findings that decided a design — [`docs/research/`](research/)
