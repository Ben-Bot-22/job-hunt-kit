# Tuning — every knob, what it trades, and how you would know it is wrong

Nearly every number in this repo was a **measured decision** at the moment it landed, and none of them
carries that measurement anywhere a reader will find it a quarter later. The comment beside a constant
says what it does; the run that chose it is gone. This page is the other half: for each knob, what
raising it costs, what lowering it costs, and — the part worth the page — **what you would see in the
output if it were set wrong.** A knob you cannot observe being wrong is a knob you cannot tune.

## How to read a row

Every knob is named as `` `file` · `NAME` = value ``, and that notation is machine-checked:
`core/test_tuning.py` reads this page, and fails if a name here no longer exists in the file it names,
or if a code-side value here no longer matches the code. **Retuning a constant therefore includes
editing this page** — that is the point of the test, and it is the only thing that stops this document
becoming a list of numbers the code stopped using.

Two surfaces, and the difference decides *who may change what*:

* **Config** — `config/settings.yaml`. The configuration surface. A user or an agent edits it freely,
  it is validated on load, and `config/settings.schema.json` is its machine-readable form. The values
  quoted here are the shipped defaults and are *not* pinned by the test, because editing them is the
  documented normal case.
* **Code** — a module constant. Changing one is a code change: a ticket, a test, a commit message.
  Values here **are** pinned by the test.

**Why the code-side knobs have not been promoted to settings.** The default reason, and it holds for
most rows below, is that **nobody has ever needed a second value** — a setting nobody sets is a
support surface, a schema entry and a validation rule bought for nothing. Where a knob has a *stronger*
reason to stay in code (it would let a user break a guarantee, or it is a measurement rather than a
preference), the row says so.

---

## 1. The configuration surface — `config/settings.yaml`

