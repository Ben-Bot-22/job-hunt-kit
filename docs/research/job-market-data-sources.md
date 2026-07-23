# Job-market data sources for an optional market-research module

Research for ticket `.scratch/jobs-db-oss-rag/issues/03-job-market-data-sources.md`.
Investigated 2026-07-21. All claims cite a primary source; every "live" claim was verified by an
actual HTTP call on that date, not from documentation alone.

> **Path note (2026-07-22).** Stage 5 · 01 gutted the frozen `jobsdb/` pipeline; the source modules
> this document describes now live in `research/sources/` and the rate extractor in `core/rates.py`.
> Paths below have been updated in place; every measurement is as originally taken.

> **Note on location.** Settled: `docs/` is the single doc root. Runbooks live in `docs/operating/`;
> this is a one-off research artifact tied to a wayfinding ticket, so it lives in `docs/research/`.

---

## TL;DR

- **Adzuna's US salary data is ~100% machine-predicted.** Every result in a live 50-row sample came
  back `salary_is_predicted: "1"` with `salary_min == salary_max` — a Jobsworth point estimate, not a
  posted salary. It is worthless as evidence of what a specific employer pays, and useless for
  contract *hourly* rates (it emits annualised figures even for `contract_type: contract`).
- **JSearch returns real posted salary on roughly 1 in 10 US software results** — but when present it
  is genuine employer data, and it returns full job descriptions (1.7k–7.3k chars) versus Adzuna's
  hard 500-char snippet.
- **No commercial job API gives credible US contract hourly rates.** The only free, authoritative,
  *hourly*, *US*, *contract* rate baseline found is **GSA CALC+ (CEILINGRATES)** — a federal
  government API, live, **no key at all**.
- **ToS verdict: nothing blocks open-sourcing the integration code.** Both restrictive ToS govern
  *data*, not client software. What they do constrain is (a) shipping cached data in the repo,
  (b) sharing one key across users, (c) commercial aggregation.
- **A credible zero-key path exists** — GSA CALC+ and BLS OEWS (v1, unregistered) together, plus
  Himalayas/Remotive for live posting supply. It is genuinely weaker than the keyed path on posting
  breadth but *stronger* on rate honesty.

---

## 1. Adzuna and JSearch today

### What the existing code actually pulls

| | `research/sources/adzuna.py` | `research/sources/jsearch.py` |
|---|---|---|
| Endpoint | `GET https://api.adzuna.com/v1/api/jobs/us/search/{page}` | `GET https://jsearch.p.rapidapi.com/search-v2` |
| Auth | `app_id` + `app_key` query params (`config.ADZUNA_APP_ID/KEY`) | `X-RapidAPI-Key` header (`config.RAPIDAPI_KEY`) |
| Query shape | one call per term in `config.STACKS` × `max_pages` (6 terms × 1 page = **6 calls/run**) | one call per term, `country=us`, `date_posted` (**6 calls/run**) |
| Skips cleanly without a key | yes (`adzuna.py:19-21`) | yes (`jsearch.py:27-29`) |
| Throttle | 1.0 s between calls | 0.5 s between calls |

Both endpoints are **still current**. Verified live 2026-07-21:

- `https://api.adzuna.com/v1/api/jobs/us/search/1` → `400` unauthenticated, `200` with Ben's
  credentials, `count: 24881` for `what=software engineer`, `max_days_old=7`.
- `https://jsearch.p.rapidapi.com/search-v2` → `401` unauthenticated, `200` with the key.
  The code comment in `jsearch.py:20` ("v1 `/search` was retired; v2 wraps jobs in `data["jobs"]`")
  still matches the live response shape.

### Adzuna — limits, auth, fields

