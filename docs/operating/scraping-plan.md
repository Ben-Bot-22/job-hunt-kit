# Scraping & Agency-Source Plan (working notes)

> Messy-but-real working doc — context we discovered while planning per-agency monitoring.
> Clean up later. Source of decisions: a live probe script (deleted in stage 5 · 01 — see git
> history) + research agents, June 2026. The six scrapers this doc designed now live in
> `research/sources/` and are flagged **rot-prone** there: they fail by returning zero, not by
> raising, and `fetch_all`'s per-source counts are the only detector.

## Probe evidence (live, from a residential IP)

| Agency | endpoint | status | server | Cloudflare | JS challenge | access shape |
|---|---|---|---|---|---|---|
| Mondo | `mondo.gosnaphop.com/sitemap.xml` | 200 | nginx | no | no | XML sitemap index → sub-sitemaps |
| Insight Global | `jobs.insightglobal.com/find_a_job/{n}/?srch=…` | 200 | IIS | no | no | ~326KB HTML w/ embedded JSON (JobType, pay rate) |
| KORE1 | `search10.smartsearchonline.com/koreone/jobs/` | 200 | IIS | no | no | classic-ASP HTML; type only on detail page |
| Motion | `motionrecruitment.com/tech-jobs/contract` | 200 | **cloudflare** | yes | **no** | HTML w/ per-job JSON-LD; passed w/ browser UA |
| Apex | `apexsystems.com/search-results-usa` | 200 | **cloudflare** | yes | **no** | HTML; per-job JSON-LD; sitemap stale; passed w/ browser UA |
| TEKsystems | `POST careers.teksystems.com/widgets` | 200 | — | no | — | Phenom JSON API; `refineSearch.totalHits`=83, but payload needs tuning to return `jobs[]` |

## Cloudflare — what it means here

- Cloudflare fronts **Motion + Apex only**. The other 4 have none.
- It blocks "bot-looking" requests; the dominant tell is the **User-Agent**. Default
  `python-requests` UA → 403. A **real browser UA → 200 with real content, no challenge** (proven).
- It's **conditional, not a hard wall** — Cloudflare escalates by **IP reputation + request rate**.
  Our probe IP is residential (trusted). **GitHub Actions = shared datacenter IPs** that Cloudflare
  trusts less, so the same code may get a JS challenge on a runner. Unknown until the first real
  Actions run — must verify there.

## Per-agency access (preferred = structured, not HTML scraping)

- **Mondo** — poll SnapHop XML job sitemaps; diff for new/removed. Detail via light HTML parse
  (no JSON-LD). Small board (~100 jobs). No Cloudflare.
- **TEKsystems** — Phenom `POST /widgets` `refineSearch` JSON API (site code `TESYUS`), paginate
  `from`/`size`. Cross-check daily `sitemap1-4.xml` (410 = closed). **Payload needs tuning** (current
  one returns counts but 0 job objects).
- **Insight Global** — GET `find_a_job/{page}/?srch=…`, parse the embedded JSON array (rich:
  JobType, PayRate, ApplicantCount). No Cloudflare. Best per-agency completeness.
- **Motion** — per-job `schema.org/JobPosting` JSON-LD on each detail page; discover via
  `/tech-jobs/contract` pagination. Cloudflare present (passed w/ UA). Aggregator-by-employer is a
  fallback.
- **Apex** — scrape `search-results-usa` (browser UA) → per-job JSON-LD. Sitemap is dead (stale
  Oct 2024). Cloudflare present (passed w/ UA).
- **KORE1** — scrape SmartSearch portal; employment type only on `jobdetails.asp?jo_num=` detail
  pages, so must fetch detail per job. No Cloudflare. Weak aggregator coverage → scraping is the
  only complete route.

## Reliability options (for the 2 Cloudflare sites; the other 4 use plain requests)

- **A. requests + browser UA + rate-limit** — works today; cheapest; risk on Actions datacenter IP.
- **B. Playwright headless** — renders JS / simple challenges; heavier; still IP-beatable.
- **C. Paid scraping API** (ScrapingBee/ZenRows/Bright Data) for just the Cloudflare URLs — vendor
  handles Cloudflare + residential proxies; most robust; cheap at our volume.
- **D. TheirStack** — avoid scraping Apex/Insight/TEK if its coverage is good (measure first).
- **E. Local residential IP** — most trusted, but needs the Mac awake (ruled out).

## Recommended approach

1. **Structured-first in GitHub Actions** for the 4 clean sites + TEK (requests/JSON/sitemap).
2. **Motion + Apex:** start with **A + source-health alarm**; flip to **C** (scraping API) only if
   the first Actions run shows Cloudflare challenging us.
3. **TheirStack** as the non-scraped backstop for Apex/Insight/TEK (reduces fragile dependencies).
4. **Source-health monitoring (key to trust):** each source reports its job count; the digest
   flags any source that returns 0 when it normally returns N (parser broke / blocked) so failures
   are loud, not silent.
5. **Defensive parsing** everywhere; prefer JSON/JSON-LD/sitemap over CSS selectors.

## Open items / TODO

- [ ] Get Ben's **exact per-agency search URLs** (his preferred filters: contract + stack + metros).
- [ ] Tune the TEKsystems Phenom payload so `refineSearch.data.jobs[]` is populated.
- [ ] Decide reliability tier for Motion/Apex (A now + C fallback?  vs C upfront).
- [ ] First real Actions run: confirm whether the runner IP gets Cloudflare-challenged on Motion/Apex.
- [ ] Add `source` + `agency` + per-source counts to the digest.
- [ ] Clean up this doc once the approach is locked.