All rows here are **config**. The file's own comments carry the reasoning; this table carries the
failure directions.

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `config/settings.yaml` · `window_days` = 3 | more re-listings of jobs `seen.json` already knows, at near-zero cost | jobs posted on a day you did not run are never scored, and nothing ever goes back for them | a run that finds almost nothing after a weekend, or a job you find by hand that the tool never listed |
| `config/settings.yaml` · `max_workers` = 12 | wall-clock falls roughly linearly — the work is network-bound — until the provider answers 429 | a ~350-job run at 5 workers took ~25 min | 429s in the log; or a run whose duration is dominated by waiting rather than by the job count |
| `config/settings.yaml` · `prefilter.enabled` = true | (`false`) every job reaches the expensive analyzer, as it did before the gate existed | — | a `Rejected / skipped` section in the worklist naming jobs you would have wanted: the gate is biased toward keep, so any of these is a real defect |
| `config/settings.yaml` · `prefilter.screen` = true | (`false`) keeps the free regex rules, drops the small model call | — | out-of-lane roles reaching the analyzer in numbers, which costs money rather than accuracy |
| `config/settings.yaml` · `precedent.k` = 3 | more grounding per judgment, ~350 un-cached prompt tokens per precedent per scored job | at 0 the analyzer sees the JD alone and your corrections stop propagating | scores drifting back to the pre-calibration pattern — the same kind of role scoring differently across two runs |
| `config/settings.yaml` · `dedup.similarity` = 0.95 | fewer collapses; a duplicate req costs one extra analysis | **a wrong collapse silently deletes a real job** — the expensive direction | the worklist's merge lines naming two postings that are not the same req. Measured over 1,144 records: 63 postings → 48 clusters, no false merge, nearest rejected pair at 0.932 |
| `config/settings.yaml` · `dedup.overlap` = 0.80 | as above — this is the second floor, and both must clear | same as above, and this is the floor that separates *same req* from *same boilerplate* | two postings merged that share only a stock benefits section |
| `config/settings.yaml` · `dedup.min_jd_chars` = 500 | short JDs stop being compared at all, so near-duplicate stubs survive | stubs get compared on too little text, which is where a false merge is cheapest to make | merges between two postings whose JDs are both one paragraph |
| `config/settings.yaml` · `liveness.max_check` = 60 | more ranked jobs verified, ~one request of wall-clock either way | below the size of your apply list, you rank reqs that closed — the failure that added this check (all five verifiable picks from one run had already closed) | an apply doc where the top picks 404 |
| `config/settings.yaml` · `liveness.workers` = 16 | pure network waits, so this is nearly free | a serial-feeling check phase | the run summary showing liveness as a large share of wall-clock |
| `config/settings.yaml` · `models.analyze` = `claude-opus-4-8` | — | a cheaper model here is the one substitution that changes *what the tool is*: the ranking is the product | rankings you stop trusting — a role you would apply to sitting below one you would not |
| `config/settings.yaml` · `models.prefilter` = `claude-sonnet-5` | — | a weaker screen kills in-lane jobs, and a kill is invisible unless you read the skipped section | in-lane roles in `Rejected / skipped` with a screen reason |
| `config/settings.yaml` · `channels.agencies.sources` = `[]` | naming `apex` or `kore1` puts back two sources measured at 3 and 2 postings | `[]` means the four measured healthy | see §5 — a source returning single digits with no error is the silent-zero failure, and the counts in the run summary are the only detector |
| `config/settings.yaml` · `report.top_terms` = 30 | a longer, more inspectable report — at 30 it renders ~230 lines over 1,143 postings, about half of it clustered term lists | a report you can skim but cannot audit: the long tail is where a mis-clustered idea hides | a term list whose last entries are still obviously frequent — the cut is landing inside the signal |
| `config/settings.yaml` · `report.top_employers` = 20 | as above | as above | the employer table ending while counts are still in double digits |
| `config/settings.yaml` · `report.bls_areas` = `National` only | adding a metro anchors wages on a local geography | national-only hides a real local gap — the national/DFW gap measured 2026-07-22 was 6.3% on the mean and 16% at p90 | a metro line printed under a remote heading: "remote" is not a BLS geography, so a metro here is a local wage labelled as something it is not |
| `config/settings.yaml` · `report.external` = true | the keyless rate baselines, ~83 s instead of 11 s | `false` (or `--offline`) makes the run first-party only | the external half rendering as a **labelled gap** — never as a shorter report, which would read as complete |
| `config/settings.yaml` · `report.supply` = false | third-party feed counts, minutes rather than seconds | — | a supply section absent from the report, which is the default and is stated as such |

`llm.provider` is in this file too and is not a tuning knob — it is the one value that makes the tool
yours. See the README under *Which LLM providers work*.

---

