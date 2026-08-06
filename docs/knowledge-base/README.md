# Knowledge base

**Everything we learned, and every reason we did something. One flat folder, no subfolders.**

If you are about to write down *why* — why a thing works this way, what a measurement showed, what was
tried and rejected, what broke and what it cost — it goes here. There is nowhere else it may go.

## The four kinds of file

The filename prefix says what it is. There are only four:

| file | what it is |
|---|---|
| `log.md` | **The running record.** One dated section per working session: what changed, what it cost to learn, the measurements, the wrong turns. Newest at the top. This is the default — most changes need only a log entry. |
| `decision-<slug>.md` | **One decision that could have gone another way.** Context, the options considered, what was chosen and why, and a **revisit trigger** — the thing that would reopen it. |
| `research-<slug>.md` | **One investigation.** A question, what was measured or read, and what it concluded. Written once, then cited rather than repeated. |
| `plan-<slug>.md` | **A build plan, kept for its reasoning.** Historical: how something was designed before it existed. Not a manual — see below. |

Descriptive names, no numbering, no acronyms. `decision-body-shop-skip-or-cap.md` tells you what it is
without looking inside; `ADR-0001` does not.

## What does NOT go here

**This folder has exactly one job, and the fastest way to ruin it is to file a how-to in it.**

- **Reference manuals → `docs/operating/`.** How the tool works *now*: the operator's guide, tuning
  knobs, services, the data map, scheduling. The seam is: **operating = how it works now;
  knowledge-base = why it's that way and what we learned.** If someone would read it to *use* the tool,
  it is an operating doc.
- **Agent conventions → `docs/agents/`.** Test policy, issue-tracker format, triage labels.
- **Tickets and specs → `.scratch/<slug>/`.** Work in flight. **Reasoning never goes in `.scratch/`** —
  a ticket is written *before* the work, never corrected *after* it, and nobody opens one a month later.
  When the work ships, the reasoning comes here and the ticket can go.
- **Personal decision-support material → [`personal/`](personal/), right here.** Job-search strategy,
  market reasoning, call prep, notes on particular companies. It is documentation, so it lives with
  the documentation; it is personal, so it is fenced. **`personal/` is the one subfolder this flat
  folder allows, and it is the privacy seam rather than a topic** — everything under it is pruned from
  the public snapshot by `scripts/extract.py` (`PERSONAL_SUBTREES` → `is_personal()`), and
  `scripts/test_leaks.py` imports that same definition so the two cannot disagree. Anything one level
  up from `personal/` **is published**. Read [`personal/README.md`](personal/README.md) before adding.

  `profile/` keeps only what the tool *loads* — `rubric.md`, `profile.yaml`, `bullet-bank.md`,
  `skiplist.md`, `cv-base.docx`, `letters/`. Those are configuration; prose about the search is not.

## Two things to know

**Read before writing.** These compound: the work-life-balance decision is built directly on the
body-shop decision's principle — *hard-skip when the criterion is factual and checkable, cap when it
is inferred*. Re-deriving that from scratch would have produced a worse answer more slowly. Check for
an existing note touching your area before designing a new one.

**Pre-2026-07-30 build history lives in `.scratch/PIPELINE-LOG.md`.** It is the stage-by-stage record
of how this repo was built. It stays in `.scratch/` deliberately: it contains absolute `/Users/…` paths,
so moving it under `docs/` would both publish it and fail `scripts/test_leaks.py`. `log.md` is the
going-forward record; that file is closed history.

## Why this folder exists

Before 2026-07-30 the answer to *"where does the reasoning go?"* was three places — a change log buried
among fourteen manuals in `docs/operating/`, decision records in `docs/adr/`, and in practice whatever
`.scratch/` ticket was open. An agent reprioritizing the entire ranking function put the reasoning in a
ticket, and had to be asked twice where the durable record was.

**A convention that exists only in the directory listing is a convention nobody follows.** So it is
stated in `AGENTS.md`, which loads every session, and the detail is here.
