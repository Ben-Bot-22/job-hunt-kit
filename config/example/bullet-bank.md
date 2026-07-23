# CV Bullet Bank — Robin Doe (fictional example)

**Robin Doe does not exist.** Every claim below is invented to show the shape of the file; see
`config/example/README.md`. Replace the whole thing with bullets mined from your own résumé — that is
what the `/setup` skill does, and it asks you about anything it cannot back rather than inventing it.

**Purpose.** The evidence-backed source of truth for `/tailor-cv`. Every bullet here was mined from real
work and marked with a confidence. Tailoring PULLS from this bank; when a JD forces a genuinely new
bullet, we ADD it back here (with evidence) so we never rewrite it twice.

**Hard rules for anything drawn from this bank**
- Truthful only. Never claim tech, metrics, or ownership not backed by an entry below.
- Respect the **DO-NOT-CLAIM** list at the bottom.
- Confidence: `high` = you can walk an interviewer through the code · `med` = inferred from structure or
  docs · `low` = thin. Prefer high.
- Numbers in `[brackets]` are asserted rather than measured — keep only what you stand behind, and never
  invent a new one.

Last refreshed: 2026-01-15 (sources: the résumé Robin handed `/setup`, plus two follow-up questions).

---

## Identity / summary raw material

- Full-stack developer, TypeScript-primary, building React front ends and the Node and Python APIs
  behind them. No years number on the CV.
- Owns a customer-facing dashboard end to end: the component library, the data-fetching layer, the
  endpoints that feed it, and the PostgreSQL queries underneath.
- Writes SQL by hand — window functions, query plans, index choices — rather than reaching for an ORM
  escape hatch.
- Maintains a small open-source React component library with real outside users, so there is public code
  to read.

---

## Project A — the customer dashboard (owner)

- **[high]** Rebuilt a jQuery reporting screen as a React and TypeScript application, moving data
  fetching onto React Query so a stale cache stopped being the most common bug report. *ev:* the PR
  series, the before/after bug counts.
- **[high]** Built the shared component library it sits on — form controls, tables, an accessible modal —
  and got [three] other teams onto it, so a design change stopped meaning four separate edits.
  *ev:* the package, its consumers.
- **[high]** Cut the initial bundle from [~1.1 MB] to [~340 KB] with route-level code splitting and by
  removing a moment.js dependency, taking time-to-interactive on a mid-range laptop under [2s].
  *ev:* the bundle analyser output in CI.
- **[med]** Added Playwright coverage for the three flows that generated the most support tickets, run on
  every PR. *ev:* the spec files, the CI config.

## Project B — the API behind it (contributor)

- **[high]** Built read endpoints in FastAPI over the reporting tables, with pagination and per-tenant
  filtering enforced in one dependency rather than in every handler.
- **[high]** Took the p95 on the heaviest endpoint from [~2.4s] to [~300ms] with a covering index and a
  materialised rollup, and wrote the test that fails if the rollup drifts from the source of truth.
- **[med]** Added a small Node/Express service for webhook ingestion, and moved the whole thing from EC2
  to ECS Fargate behind the existing load balancer with no downtime.

## Project C — `rivet-ui` (open source, sole maintainer)

- **[high]** A small React component library built on Radix primitives: typed props, no runtime CSS-in-JS,
  and every component keyboard-navigable and screen-reader-labelled by construction rather than by audit.
- **[med]** [~40] GitHub stars and a handful of outside contributors; every PR runs the suite plus an
  axe-core accessibility check in GitHub Actions.

---

## DO-NOT-CLAIM

- **Kubernetes ownership.** Robin has deployed into a cluster someone else ran. Do not let a JD's
  "Kubernetes" keyword turn that into operating one.
- **Team leadership.** No direct reports, no formal tech-lead title. "Mentored one intern" is the true
  version and is worth saying plainly.
- **Native mobile.** No shipped Swift or Kotlin. React Native was a two-week spike that did not ship.
- **Go, Kafka, Spark.** Read about, never shipped.
- **Design ownership.** Robin implements designs and maintains the system; there is no Figma authorship
  to claim.
- **A years-of-experience number.** Not on the CV. Let the roles carry the dates.