## 2. Code — the shared core (`core/`)

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `core/cluster.py` · `SIMILARITY` = 0.82 | two spellings of one idea stay apart, and the report under-counts the biggest finding — *permanent role, not contract* is 127 spellings totalling 670 | two different ideas glue together under one label | a cluster whose member list contains something that is plainly a different finding. Measured: a real member sits at 0.84, the first real non-member at 0.78 — the threshold is in a gap, not on a knife edge |
| `core/cluster.py` · `CONTAINMENT` = 0.9 | the one case embeddings cannot see (`vibe-coding` inside `remotevibecodingjobs`, cosine 0.61) stops merging | partial overlaps start counting as containment — `No equity` absorbed into `Equity-heavy comp` at 0.6 | a cluster label that is a short token, with members that merely contain it |
| `core/cluster.py` · `_MIN_CONTAINED_CHARS` = 10 | short values stop being containment candidates | a three-letter token swallows everything it appears in | a two- or three-word cluster with dozens of unrelated members |
| `core/cluster.py` · `_NGRAM` = 4 | longer n-grams make containment stricter and more literal | shorter ones make it fire on shared letter runs | containment merges between words that share a stem and nothing else |
| `core/index.py` · `MD_CHUNK_CHARS` = 2000 | chunks longer than the ~512 word pieces `bge-small` actually reads — the tail is stored and never embedded | more, smaller chunks: retrieval gets more precise and less contextual | a retrieved doc whose heading matches and whose body does not contain the thing you searched for |
| `core/index.py` · `fetch_k` = 20 | MMR re-ranks a wider candidate pool, at more vector maths | too small a pool and MMR has nothing to diversify over | precedents that are all the same company or all the same title |
| `core/index.py` · `lambda_mult` = 0.5 | toward 1.0 is pure similarity — three near-identical precedents | toward 0.0 is pure diversity — precedents that are not actually similar to the job | the precedent block in the prompt reading either as one job repeated, or as three unrelated jobs |
| `core/fetch.py` · `_MIN_JD` = 120 | real but terse JDs get discarded as fetch failures and queued for the browser | interstitials and error pages count as JDs and reach the analyzer as garbage | scored jobs whose `why` is generic — the model judging a cookie banner |
| `core/llm.py` · `MAX_RETRIES` = 2 | more tolerance of provider blips, longer tail latency on a genuine outage | a transient 529 fails a job that would have succeeded | single jobs failing in a run where everything else worked. **Not promoted, and not chosen either:** it is what `anthropic.Anthropic()` has always defaulted to, made explicit so a library default cannot move it underneath us |

---

## 3. Code — the daily run (`triage/`)

### The prefilter, which is where the tool's opinions are hard-coded

`triage/prefilter.py` is the only module whose constants encode a *person's* bar rather than a
measurement, and the whole file's failure direction is asymmetric: **a wrong kill costs a job you
never see; a wrong keep costs one analysis.** Everything here is tuned toward keep, and the kills are
still rendered in the worklist's `Rejected / skipped` section with a reason, so nothing disappears
silently. **Reading that section is how you tune this file** — it is the only observable.

The regexes are pinned to 2026-07 posting boilerplate. **Drift here is invisible**: a JD phrasing that
stops matching does not error, it simply stops filtering, and the cost is money rather than a wrong
answer — which is why it can go unnoticed for months.

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `triage/prefilter.py` · `_YEARS_BAR` = 10 | 12+ and 15+ bars survive to the analyzer and occasionally rank | 7–8 year asks — routinely stretchable — get killed mechanically | a job in `Rejected / skipped` for a years bar you would have stretched; or (the failure that added this) a stated "10+ Years of Experience" scoring 83 and reaching the apply list |
| `triage/prefilter.py` · `_TRAVEL_BAR` = 50 | heavy-travel roles reach the ranking | occasional-travel roles get killed | a skip reason citing travel on a role that said "up to 25%" |
| `triage/prefilter.py` · `_SHOP_STRONG` (4 patterns, any one fires) | a body shop reaches the analyzer — cheap | **a real agency gets cut, and agency reqs are the fastest fills and the only contract supply** | a named staffing firm in `Rejected / skipped`. Measured over 1,134 jobs: 6 cut, and 0 of the 41 postings from the 28 named staffing agencies in the corpus |
| `triage/prefilter.py` · `_SHOP_WEAK` (5 patterns, two must fire) | as above | one weak tell alone would have killed three real employers — which is why two are required | a skip whose reason names a single weak tell |
| `triage/prefilter.py` · `_OFF_LANE_TITLE` | a `.NET`/Java-titled role reaches the analyzer | a JD that merely mentions Java in a nice-to-have gets killed — the rule is **title-only** on purpose, and `_IN_LANE_RESCUE` exists so "JavaScript" cannot match "java" | a full-stack role skipped for a stack it mentions once |
| `triage/prefilter.py` · `_MAX_JD` = 2500 | the screen reads more context than it needs, at more tokens per job | the screen judges on a header and a benefits list | screen kills on jobs whose in-lane content is below the cut |
| `triage/prefilter.py` · `_SCREEN_MAX_TOKENS` = 400 | headroom, unused | 200 truncated the JSON on ~2% of calls — a wasted screen, measured | screen calls failing to parse in the log |

