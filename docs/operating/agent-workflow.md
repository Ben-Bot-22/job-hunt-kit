# Agent workflow (Matt Pocock skills) — how to use it

Installed 2026-07-21 from [`mattpocock/skills`](https://github.com/mattpocock/skills). Skills live in
`.claude/skills/`, repo config in `docs/agents/`, and the summary block an agent reads is in
`AGENTS.md` (`CLAUDE.md` is a stub importing it). These twenty are **vendored** — `skills-lock.json`
names every one, which is exactly how the extraction allowlist tells them from this repo's own five
workflows and ships only ours.

**If you remember one thing: type `/ask-matt`.** It's a router — describe your situation in plain
English and it tells you which skill to reach for and why. Everything below is what it knows.

---

## The main flow: idea → shipped

This is the route most work travels. Four commands.

```
/grill-with-docs  →  /to-spec  →  /to-tickets  →  /implement  →  (code review, commit)
   sharpen it        write it     split it        build it
```

**1. `/grill-with-docs`** — you describe a rough idea; the agent interviews you relentlessly until the
design is actually sharp. It's stateful: what it learns about the domain gets written to `CONTEXT.md`
and `docs/adr/` so the next session doesn't re-ask. Use this one when you're working in this repo.

**2. `/to-spec`** — collapses that conversation into `.scratch/<feature-slug>/spec.md`. You stay in the
same session; the spec is just the conversation made durable.

**3. `/to-tickets`** — splits the spec into *tracer-bullet* tickets: each one a thin end-to-end slice
that works, not a horizontal layer that doesn't. Writes one file per ticket to
`.scratch/<feature-slug>/issues/NN-slug.md`, each declaring what blocks it via a `Blocked by:` line.

**4. `/implement`** — builds one ticket. Internally it drives `/tdd` (red → green → refactor, one slice
at a time) and finishes by running `/code-review` on the diff before committing.

### The one rule that matters: context hygiene

**Keep steps 1–3 in a single unbroken context window.** Don't `/compact`, don't `/clear` until after
`/to-tickets` — the grilling, the spec, and the tickets all need to build on the same thinking.

**Then clear context between each `/implement`.** Each ticket starts fresh and works from its file.

The reason is the *smart zone* — roughly the first ~120k tokens, where the model still reasons sharply.
If a session is heading past it before `/to-tickets`, don't push on degraded: `/handoff` and continue in
a fresh thread.

### Two branches inside the flow

- **Can't settle a question by talking?** If the answer needs running code (does this state model feel
  right? what should this UI look like?), detour: `/handoff` out → new session → `/prototype` to answer
  it with throwaway code → `/handoff` back. Keep the answer, delete the code.
- **Is it a one-session job?** Then skip `/to-spec` and `/to-tickets` entirely — go straight from the
  grilling to `/implement` in the same window.

---

## On-ramps — when work arrives instead of starting from an idea

| Situation | Reach for | Notes |
|---|---|---|
| Raw bugs/requests piling up | `/triage` | Moves issues through triage states until they're agent-ready, then `/implement` picks them up. **Only for issues you didn't create** — tickets from `/to-tickets` are already agent-ready; don't triage them. |
| Something's broken | `/diagnosing-bugs` | For the hard ones: intermittent flakes, regressions, bugs that resist a first look. It refuses to theorise until it has one command that goes red on *this* bug, then fixes with a regression test. |
| A huge, foggy effort | `/wayfinder` | For work too big to hold in one session and where the *route* isn't visible yet. Produces **decisions, not deliverables** — a shared map of decision tickets resolved one at a time. When the fog clears it hands off to `/to-spec`. Slow and dense — never use it on a well-scoped feature. |

---

## Everything else

**Standalone**

- `/grill-me` — same interview as `/grill-with-docs` but stateless, for plans that don't live in a repo.
  (Career strategy, a music project, a decision. Nothing gets written to the codebase.)
- `/prototype` — throwaway code to answer one design question.
- `/research` — delegates reading legwork to a **background agent**: investigates against primary
  sources, leaves a cited markdown file in the repo. You keep working while it reads. Its output feeds
  *into* `/grill-with-docs` — research sharpens the thinking, it doesn't replace it.
- `/tdd` — build one concrete behaviour test-first, without a whole spec.
- `/code-review` — two-axis review of a diff against a fixed point: **Standards** (does it follow this
  repo's conventions?) and **Spec** (does it do what the ticket asked?), run as parallel subagents.

**Codebase health**

- `/improve-codebase-architecture` — a survey, run in spare moments. Finds "deepening opportunities" and
  renders them as an HTML report. Picking one *generates an idea* you take into `/grill-with-docs`.

**Vocabulary layers** (model-invoked — these fire on their own, but you can call them directly when the
*words* are the problem rather than the process)

- `/domain-modeling` — sharpen domain language; resolve an overloaded term; record a hard-to-reverse
  decision as an ADR. This is what keeps `CONTEXT.md` a clean glossary.
- `/codebase-design` — the deep-module vocabulary (module, interface, depth, seam, adapter, leverage,
  locality) for designing a module's *shape*: lots of behaviour behind a small interface.

**Crossing sessions**

- `/handoff` — compacts the conversation into a markdown file. You then open a **new** session and point
  it at that file. Use when you want a fresh window but need the current thinking preserved.
- `/compact` (built-in) — stays in the *same* conversation, summarising earlier turns. Use at
  intentional breaks between phases. **Don't compact mid-phase** — the agent loses its way.
- Short version: **`/handoff` forks, `/compact` continues.**

---

## This repo's local setup

**Naming:** your job-triage pipeline was renamed to **`/job-triage`** so it doesn't collide with the
engineering `/triage` skill above. Same tool, same nine steps — just a more specific name.
See `docs/operating/triage-operating.md`.

**Issue tracker: local markdown.** No GitHub Issues round-trips. Everything lives in `.scratch/`:

```
.scratch/<feature-slug>/
├── spec.md                    ← /to-spec writes this
└── issues/
    ├── 01-first-slice.md      ← /to-tickets writes these
    └── 02-second-slice.md
```

Each issue file carries a `Status:` line (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`) and a `Blocked by: NN, NN` line. Comments append under a `## Comments`
heading. Full conventions: `docs/agents/issue-tracker.md`.

`.scratch/` is **not** gitignored — specs and tickets get committed alongside the code they describe.

**Domain docs:** single-context. `CONTEXT.md` at the root and `docs/adr/` don't exist yet and that's
fine — `/domain-modeling` creates them lazily, the first time a term or decision actually needs pinning
down. Don't create them upfront.

**Not installed** (available via `npx skills add mattpocock/skills -s <name>` if you ever want them):
`teach`, `writing-great-skills`, `qa`, `design-an-interface`, `request-refactor-plan`,
`ubiquitous-language`, `to-questionnaire`, `wizard`, plus a batch of TypeScript- and writing-specific
skills that don't fit a Python repo.

---

## Cheat sheet

| I want to… | Command |
|---|---|
| …figure out which command I want | `/ask-matt` |
| …build a feature in this repo | `/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement` |
| …build something small, right now | `/grill-with-docs` → `/implement` |
| …think through a plan with no codebase | `/grill-me` |
| …fix something broken | `/diagnosing-bugs` |
| …deal with a pile of incoming issues | `/triage` |
| …start something big and foggy | `/wayfinder` |
| …answer a design question with code | `/prototype` |
| …have facts gathered while I work | `/research` |
| …review a branch before merging | `/code-review` |
| …carry this conversation into a fresh session | `/handoff` |
| …run my job hunt | `/job-triage` |

**Updating the skills:** `npx skills@latest update --project -y`
