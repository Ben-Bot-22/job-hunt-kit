IDEAL ROLE (the 10/10 Robin is optimizing for):
- REMOTE within the US, worked from Chicago — NO relocation, and no hybrid that means an office three
  days a week under another name.
- PERMANENT, salaried, W2 is the preference — Robin wants a team and a title. But a W2 CONTRACT at
  $60/hr or better is a real option and CAN score FIT or STRONG_FIT: rank it below an equivalent
  permanent role, do NOT gate it out.
- $115k HARD FLOOR on base salary, or $60/hr on a contract (a posted band whose top clearly sits
  below that = SKIP).
- MODERATE INTENSITY (1-3 on a 1-5 scale): a normal week, a real on-call rotation or none at all.
  Protected time: evenings, a Tuesday climbing session, and an open-source React component library
  Robin maintains.
  **Intensity SORTS, it does not EXCLUDE.** An on-call rotation, incident response, sprints and
  deadlines are ordinary conditions of employment — a 4 or 5 ranks the role below an equal-fit
  sane-hours one and puts the quoted phrase on its line, and that is all it does. Write down which
  demands actually cross YOUR line; everything else is a job being a job.
  **TRAVEL THRESHOLD: 10%.** More than that, stated in the posting, sets `held_back_reason: "travel"`
  and the role leaves the ranked list into the review section — still linked, still readable, still
  something Robin can pull back in. *(This number is the one the analyzer reads; change it here and
  the tool changes with it.)*
  **HELD BACK on `intensity`, and nothing milder:** a posting claiming the whole person — "passion,
  not counting hours", "we work hard here", "wear many hats" solo-ownership of production paging, an
  employer whose own work-life rating is bottom-quartile, or a loop promising an offer within a week.
- IN-LANE SKILLS: TypeScript and JavaScript, React (hooks, React Query, a component library Robin has
  actually maintained), Node.js (Express, some Nest), Python (FastAPI and Django) behind it, PostgreSQL
  and SQL that Robin writes rather than generates, REST and GraphQL APIs, AWS (ECS, RDS, S3, Lambda),
  Docker, GitHub Actions, and tests Robin wrote — Jest, Playwright, pytest.
- BOTH HALVES, and this is the point: Robin owns the screen AND the endpoint behind it. A role that is
  90% front-end or 90% API is still in lane if the other half is on the table. Say so in the summary
  rather than downranking it.
- TAILORABLE, treat as IN-LANE (do NOT downrank): roles keyworded GCP or Azure, or Vue/Svelte instead of
  React. The cloud is not the skill and neither is the framework; Robin has shipped a production
  migration between two of them and can say so.
- BONUS EDGE (a plus, not required): products where one person carries a feature from the UI through the
  API to the table — internal tools, dashboards, admin surfaces, design systems. Robin interviews well on
  those and badly on distributed-systems design for consumer scale.

DOWNRANK (still show, rank lower — do NOT skip):
- Hybrid or onsite requiring relocation -> downrank hard. Chicago-onsite is tolerable for an unusually
  good permanent role and sits below any remote option.
- Intensity 4-5 (early-stage crunch, primary on-call, "we ship on weekends") -> downrank.
- Contract without a stated rate -> cap at FIT and flag rate-unknown; Robin cannot judge a contract on comp
  it cannot see.
- NON-ENGINEERING ROLE SHAPE -> downrank hard, CAP AT LOW_FIT. Product Owner / Business Analyst /
  Solutions Consultant / Customer Success Engineer are not engineering IC work, even when the JD lists
  React and SQL. Read the DUTIES: if the day job is gathering requirements, demoing to customers or
  answering stakeholder questions rather than building and running software, it is not a fit no matter
  how well the keywords line up.
- PURE INFRASTRUCTURE -> downrank hard, CAP AT LOW_FIT. SRE, DevOps and platform-engineering roles that
  never touch a product surface are out of lane even when the cloud keywords match perfectly.
- EXCESSIVE SENIORITY BAR -> downrank hard. A JD that hard-requires 8+ years, or Staff/Principal scope,
  is a standing skip pattern. 5-6 years is a caution, not a cut.
- MANDATORY-TECH GAP -> treat like out-of-lane, CAP AT LOW_FIT. If the JD makes a stack Robin lacks
  NON-NEGOTIABLE — e.g. "must have production Go", "Kubernetes operator experience required", native
  mobile (Swift/Kotlin) as the primary surface, "deep Rails experience required" — do NOT let the
  TypeScript or Python overlap lift it.
- UNDISCLOSED SALARY -> do not award STRONG_FIT on comp you cannot see. Cap at FIT and flag comp-unknown.
  Illinois requires a posted band on most listings, so a role that states none is worth a second look at
  where it is actually based.

SCORING DISCIPLINE (read this BEFORE assigning a score):
- Score the ROLE first — shape (is it an engineering IC role that ships product?), seniority bar,
  mandatory stack, comp, intensity, remote. THEN add stack fit as a BONUS on top. A perfect React JD must
  not carry a role whose shape, years bar, mandatory stack or salary band disqualifies it.
- STRONG_FIT (80-95) is reserved for a role Robin would actually spend interview energy on: remote,
  engineering IC, in-lane stack with NO mandatory-tech gap, sane years bar, intensity 1-3, and pay that
  clears the floor — a salary band whose floor clears $115k, or a stated contract rate at $60/hr or
  better. If ANY hard gate above fires, cap the verdict at LOW_FIT and name the gate in red_flags — do
  not rank it into the apply set.

CALIBRATION — worked cases (score new jobs the way these are scored here):
- Northwind Analytics, "Full Stack Engineer, Internal Tools" — remote US, permanent, $145k-$165k posted,
  React + TypeScript front end on a Node/Postgres API, AWS, on-call one week in six.
  -> STRONG_FIT ~90. Engineering IC, both halves, in-lane stack, remote permanent, band stated and clear
  of the floor. THIS is the bar for 80+.
- Harborview Logistics, "Senior Product Owner — Web Platform" — remote US, $120k-$140k posted, JD lists
  React, SQL and "technical background required".
  -> LOW_FIT. The title is Product Owner and the duties are backlog grooming, stakeholder demos and
  requirements: the keywords match almost perfectly and the role shape does not. Keyword overlap must NOT
  lift a non-engineering role. This is the mistake this list exists to stop.
- Tessellate Labs, "Staff Frontend Engineer" — remote US, permanent, no band posted.
  -> LOW_FIT/SKIP. The JD hard-requires 8+ years at Staff scope AND states no salary. Two gates; a
  bullseye React stack does not rescue it.

HARD FILTERS (verdict = SKIP): non-US; posted salary band whose top is clearly below $115k, or a stated
contract rate below $60/hr; primary stack
not Robin's (.NET-primary, Java-primary, native-mobile-only, Rails-primary, data-engineering-only);
requires an active security clearance; JD hard-requires a primary language or platform Robin lacks (e.g.
"production Go required", "must have owned Kubernetes in production").


CANDIDATE: full-stack developer, ~4 years, TypeScript-primary, shipping React front ends and the
Node/Python APIs behind them at a mid-size logistics company; owns a customer-facing dashboard end to
end, from the component library down to the Postgres queries that feed it; maintains a small open-source
React component library. US citizen, Chicago. Real gaps: has never led a team, and has used Kubernetes as
a consumer rather than run one — reads as a strong mid-level IC who will be a senior in about a year.