### Prompt budgets — every one of these is tokens against context

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `triage/analyze.py` · `_MAX_JD` = 8000 | more JD in the prompt, more cost per scored job | the requirements section falls off the end of a long JD and the verdict is made without it | a `why` that misses a stated requirement present in the posting |
| `triage/analyze.py` · `_MAX_TOKENS` = 8000 | headroom | a truncated structured response — the whole judgment lost | analysis failures on the longest JDs only |
| `triage/precedent.py` · `_MAX_QUERY_JD` = 1500 | past ~512 word pieces `bge-small` stops reading, so this is embedded weight rather than signal | too little text and the retrieval query is a title | precedents that match the title and not the role |
| `triage/precedent.py` · `_MAX_WHY` = 300 | precedent reasoning becomes a paragraph each, times `precedent.k`, every scored job | one line becomes half a line and stops carrying the reason | precedent lines in the prompt that end mid-sentence |
| `triage/channels/common.py` · `_MAX_CONTENT` = 16000 | more of each email reaches the extractor; big digests list 60+ jobs | a digest's later jobs are never seen | a digest email yielding far fewer jobs than it lists |
| `triage/channels/common.py` · `_MAX_URLS` = 200 | more candidate links per email; one RemoteVibeCoding digest carries 57 | links dropped before the extractor sees them | as above |
| `triage/channels/common.py` · `_EXTRACT_MAX_TOKENS` = 20000 | headroom | truncated extraction — an email's jobs lost wholesale | an email that yields zero jobs and no error |
| `triage/channels/common.py` · `_BACKFILL_JD_CHARS` = 6000 | more of a pasted URL's page is read to recover title and company | the header and first requirements block are enough; below that, the title is guessed | pasted jobs arriving with a wrong or empty company |
| `triage/channels/common.py` · `_BACKFILL_MAX_TOKENS` = 500 | headroom | truncated backfill | as above |

### Safety caps — none of these is a performance knob; each bounds one bad run

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `triage/channels/mail.py` · `_MAX_EMAILS` = 250 | a backlogged inbox is read in one run, at proportional time | a normal day's mail is truncated and the excess is never revisited | the `mail` count sitting exactly at the cap |
| `triage/channels/boards.py` · `_MAX_PER_BOARD` = 200 | a board that republishes wholesale costs a long run instead of a noisy one | a large employer's board is truncated newest-first | a board count sitting exactly at 200 |
| `triage/channels/paste.py` · `_MAX_URLS` = 200 | as above, for `--paste-file` | a long paste file silently truncated | a paste count at exactly 200 |
| `triage/channels/agencies.py` · `_MAX_PER_SOURCE` = 200 | same shape and same reason as `_MAX_PER_BOARD` | an agency's board truncated after the freshness window | a source count at exactly 200 |
| `triage/channels/agencies.py` · `_DEADLINE` = 300.0 | a hang detector with less room: TEKsystems' *healthy* run is 131 s and the four sources run concurrently | a slow-but-working source is abandoned mid-run | a source reporting 0 in a run where it worked yesterday, with the channel finishing at ~300 s. **Not promoted:** one shared deadline bounds the channel; four per-source timeouts would stack to twenty minutes, which is the number nobody wanted |
| `triage/channels/agencies.py` · `DEFAULT_SOURCES` | see §5 | see §5 | see §5 |
| `triage/dedup.py` · `_SHINGLE` = 5 | longer shingles: only near-identical text overlaps | shorter ones and shared stock phrases start overlapping, which is exactly the false merge `overlap` exists to prevent | a merge justified by boilerplate |
| `triage/dedup.py` · `_MAX_EMBED_CHARS` = 4000 | past ~512 word pieces this is weight, not signal | too little text and two different reqs at one company look identical | merges between two genuinely different roles at the same employer |
| `triage/liveness.py` · `timeout` = 15.0 | slow boards get a verdict instead of a timeout | a slow-but-live req is reported unverifiable | liveness verdicts that are mostly "could not check" |

