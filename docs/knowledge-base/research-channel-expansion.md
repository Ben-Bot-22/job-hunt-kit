# Should the triage funnel add new job sources?

Investigated 2026-07-29, prompted by `docs/knowledge-base/personal/` → the "sources wip" list of thirteen candidate
job boards. Every "live" claim below was verified by an actual HTTP call on that date.

**Verdict: add nothing. The funnel is not the constraint.**

---

## TL;DR

- **The bottleneck is applications, not leads.** The 2026-07-28 apply doc shows **7 applied, 15
  ranked-but-unapplied** — several of them verified 🟢 LIVE. Adding supply to a funnel with unworked
  surplus at the bottom does nothing for speed to a signed role.
- **The agency scrapers are healthy** — ~**1,352 postings**, zero errors, Apex at **492**. There was
  nothing to fix, and `core/scrapers/__init__.py` already said so; see §2 for the reading error that
  put a scraper audit on this list in the first place.
- **Eleven of thirteen candidate sources are unusable**: login-walled, bot-walled, wrong lane, or too
  thin to pay for themselves. Measured individually below.
- **HN "Who is Hiring" is real but small** — ~47 in-lane remote-US posts/month, 90% novel, but 66%
  permanent, 17% with a posted salary, 36% startups. ~1% supply increase. Not worth code.
- **A board watchlist is the wrong shape for a wide net.** `channels.boards` only ever sees companies
  named in advance, so it cannot "capture everything" by construction.

---

## 1. Where the leads actually come from

`source_platform` counts, from `data/corpus/state-*.json`:

| | 7/23 | 7/24 | 7/27 | 7/28 |
|---|---|---|---|---|
| email alerts (Dice/LinkedIn) | 133 | 22 | 117 | — |
| linkedin | 23 | 19 | 72 | 31 |
| agencies | 13 | 13 | 67 | 19 |
| remotevibecodingjobs | 32 | — | — | — |
| **boards** | **0** | **0** | **0** | **0** |

Across every worklist written: 691 LinkedIn links, 397 remotevibecodingjobs, 46 Dice. **Email is the
dominant channel** and the widest existing lever — a new saved search costs no code.

`channels.boards` is enabled with `greenhouse: []` and `lever: []`, so it has never contributed a job.

## 2. Agency scraper health — nothing was wrong, including the docs

Measured live 2026-07-29 by calling each scraper in `core/scrapers/AGENCIES` directly. Zero errors.

| scraper | raw scrape 2026-07-29 |
|---|---|
| apex | 492 |
| insightglobal | 465 |
| motion | 277 |
| teksystems | 83 |
| scion | 13 |
| mondo | 16 |
| kore1 | 6 |
| | **~1,352** |

**A scraper audit was on this review's list for two days on the strength of a line nobody should have
trusted.** AGENTS.md summarised the 2026-07-22 counts as "**Apex 3, KORE1 2** — either small boards or
already partly rotted", and that gloss outlived its own correction: `core/scrapers/__init__.py` records
that Apex *was* real rot and was **fixed on 2026-07-24** (`?page=N` needed a session cookie the scraper
never sent), that KORE1's 6-of-64 is the title filter working on a mostly non-software board, and that
raw counts and in-window counts are different numbers — only the raw one says anything about health.

Two lessons, and the second is the general one:

1. **`core/scrapers/__init__.py` is the authoritative account of scraper health.** AGENTS.md now points
   at it rather than restating it.
2. **Read to the end of the primary source before reporting a conclusion.** This review reversed twice
   — first proposing an audit off the stale gloss, then reporting the docs as wrong when the docstring
   had been right all along. Both reversals came from stopping at the first file that mentioned the
   thing.

## 3. The thirteen candidates, measured