Rate limits are published in the ToS, not the API docs
([developer.adzuna.com/docs/terms_of_service](https://developer.adzuna.com/docs/terms_of_service)):

> 25 hits per minute / 250 hits per day / 1000 hits per week / **2500 hits per month**

At 6 calls/run this is not close to binding, even at several runs a day. Auth is a free
`app_id`/`app_key` pair from [developer.adzuna.com/signup](https://developer.adzuna.com/signup);
there is no paid self-serve tier — larger volume is a "contact us" conversation.

Beyond `/search`, Adzuna exposes aggregate endpoints that are a better fit for a *market-research*
module than scraping individual ads: `/histogram` (salary distribution),
`/history`, `/top_companies`, `/geodata`, and `/jobsworth`
([developer.adzuna.com/overview](https://developer.adzuna.com/overview)). `/histogram` returns
vacancy counts per salary bucket
([developer.adzuna.com/docs/histogram](https://developer.adzuna.com/docs/histogram)); a live call for
`what=software engineer` returned:

```
{"40000": 392, "60000": 899, "80000": 1524, "100000": 2310,
 "120000": 3214, "140000": 19194, "20000": 50}
```

**Salary reliability — the decisive finding.** A live 50-result sample of US `software engineer`:

| Measure | Result |
|---|---|
| Results carrying a salary | 50 / 50 (100%) |
| `salary_is_predicted == "1"` | **50 / 50 (100%)** |
| `salary_min == salary_max` | every row (e.g. `98379.59 / 98379.59`) |
| `contract_type` present in the payload | **0 / 50** |
| `description` length | exactly 500 chars, every row |

Filtering to `contract=1` (976 US hits) improves this only marginally: **47/50 still predicted**, and
all values are annualised — e.g. `122308.06`, `253410.55` — not hourly rates. So for the ticket's
key question:

> **Adzuna returns no usable salary evidence for US contract roles.** It returns a model's guess at
> an annual-equivalent number. `salary_is_predicted` is the flag that says so, and the current code
> never reads it (`adzuna.py:65-66` labels the value `"(Adzuna est.)"`, which is an honest hedge, but
> the field is dropped into `salary_min`/`salary_max` as if it were observed data).

Adzuna's own history explains why: roughly half of the ads it indexes carry no salary at all, which
is precisely what Jobsworth was built to paper over
([TechCrunch, 2013](https://techcrunch.com/2013/07/24/pay-day)).

Two further live-verified limitations of the current integration, both worth carrying into any
refactor:

1. **`contract_type` is absent from unfiltered `/search` results.** `adzuna.py:61` does
   `item.get("contract_type", "")`, so the synthesised `"Employment type: unspecified"` string is
   what every Adzuna job carries into the scorer. The field only appears when you *filter* on it
   (`contract=1` → `contract_type: "contract"` on all 50 rows). Contract vs permanent must be
   obtained by issuing separate filtered queries, not by reading the field.
2. **Descriptions are truncated to 500 characters.** Adzuna states this outright: "we currently only
   provide a snipped of the job description in the response"
   ([developer.adzuna.com/docs/search](https://developer.adzuna.com/docs/search)). Anything doing
   keyword/stack extraction from Adzuna text is working from an ad teaser.

### JSearch — limits, auth, fields

JSearch is built and operated by **OpenWeb Ninja / Whats Next Labs LLC** (Sunnyvale, CA) and resold
through the RapidAPI marketplace. Published plans
([openwebninja.com/api/jsearch](https://www.openwebninja.com/api/jsearch)):

| Plan | Price | Requests/mo | Rate |
|---|---|---|---|
| Free | $0 | **200** | 1000/hr |
| Pro | $25/mo | 10,000 | 5/s |
| Ultra | $75/mo | 50,000 | 10/s |
| Mega | $150/mo | 200,000 | 20/s |
| PAYG | $0.005/req | — | 5/s |

The 200/mo free quota was confirmed from the live response headers on 2026-07-21:
`X-RateLimit-Requests-Limit: 200`, `X-RateLimit-Requests-Remaining: 157`. The code comment in
`jsearch.py` and `.env.example` are both accurate. **At 6 calls/run, a daily cron consumes ~180 of
200 requests per month** — the free tier is genuinely tight, which is exactly why `config.yaml`
throttles it with `every_days: 1`. Any broadening of `search.terms` breaks the free tier.

Live field inventory (`/search-v2`, `query=software engineer&country=us&date_posted=3days`, n=10):

| Measure | Result |
|---|---|
| Rows with `job_min_salary` or `job_max_salary` | **1 / 10** |
| `job_salary_period` where present | `YEAR` |
| `job_employment_type` | `Full-time` × 10 |
| `job_is_remote` | `false` × 10 |
| `job_description` length | 1759–7253 chars (**full text**) |
| `job_publisher` | LinkedIn (with `apply_options[]` giving each publisher's link) |

The one salaried row was `175000–245000 YEAR` — a real posted range. So JSearch's salary coverage is
*sparse but honest*, the inverse of Adzuna's *complete but synthetic*. Neither returns hourly
contract rates in this sample.

JSearch also exposes **`/estimated-salary`**, which is the closest thing either provider has to a
market-research primitive. Live call (`Software Engineer`, `United States`):

```json
{"min_salary": 120328.93, "median_salary": 150680.69, "max_salary": 191191.25,
 "median_base_salary": 116367.12, "median_additional_pay": 34313.57,
 "salary_period": "YEAR", "salary_count": 720651,
 "publisher_name": "Glassdoor", "confidence": "CONFIDENT",
 "salaries_updated_at": "2025-04-10T23:59:59.000Z"}
```

Useful, well-sourced, and **annual-only** — and note `salaries_updated_at` is over a year stale as of
this research. It answers "what does a US software engineer earn", never "what does a US contract
React role bill at".

### Verdict on point 1

Both are live and viable. **Neither solves the salary problem for US contract roles**, which the map
identifies as the most valuable field. Adzuna is best used for *aggregate* signal (`/histogram`,
`/top_companies`, vacancy counts by term/geo) where a predicted-salary distribution is at least
internally consistent; JSearch is best used for *full JD text* on a small number of queries. Contract
hourly rates have to come from somewhere else (see §3, GSA CALC+) or from parsing rate strings out of
the JD body.

---

## 2. Terms of service — the gate

### Adzuna

Source: [developer.adzuna.com/docs/terms_of_service](https://developer.adzuna.com/docs/terms_of_service)
(retrieved 2026-07-21).

Permissible use is an enumerated list:

> The Adzuna API may be used for:
> Publishing Adzuna ad listings / Publishing Jobsworth salary estimates / **Personal research**

**(a) Storing results locally** — not addressed. There is no caching, database-rights, or retention
clause. The only data-removal obligation is on termination:

> Upon termination of this agreement, for any reason and by either party, an API user shall
> immediately remove all insertion codes and data acquired from Adzuna from all pages of its web sites.

Note the scope: "from all pages of its **web sites**". A local file on a laptop is not a web site.
Reading this as permissive for local storage is reasonable, but it is a gap in the terms rather than
an express grant.

**(b) Aggregating into a report** — this is the clause that matters, and it is a real constraint:

> Any other use of the Adzuna API by a **commercial, government or academic organisation** including
> any affiliates or individuals, is permitted subject to a 14 day trial period. This period is
> strictly for the purpose of validating the general coverage and quality of the data […] **It may
> not be used in its original format or in aggregation (including but not limited to vacancy counts,
> average salaries etc) to deliver any ongoing work or research** […] without written consent.

Read carefully, this bites on "any **other** use" by a commercial/government/academic organisation.
An individual doing **personal research** — an unemployed developer profiling his own job market —
falls under the enumerated permissible use, not the 14-day trial carve-out. That reading is
defensible, but it is a reading, and the sentence explicitly reaches "affiliates or **individuals**"
of such organisations. **Practical consequence: a market-research module built on Adzuna is fine for
personal use and is not fine as a commercial product or a hosted service.** That happens to align
exactly with standing rule 1 (a repo a stranger runs on their own machine with their own key), so
the constraint is satisfiable — but it must be stated in the README, because a user who deploys this
inside their employer is out of compliance.

Attribution is mandatory and specific. For personal/academic research:

> An API user shall acknowledge Adzuna as the source of all salary and vacancies data wherever it is
> published. References should refer to: "The Adzuna API" and link to http://www.adzuna.co.uk/ or the
> relevant local domain.

If listings are *displayed*, the heavier requirement applies — a "Jobs by Adzuna" label at least
116×23 px with specific hyperlinks; Jobsworth estimates need a 20×20 px icon, the words "Adzuna
Jobsworth", a link to the salary predictor, and the mouseover text "Salary estimate powered by Adzuna
Jobsworth". For a Markdown report the pixel specs are inapplicable, but the source acknowledgement is
not — **any report that prints an Adzuna salary number must credit Adzuna Jobsworth and link it.**

**(c) Does the ToS permit an open-source repo shipping the integration?** Nothing in the document
addresses source code, redistribution, or sublicensing at all. It constrains what an API *user* does
with *data*. Publishing a client library that calls the API is not use of the data. **Not blocked.**

One clause does shape the OSS design, though:

> **Creation of multiple accounts for a single entity or individual** will immediately be considered
> misuse and a breach of these terms and conditions.

This forbids key-farming, not per-user keys. It reinforces the correct design: **each cloner
registers their own `ADZUNA_APP_ID`/`APP_KEY`; the repo never ships a key, and never proxies through
a shared one.**

Also note, for anyone tempted to enrich Adzuna results by going upstream:

> An API user agrees to direct all queries via Adzuna. Any attempt to contact a third party, even
> where they provide listings content, will be considered a breach […] their access to the API will
> be revoked immediately.

### JSearch / OpenWeb Ninja

Two documents stack here, and the *provider's* terms are the operative ones.

**RapidAPI (now Nokia of America Corporation, dba Rapid).** Rapid's Terms
([rapidapi.com/terms](https://rapidapi.com/terms), which resolves to
[rapidapi.com/page/terms](https://rapidapi.com/page/terms)) distinguish "API Providers" (who list
APIs) from "API Consumers" (who call them); Rapid operates the marketplace and billing, and the
substantive rights in the data flow from the provider. The full text is JavaScript-rendered and was
not retrievable by automated fetch, which is itself worth flagging: **this ToS could not be verified
verbatim from the primary source**, only its structure via search snippets. RapidAPI's parent Rapid
was acquired by Nokia in November 2024 and the marketplace is still operating; there is a live-tested
dependency on a platform with a distressed corporate history
([TechCrunch, 2023](https://techcrunch.com/2023/05/05/rapidapi-headcount-down-82-from-fresh-layoffs-less-than-two-weeks-after-cutting-50-of-staff/)).
Because OpenWeb Ninja sells the same API direct, that risk is mitigable by switching hosts.

**OpenWeb Ninja / Whats Next Labs LLC** ([openwebninja.com/terms](https://www.openwebninja.com/terms),
last updated 2025-10-17) is the binding one, and it is markedly more restrictive than Adzuna's:

> The Content and Marks are provided in or through the Services "AS IS" for your **personal,
> non-commercial use or internal business purpose only**.

> Except as set out in this section […] no part of the Services and no Content or Marks may be
> copied, reproduced, **aggregated**, republished, uploaded, posted, publicly displayed, encoded,
> translated, transmitted, distributed, sold, licensed, or otherwise exploited **for any commercial
> purpose whatsoever**, without our express prior written permission.

And in §8 Prohibited Activities:

> As a user of the Services, you agree not to: **Systematically retrieve data or other content from
> the Services to create or compile, directly or indirectly, a collection, compilation, database, or
> directory without written permission from us.**

> Use the Services as part of any effort to compete with us or otherwise replicate our API as a
> service offerings in a revenue-generating endeavor or commercial enterprise.

**(a) Storing results locally** — §8 says *systematic* retrieval to build "a collection, compilation,
database, or directory" is prohibited without written permission. Read literally, that is what a
`jobs-db` is. In fairness this is boilerplate (a Termly-style template) written for a *website*, and
the paid API tiers make no sense if callers can't retain what they buy. But **as written, this ToS is
hostile to the thing the module does**, and it is the strictest text found in this research.

**(b) Aggregating into a report** — permitted for "personal, non-commercial use or internal business
purpose"; explicitly prohibited "for any commercial purpose whatsoever".

**(c) Open-sourcing the integration** — again, nothing restricts publishing a client. The prohibition
is on replicating *their API as a service*. A local CLI that calls JSearch with the user's own key is
not that. **Not blocked.** Note there is no attribution requirement in OpenWeb Ninja's terms
comparable to Adzuna's — but individual postings carry `job_publisher` (LinkedIn, etc.) and apply
links should be preserved rather than stripped.

### The government sources

- **BLS** — public domain, with a citation duty: users must cite the retrieval date and state that
  "BLS.gov cannot vouch for the data or analyses derived from these data after the data have been
  retrieved from BLS.gov", and may not modify content and still attribute it to BLS
  ([bls.gov/developers](https://www.bls.gov/developers/)). No commercial restriction. Note bls.gov
  *web pages* return 403 to automated clients; `api.bls.gov` does not.
- **GSA CALC+** — a US Government API on `api.gsa.gov`. The documentation states plainly: "Access to
  this tool does not require user credentials or authentication"
  ([open.gsa.gov/api/dx-calc-api/](https://open.gsa.gov/api/dx-calc-api/)). No usage restrictions are
  published; the underlying contract-award data is federal public record.
- **DOL OFLC disclosure data** (H-1B LCA) — quarterly public-record XLSX downloads
  ([dol.gov/agencies/eta/foreign-labor/performance](https://www.dol.gov/agencies/eta/foreign-labor/performance)),
  public domain.

### Explicit ToS verdict

> **No source examined blocks open-sourcing the integration.** Every restrictive clause found governs
> use of the *data*, not distribution of *client code*. Adzuna and OpenWeb Ninja both bound their
> grants to personal / non-commercial / internal-business use, and OpenWeb Ninja's §8 additionally
> prohibits systematic retrieval into a database. The compliant shape is therefore forced, and it is
> the shape the project already wants:
>
> 1. Ship code, never data. **No cached API results, no sample corpus, no fixtures containing real
>    listings, committed to the repo.** (`.gitignore` already excludes `data/` and `.state/`.)
> 2. Every user brings their **own** key; never a shared or proxied key (Adzuna: multiple accounts
>    for one entity = breach).
> 3. Label the module **personal, non-commercial use** in the README, and say out loud that
>    commercial or organisational use requires the user to obtain their own written consent /
>    licence from Adzuna and OpenWeb Ninja.
> 4. Print the Adzuna attribution line whenever an Adzuna figure appears in a report, and the
>    Jobsworth credit whenever a predicted salary appears.
> 5. Preserve `job_publisher` / apply links rather than stripping provenance.

---

## 3. Alternatives worth knowing about

Every "live" row below was called on 2026-07-21.

### Comparison table

| Source | Cost / free tier | Auth | US remote/contract software coverage | Salary field | ToS posture | Live |
|---|---|---|---|---|---|---|
| **Adzuna** `/search`, `/histogram` | Free; 250/day, 2500/mo | free `app_id`+`app_key` | broad (24,881 US "software engineer" hits, 976 with `contract=1`) | **predicted, annual, point estimate — 100% of sample** | personal research OK; commercial/org = 14-day trial + written consent; heavy attribution | ✅ |
| **JSearch** (RapidAPI / OpenWeb Ninja) | Free 200 req/mo; $25/mo for 10k | RapidAPI key header | broad (Google-for-Jobs aggregation, LinkedIn et al.) | **real but sparse (~1/10)**, annual; `/estimated-salary` gives Glassdoor aggregates | personal/non-commercial only; §8 bars systematic DB-building; no attribution clause | ✅ |
| **GSA CALC+ / CEILINGRATES** | **Free, unlimited, no account** | **none** | federal contract labor categories, US-wide | **real hourly contract rates** — 296 "Software Engineer" rows, median **$113.53/hr** | US Gov public record; no published restriction | ✅ |
| **BLS OEWS via Public Data API v1** | **Free, no key**, 25 queries/day | none (v2 = free key, 500/day) | national/MSA wage stats by SOC (15-1252 Software Developers) | **authoritative annual + hourly means/percentiles** | public domain + citation duty | ✅ |
| **Himalayas** | Free | **none** | 97,673 jobs total; strong remote, US-filterable | `minSalary`/`maxSalary` present on **55%** of US SWE sample — but **annual only**, and **1 of 94 was `Contractor`** | attribution required; "do not submit Himalayas jobs to third-party websites" | ✅ |
| **Remotive** | Free | **none** | remote-only, modest volume (41 results for "software engineer") | `salary` free-text on **33/41**; **includes hourly strings** (`"$90 - $150 /hour"`); `job_type` includes `contract`/`freelance` (6/41) | free API, attribution expected | ✅ |
| **Greenhouse Job Board API** | Free | **none for GETs** | per-company only; needs a curated board-token list | `?pay_transparency=true` → `pay_input_ranges[]` with `min_cents`/`max_cents` | public job-board endpoints; per-employer | ✅ (200) |
| **Lever postings API** | Free | **none** | per-company only | varies | public job-board endpoints | ✅ (200) |
| **Arbeitnow** | Free | **none** | **Europe-focused** — weak for US | not documented | not clearly stated | — |
| **DOL OFLC / H-1B LCA disclosure** | Free bulk XLSX | none | employer-reported wages, heavily software; permanent roles | **real employer-declared wages** by SOC + worksite | public domain | quarterly files |
| **USAJOBS Search API** | Free | free key (email registration) | federal only; not the target market | salary ranges always present | US Gov | not re-verified (site timed out) |
| **TheirStack** (already wired, `research/sources/theirstack.py`) | **Paid — 1 credit per job returned** | `THEIRSTACK_KEY` | good agency/contract coverage | varies | commercial licence | key-gated |

### The finding that matters most: GSA CALC+

`GET https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/?search=labor_category:Software+Engineer&page=1&page_size=200`
— **no API key, no account, no rate limit published.** Live results, 2026-07-21 (index
`ceilingrates-2026-07-21_02-00-02`, refreshed nightly):

| Labor category | n | min | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| Software Engineer | 296 | $30.86 | $97.74 | **$113.53** | $124.98 | $144.84 |
| Software Developer | 148 | $50.80 | $100.59 | **$121.04** | $146.94 | $279.56 |
| Full Stack Developer | 20 | $73.30 | $92.51 | **$124.13** | $133.73 | $173.03 |
| Web Developer | 177 | $68.56 | $94.70 | **$111.12** | $137.38 | $235.50 |

Each row carries `labor_category`, `current_price` (hourly), `min_years_experience`,
`education_level`, `worksite`, `security_clearance`, `vendor_name`, `idv_piid`, `schedule`,
`business_size`, and forward-year prices — so it supports "rate by seniority" and "rate by
on-site vs contractor-facility" cuts natively via `filter=min_years_experience:N`,
`filter=education_level:BA`, `filter=worksite:Contractor`.

**Essential caveat, and it must be printed next to any number derived from it:** these are *ceiling
bill rates on GSA schedule contracts* — what the federal government may be charged by a vendor — not
what a contractor is paid. Commercial staffing markups typically put the pay rate well below the
bill rate, so CALC+ medians are an **upper bound on billable rate**, not a take-home expectation.
They are still the only free, current, US, hourly, contract-specific figures found. Also note the
free-text `q=` parameter matches loosely (a `q=software engineer` query returned a "Medical Coding
Auditor"); use `search=labor_category:<phrase>` and filter client-side.

### BLS OEWS as the wage baseline

The v1 API needs **no registration** — verified live, 25 queries/day, 25 series/query, 10 years/query;
v2 requires a free key and raises it to 500/day, 50 series/query, 20 years
([bls.gov/developers/api_faqs.htm](https://www.bls.gov/developers/api_faqs.htm)). A keyless POST to
`https://api.bls.gov/publicAPI/v1/timeseries/data/` for SOC 15-1252 (Software Developers), national,
returned `2025 A01 = 148100` (annual mean wage) — i.e. **current OEWS data, free, no account**. This
is the right anchor for "is this posting's number normal", and it is available per-MSA, which matters
for Ben's Texas/Oklahoma drivable-market question.

### Notes on the rest

- **Himalayas** is the strongest keyless *posting* source: real volume, `employmentType`,
  `locationRestrictions`, `seniority`, `minSalary`/`maxSalary`/`salaryPeriod`/`currency`, full
  `description`. But its contract supply is negligible (1 of 94 in a US SWE sample) and salaries are
  annual — good for perm-market shape, near-useless for contract rates. Attribution required:
  "link back to the URL found on Himalayas AND mention Himalayas as the original source"
  ([himalayas.app/api](https://himalayas.app/api)).
- **Remotive** is small but is the only keyless source seen returning **hourly** rate strings
  (`"$90 - $150 /hour"`, `"$120 - $170 /hour"`) on genuinely contract/freelance roles. The field is
  unparsed free text, so it needs a regex/LLM extraction step — which is a hint about the general
  technique: **the honest source of contract rates is the rate string in the JD body**, and that is
  something this repo's Claude-scoring step is already well placed to extract.
- **Greenhouse / Lever** are free and keyless but per-company: they answer "who is hiring and at what
  posted range" only if you first decide *which* companies. Useful for a curated watchlist, not for a
  broad market sweep. Greenhouse's `?pay_transparency=true` returns structured `min_cents`/`max_cents`
  ([developers.greenhouse.io/job-board.html](https://developers.greenhouse.io/job-board.html)).
- **Arbeitnow** is keyless but explicitly "the latest jobs in **Europe**" — wrong market, skip.
- **DOL H-1B LCA disclosure data** is the highest-integrity free US wage dataset that exists (actual
  employer-declared wages, by SOC code and worksite, public domain) but it is quarterly bulk XLSX,
  permanent-role-only, and lags. Worth a background "wage baseline" refresh job, not a live query.

---

## 4. The zero-key path

**Yes — a credible zero-key market-research output exists.** It is not a consolation prize; on the
one dimension the map cares most about (US contract *rates*) it is *better* than the keyed path,
because Adzuna's salary numbers are synthetic and JSearch's are 90% absent.

Proposed default, requiring **no third-party key of any kind**:

| Report section | Zero-key source | Quality |
|---|---|---|
| Contract hourly rate band by role + seniority | **GSA CALC+** (`min_years_experience` cuts) | real, current, hourly — but *bill-rate ceiling*, must be labelled |
| Perm salary baseline, national + by metro | **BLS OEWS v1** (SOC 15-1252 etc.) | authoritative, public domain, ~annual cadence |
| Live remote posting supply, gating stacks, who's hiring | **Himalayas** + **Remotive** | real postings, full descriptions, no key |
| Posted-range distribution for named target companies | **Greenhouse/Lever** board APIs, curated tokens | exact, employer-stated |
| Rate strings actually seen in JDs | regex/LLM extraction over the above descriptions + **the user's own scored corpus** | the only honest contract-rate evidence in the whole survey |

The last row is the thin-over-own-corpus option the ticket asks about, and it should ship regardless.
The `triage/` pipeline already scrapes and scores full JDs; those `state-*.json` files are a
first-party corpus with no ToS attached to it at all. A "what has my own market looked like over the
last 90 days" report — rate strings seen, stacks demanded, remote vs onsite mix, agencies vs direct —
costs nothing, needs no key, and is arguably *more* decision-relevant to Ben than a national average.
It is also the only market view that survives every ToS in §2 untouched.

**So the module should not be gated behind "add a key to unlock."** The correct shape is:

- **Tier 0 (default, no key):** own-corpus retrospective + BLS baseline + CALC+ rate bands +
  Himalayas/Remotive live supply. A complete, useful report.
- **Tier 1 (opt-in key):** Adzuna adds vacancy-count and salary-distribution breadth via `/histogram`
  and `/top_companies`; JSearch adds Google-for-Jobs reach and full JD text on high-value queries.
  Both **degrade silently to Tier 0** — which is exactly what `adzuna.py:19-21` and `jsearch.py:27-29`
  already do today.

That satisfies standing rule 1 as written, and it satisfies rule 3 (contain scope), because Tier 0 is
built from four unauthenticated GETs and data the repo already has.

---

## 5. Key handling for an OSS repo

**The repo already implements the conventional pattern correctly.** `.env.example` (committed,
placeholder values, one commented line per provider explaining cost and where to register) +
`.env` (gitignored) + `python-dotenv` loading in one place per package. `.gitignore` already has `.env`, `.env.*`, `!.env.example`,
`.secrets/`, `data/`, `.state/`.

The reference articulation of why is the twelve-factor "Config" factor
([12factor.net/config](https://12factor.net/config)):

> The twelve-factor app stores config in environment variables […] A litmus test for whether an app
> has all config correctly factored out of the code is whether the codebase could be made open source
> at any moment, without compromising any credentials.

and on the intermediate approach this repo uses:

> [config files not in revision control] is a huge improvement over using constants which are checked
> into the code repo, but still has weaknesses: it's easy to mistakenly check in a config file to the
> repo […]

Recommendations, in priority order:

1. **Keep `.env` + `.env.example`; do not move to committed config.** `config.yaml` is the right home
   for *tuning* (search terms, source toggles, rubric) and must stay free of secrets — it currently is.
   The existing split (secrets in env, behaviour in YAML) is the correct seam and needs no change.
2. **Every optional provider must fail soft, and say so.** The existing `if not key: log; return []`
   guard is the pattern; make it a documented contract for new sources, and have the report print a
   line like `Adzuna: skipped (no ADZUNA_APP_ID)` so a stranger understands *why* a section is thin
   rather than assuming breakage.
3. **The agent-assisted setup flow should write `.env`, never `settings.json` or `config.yaml`.**
   Claude Code's own guidance is that project-level `.claude/settings.json` is shared/committed
   config and must not hold secrets; personal values belong in `.claude/settings.local.json` or the
   environment. An `/setup-keys` command should: read `.env.example`, ask which optional providers the
   user wants, link the registration page for each, append to `.env` (creating it from the example if
   absent), and confirm `.env` is gitignored — and it should never echo a key value back into the
   transcript.
4. **Do not adopt OS keychain storage** (`keyring`, macOS Keychain) for v1. It is a real option and
   the `keyring` package abstracts Keychain/Credential Locker/GNOME
   ([keyring.readthedocs.io](https://keyring.readthedocs.io/en/stable/)), but it adds a dependency, a
   platform-specific failure surface, and a second place a key can live — for keys whose worst-case
   compromise is 200 free job-search requests a month. Env vars are proportionate. Revisit only if
   the repo ever handles something with billing exposure.
5. **Add a secret-scanning safety net** rather than relying on discipline — a `gitleaks`/`detect-secrets`
   pre-commit hook, plus GitHub push protection on the public repo. This is cheap and it is the one
   thing that catches the failure mode 12-factor warns about.
6. **Never ship a key, never proxy one.** Explicitly forbidden by Adzuna's "multiple accounts for a
   single entity" clause, and it is what would turn a personal-use tool into a service.

---

## Recommendation

**Build against two, in this order:**

1. **GSA CALC+ (CEILINGRATES)** — the primary new integration. Free, keyless, current, US-specific,
   and the only source in this survey that answers the highest-value question (contract hourly rate
   by role and years of experience) with observed rather than modelled data. It single-handedly makes
   the zero-key tier real. Pair it with **BLS OEWS v1** (also keyless) for the permanent-salary
   baseline; together they are ~two HTTP calls and no accounts.
2. **Adzuna, retained but repurposed** — keep the existing key-gated integration, and shift its role
   from *listing supply* to *aggregate market shape* via `/histogram`, `/top_companies` and vacancy
   counts, which is what its data is actually good for. Stop treating `salary_min`/`salary_max` from
   `/search` as observed salary; read `salary_is_predicted` and label accordingly. Add the required
   Jobsworth attribution.

**Keep but demote JSearch.** It stays valuable for full JD text and Google-for-Jobs reach, but 200
requests/month cannot support a broad market sweep, its ToS is the most restrictive found, and it sits
on a marketplace with a distressed corporate history. Reserve its quota for high-value targeted
queries, keep the `every_days` throttle, and make sure the module is fully useful when
`RAPIDAPI_KEY` is unset.

**Add Himalayas and Remotive as keyless posting sources** for live remote supply and — in Remotive's
case — the only keyless hourly rate strings found. Both need an attribution line.

**Skip Arbeitnow** (Europe). **Leave TheirStack key-gated and off by default** (paid per job returned).

---

## Sources

- [Adzuna API Terms of Service](https://developer.adzuna.com/docs/terms_of_service)
- [Adzuna API Overview](https://developer.adzuna.com/overview) · [Search ads](https://developer.adzuna.com/docs/search) · [Histogram data](https://developer.adzuna.com/docs/histogram) · [Signup](https://developer.adzuna.com/signup)
- [TechCrunch — Adzuna Jobsworth salary prediction (2013)](https://techcrunch.com/2013/07/24/pay-day)
- [JSearch on RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) · [OpenWeb Ninja — JSearch plans & docs](https://www.openwebninja.com/api/jsearch) · [OpenWeb Ninja Terms (Whats Next Labs LLC, 2025-10-17)](https://www.openwebninja.com/terms)
- [RapidAPI Terms](https://rapidapi.com/terms) → [rapidapi.com/page/terms](https://rapidapi.com/page/terms) · [TechCrunch — RapidAPI layoffs (2023)](https://techcrunch.com/2023/05/05/rapidapi-headcount-down-82-from-fresh-layoffs-less-than-two-weeks-after-cutting-50-of-staff/)
- [GSA CALC+ Quick Rate API (open.gsa.gov)](https://open.gsa.gov/api/dx-calc-api/) · [buy.gsa.gov/pricing](https://buy.gsa.gov/pricing/qr/know-more)
- [BLS Developers](https://www.bls.gov/developers/) · [API FAQs (v1 vs v2 limits)](https://www.bls.gov/developers/api_faqs.htm) · [API Signatures v2](https://www.bls.gov/developers/api_signature_v2.htm)
- [DOL OFLC Performance & Disclosure Data](https://www.dol.gov/agencies/eta/foreign-labor/performance)
- [Himalayas Remote Jobs API](https://himalayas.app/api) · [Arbeitnow Job Board API](https://www.arbeitnow.com/blog/job-board-api) · [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)
- [The Twelve-Factor App — Config](https://12factor.net/config) · [python keyring documentation](https://keyring.readthedocs.io/en/stable/)
- Live API probes run 2026-07-21 against `api.adzuna.com`, `jsearch.p.rapidapi.com`,
  `api.gsa.gov/acquisition/calc/v3`, `api.bls.gov/publicAPI/v1`, `himalayas.app/jobs/api`,
  `remotive.com/api/remote-jobs`, `boards-api.greenhouse.io`, `api.lever.co`.