---

## 4. Code — research and the market report (`research/`)

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `research/retrospective.py` · `COMPANY_SIMILARITY` = 0.88 | two spellings of one firm counted twice, splitting its employer row | **two different firms shown as one** — proper nouns need a tighter threshold than prose does, which is why this sits above `cluster.SIMILARITY`'s 0.82 | an employer row whose member spellings name two companies |
| `research/retrospective.py` · `TOP_EMPLOYERS` = 20 | a longer employer table | the tail is cut where counts are still meaningful | see `report.top_employers` |
| `research/retrospective.py` · `TOP_TERMS` = 30 | as above, for terms | as above | see `report.top_terms` |
| `research/report.py` · `MAX_SPELLINGS` = 8 | the biggest red flag prints ~100 member lines and the report stops being skimmable | fewer spellings, and the spellings **are** the audit trail for the count | a cluster whose printed members do not obviously add up to its total. The cut is *stated* in the output, because a silent truncation reads as the whole answer |
| `research/snapshots.py` · `MIN_SNAPSHOTS` = 3 | a stricter gate: trends appear later and are better supported | two snapshots is a trend claim resting on two observations | a trend line drawn from a run-to-run wobble. **Not promoted:** this is a claim-honesty gate, not a preference — a user lowering it would publish a trend the data cannot carry |
| `research/snapshots.py` · `MIN_DAYS` = 60 | as above, in time | three snapshots inside one week is a trend claim resting on one week | as above — both gates must clear, deliberately |
| `research/snapshots.py` · `TOP_TERMS` = 20 | a wider term set carried into each snapshot, and snapshots are permanent files | a narrower one, and a term that mattered later was never recorded | a trend section that cannot follow a term the current report ranks highly |
| `research/agent.py` · `MAX_PASSES` = 3 | a non-deterministic loop stops being affordable | fewer lookups and the brief is thinner | a brief that says "undetermined" on questions one more page would have answered. **Not a tuning knob:** it is the reason the loop is bounded at all |
| `research/agent.py` · `_Q_SAME` = 0.5 | near-duplicate questions survive into the brief | genuinely different questions get merged | two questions in the brief that are the same question |
| `research/agent.py` · `_Q_SHINGLE` = 4 | stricter question matching | shorter shingles match on shared phrasing | as above |
| `research/boards.py` · `_MIN_PAGE` = 200 | a thin but real careers page is treated as a shell | a redirect notice or an error page is read as evidence | a brief citing a "careers page" that contains nothing |
| `research/cache.py` · `MAX_AGE_DAYS` = 14 | a stale brief is served for a company whose board has moved on | every lookup re-runs the agent, at a model call each | a brief whose "what else is on their board" no longer matches the board. A judgement about how fast a board moves, not a knob |
| `research/history.py` · `_SAME_JD` = 0.25 | the same req posted by an agency and by the employer stops being recognised as one | unrelated JDs start matching — though the noise floor is ~0 shared 5-grams even between two full-stack boilerplate JDs, so there is room below | a history section that fails to tell you that you have seen this exact req before, under another name |
| `research/history.py` · `_SHINGLE` = 5 | as `dedup._SHINGLE` | as `dedup._SHINGLE` | — |

### The market data sources — all of these are rate-limit and politeness knobs