| source | machine-readable | measured content | verdict |
|---|---|---|---|
| HN "Who is Hiring" | ✅ free Algolia API | 276 posts → 149 remote → **47 remote+US+in-lane** | see §4 |
| Greenhouse / Lever | ✅ keyless, JD + pay in one call | already coded, list empty | see §5 |
| aijobs.net (ex ai-jobs.net) | ❌ scrape, no feed | data-eng / MLOps / PhD / heavy non-US | wrong lane |
| Remotive | ✅ API (already in `research/sources/`) | **35** software-dev → 16 US → **2** in-lane | too thin |
| Himalayas | ✅ API (already in `research/sources/`) | 20/page, ~1 in-lane/page | cost/yield |
| a16z portfolio jobs | ❌ Consider.co, no public API | — | skip |
| YC workatastartup | ❌ 406, login wall | — | skip |
| Wellfound | ❌ 403 bot wall | — | skip |
| startup.jobs | ❌ Cloudflare 403 | — | skip |
| topstartups.io / trueup.io | ❌ JS-rendered | — | skip |
| vibecoding.work | sitemap only | real AI-native listings | likely same pool as RVCJ |
| vibehackers.io | ❌ empty HTML shell | — | skip |
| Gun.io | ❌ matcher, no public board | remote long-term contract only | see §6 |

YC and a16z being both slow *and* login-walled confirms the "demote the startup route" call already
recorded in the sources list — they would be manual browsing forever.

## 4. HN "Who is Hiring" — real, novel, and still not worth code

The July 2026 thread, parsed via `hn.algolia.com/api/v1/items/`:

- **47** posts are remote + US + in-lane
- **90% novel** — only 19 of 198 HN companies appear in the 998-company corpus. (The 19 that *did*
  arrive came via remotevibecodingjobs: Grafana Labs, We The Flywheel, Credo Health.)
- **66% full-time perm**, only **11%** mention contract → not the PRIMARY tier
- **17%** post a salary → the rubric's undisclosed-rate rule caps these at FIT
- **36%** carry startup signals (seed / Series A / YC / founding) → already demoted
- **4%** have a 7+ year bar → genuinely friendlier than the LinkedIn funnel

Realistic yield ~10 usable roles **per month**, against a funnel producing ~20 ranked roles per run,
4–5 runs a week. **≈1% supply increase.** Free to skim by hand on the 1st of the month; not worth a
channel, a monthly command, or the maintenance.

## 5. Why a board watchlist was rejected

`channels.boards` works — verified live: Anthropic 411 postings, Grafana Labs 136 (46 in-lane),
Backblaze 38, Luxury Presence 21. Jobs arrive with JD and pay range attached, verifiable at the
employer. Two reasons it still loses:

1. **A watchlist is structurally narrow.** It only ever returns companies named in advance, so it
   cannot serve the stated goal ("capture everything"). It is the opposite of a wide net.
2. **Seeding it from the corpus does not work.** Of 169 companies scoring 70+, the top is almost
   entirely staffing vendors (Mondo, Genesis10, Kforce, Themesoft, Pyramid) — agencies do not run
   Greenhouse/Lever boards, and `channels.agencies` already covers them. Token-testing the plausible
   direct employers yielded **6 live boards out of 16**.

A hand-picked AI-native list was drafted (18 live boards, 423 in-lane US roles) and **rejected on
fit**: Anthropic, Figma, Datadog, Affirm et al. carry staff-level bars and enterprise-tenure
expectations that the rubric downranks hard. It was volume, not fit.

## 6. Gun.io

A matcher, not a source: profile → internal vetting → client match. **It adds zero rows to the
pipeline** and therefore cannot be a channel. In its favour: remote long-term *contract* only, devs
keep 100% of their set rate, portfolio-based vetting rather than a code test. Against it: the same
opaque-queue shape as Toptal (skipped) and Braintrust (dropped 2026-07-27), where agencies won on
speed. Standing advice: finish the existing Gun.io thread rather than starting new marketplace
signups; if it goes quiet, that answers the category.

## 7. What was decided

**Do:**
- Nothing to the channels. The funnel is healthy and has unworked surplus.
- Correct the stale per-source counts in `core/scrapers/__init__.py`.
- Optionally skim the HN thread by hand on the 1st of the month. ~15 minutes.

**Do not:**
- Add a boards watchlist — wrong shape for a wide net, and the corpus cannot seed it.
- Add HN as a channel or a monthly command — ~1% supply for permanent maintenance.
- Add aijobs.net, Remotive, Himalayas, a16z, YC, Wellfound, startup.jobs, topstartups, trueup,
  vibehackers, vibecoding.work, or Gun.io.
- Keep remotevibecodingjobs, but always ⚪ unverified — it still surfaced Genesis10 (fit 90), and it
  still serves 200s on dead reqs.

**The generalisable finding:** every source evaluated here widens *supply*. None widens *conversion*,
which is where the search is actually constrained. Re-open this review only if a run comes back thin —
not on the intuition that more sources must be better.