Coverage failures here are **silent**: a source that gets throttled returns fewer rows, not an error.

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `research/sources/adzuna.py` · `DETAIL_WORKERS` = 3 | measured: 4 workers with no throttle got **12 of 25** detail pages 403'd; 3 at 1.0 s got **0** | slower, no more reliable | a detail-fetch count well below the posting count |
| `research/sources/adzuna.py` · `DETAIL_THROTTLE` = 1.0 | politer and slower | 403s, which look like missing data rather than like an error | as above |
| `research/sources/adzuna.py` · `THROTTLE` = 1.0 | as above, for the listing pages | Adzuna's free rate limits are undocumented, so this is deliberately conservative | listing pages returning fewer results than the reported total |
| `research/sources/adzuna.py` · `MAX_PAGES` = 1 | more sample, linearly more wall-clock and more detail fetches | one page of 50 is the sample | a supply count that is always exactly `RESULTS_PER_PAGE` |
| `research/sources/adzuna.py` · `MAX_DAYS_OLD` = 3 | stale reqs in a supply count that is meant to measure *current* hiring | too narrow and a slow-posting week reads as a market contraction | a supply drop that coincides with nothing in the news |
| `research/sources/adzuna.py` · `_SAME_AD_CHARS` = 120 | a detail page is accepted as belonging to the teaser when it does not | a real detail page is rejected as a mismatch | JDs attached to the wrong posting — the expensive direction, hence the check |
| `research/sources/himalayas.py` · `MAX_PAGES` = 50 | linear: 1,000 rows in ~20 s, out of a board of 95,456. This is the newest slice, not the board | a smaller sample of the newest postings | a Himalayas count that moves with your page cap rather than with the market |
| `research/sources/himalayas.py` · `THROTTLE` = 0.2 | politer, and 50 pages makes it visible | a public API paged 50 times without a pause | rate-limit responses mid-page-loop |
| `research/sources/calc.py` · `MAX_ROWS` = 6000 | more of the CALC+ ceiling-rate corpus | **a stop, not a sample** — hitting it is written into the report's caveat | the caveat appearing every month, which means the ceiling is now the binding constraint |
| `research/sources/calc.py` · `PAGE_SIZE` = 1000 | ~0.9 MB and ~0.8 s per page; the API accepts it without complaint | more requests for the same rows | — |
| `research/sources/calc.py` · `THROTTLE` = 0.5 | a public `.gov` endpoint being paged to exhaustion; be visibly polite | — | — |
| `research/sources/calc.py` · `TIMEOUT` = 60 | tolerance for a slow public endpoint | a timeout renders as a labelled gap in the report, never as a smaller number | the external half missing with no explanation |
| `research/sources/bls.py` · `TIMEOUT` = 180 | measured: BLS took over 60 s to answer a 7-series request and timed out at 60 | as above | the wage baseline absent from the report |
| `research/sources/bls.py` · `MAX_QUERIES` = 2 | of a **25/day** allowance. **Not promoted:** it is a hard stop against burning a daily quota in a loop, not a budget to spend | fewer series per run | a run that reports a partial wage baseline |
| `research/sources/theirstack.py` · `MAX_JOBS` = 160 | **TheirStack bills one credit per job returned, not per match** — this is a credit cap | a smaller supply sample | credits gone in one run. **Not promoted:** a user raising it spends their own money without being asked |
| `research/sources/theirstack.py` · `POSTED_DAYS` = 3 | a wider query window, more credits | as `MAX_DAYS_OLD` | — |
| `research/sources/jsearch.py` · `DATE_POSTED` = `3days` | one request per term is one of **200/month** — the window buys freshness, not volume | — | a monthly quota exhausted mid-month |
| `research/sources/jsearch.py` · `THROTTLE` = 0.5 | politeness on a metered API | — | — |

---

## 5. The agency scrapers — caps, throttles, and the rot baseline

**These parse live HTML and they fail by returning zero, not by raising.** A site that restructures
does not error; it stops matching. The per-source counts printed in the run summary are the **only**
detector there is, and nothing in the code can tell a rotted scraper from a genuinely small board.
That is why the last measured counts are recorded here and in `core/scrapers/__init__.py`: the
baseline *is* the test.

**Measured live 2026-07-22:**

| source | count | reading |
|---|---|---|
| Insight Global | 87 | healthy |
| TEKsystems | 78 | healthy — and 131 s, the slowest of the four |
| Motion | 27 | healthy |
| Mondo | 15 | healthy |
| Apex | 3 | small board *or* partly rotted — excluded from `DEFAULT_SOURCES` |
| KORE1 | 2 | same |

A source is put back into `channels.agencies.sources` when a fetch returns a **double-digit** count
whose postings survive a spot-check — at which point it is added to `DEFAULT_SOURCES` and said so in
the commit.

Per-source caps and throttles. All **code**; not promoted because they are properties of somebody
else's website, not of your search, and a user tuning them would be tuning a page structure they
cannot see:

| knob | raising it | lowering it | wrong — what you would see |
|---|---|---|---|
| `core/scrapers/insightglobal.py` · `MAX_PAGES` = 2 | more coverage, linearly slower | 87 postings came from 2 pages; fewer pages cuts the newest slice | a count that tracks the cap rather than the board |
| `core/scrapers/insightglobal.py` · `THROTTLE` = 0.7 | politer | the fastest way to get a scraper blocked, which presents as rot | a healthy source going to 0 shortly after a throttle was lowered |
| `core/scrapers/teksystems.py` · `MAX_JOBS` = 150 | more of the sitemap fetched, and this source is already the slowest at 131 s | fewer jobs | the channel hitting `_DEADLINE` |
| `core/scrapers/teksystems.py` · `THROTTLE` = 0.25 | politer, slower | as above | as above |
| `core/scrapers/mondo.py` · `MAX_JOBS` = 200 | more of the sitemap | fewer | a count at exactly the cap |
| `core/scrapers/mondo.py` · `THROTTLE` = 0.3 | politer | — | — |
| `core/scrapers/motion.py` · `MAX_PAGES` = 6 | more coverage | 27 postings came from 6 pages | a count at exactly the cap |
| `core/scrapers/motion.py` · `THROTTLE` = 0.3 | politer | — | — |
| `core/scrapers/apex.py` · `MAX_PAGES` = 8 | 8 pages yielded 3 postings — the keyword filter is AJAX-gated, so a plain GET sees a shallow slice regardless | — | raising this and getting the same 3 is the evidence that it is the *page*, not the cap |
| `core/scrapers/apex.py` · `THROTTLE` = 0.3 | politer | — | — |
| `core/scrapers/kore1.py` · `MAX_JOBS` = 60 | as Apex — 2 postings against a cap of 60 | — | as Apex |
| `core/scrapers/kore1.py` · `THROTTLE` = 0.3 | politer | — | — |

---

## What is deliberately not on this page

Not every constant is a knob, and listing the rest would bury the ones that are. Excluded, by rule:

* **Paths, filenames and prefixes** — `config.py`'s directory constants, `INDEX_FILENAME`,
  `market-numbers-`. Changing one is a rename, not a tuning decision.
* **Endpoints, user-agent strings and model ids in code** — facts about someone else's service.
* **Regex source that encodes a format rather than a threshold** — `core/rates.py`'s money patterns,
  `core/models.py`'s legal-suffix list. They are either right or broken; there is nothing to trade.
  The prefilter's regexes *are* listed, because there the bar itself is a judgment.
* **Limits imposed by an API, which we do not get to choose** — `himalayas.PAGE` = 20 (the API's hard
  cap: ask for 50 and it returns 20 and says so), `theirstack.PER_PAGE` = 25 (free-plan error E-020
  above it), `bls.MAX_SERIES` = 25 (the v1 API's per-request limit), `adzuna.RESULTS_PER_PAGE` = 50.
* **On-disk format versions** — `snapshots.VERSION`. A number that must change when a shape changes,
  not one you tune.
