# The market report — how it's run, and how it relates to your own market notes

What the market pays, and what your own inbox has actually been offering. The engine is
`research/retrospective.py` + `research/report.py`; the command is `python -m research.market`.

```
python -m research.market                 your corpus + the keyless external baselines
python -m research.market --offline       first-party only — no network at all, no key, no ToS
python -m research.market --supply        also pull the third-party job feeds (minutes, not seconds)
python -m research.market --print         the markdown to stdout as well, for piping
```

Two files come out, both under `data/reports/`, both dated:

| file | owner | what it is |
|---|---|---|
| `market-numbers-<date>.json` | **the machine** | the numbers, flat and accumulating. What the next run's trend section reads, and what a narrative cites. |
| `market-report-<date>.md` | **the machine** | the rendered document — two halves, every section stamped with its sample size and window. |
| `docs/knowledge-base/personal/market/market-insights.md` | **you** | the judgment. **Nothing generated ever overwrites it.** |

## A separate command, not a flag on the daily run

Different cadence. The triage pipeline runs every weekday; this runs monthly, or before a
negotiation. Measured on the real 1,143-record corpus: **11.3 s first-party**, almost all of it
clustering 3,606 distinct red flags, and **~83 s with the external baselines**. Folding that into
`python -m triage` would make every morning slower and noisier for a document nobody reads daily —
and `research/test_market.py` asserts the pipeline does not import it, so a well-meant `--report`
flag fails a test rather than passing review.

Configuration is the `report:` block of `config/settings.yaml`, under the same validated schema as
everything else there — external on/off, the job feeds on/off, which BLS metro is anchored, and how
long the lists are. Flags are this run; the settings file is the standing choice.

## The external half is absent out loud, never silent

Part 2 renders in every case. With no network it says *External market data is UNAVAILABLE for this
run* and adds that the rate baselines need **no API key, only a network** — so a stranger learns both
what is missing and that it is free. With a network but a dead source, it names the source that
returned nothing. A shorter report that read as complete is the failure this shape exists to prevent:
a median over one inbox is not a market rate.

The same rule runs through the figures. A GSA CALC+ number carries **CEILING** on its own line as
well as the full caveat under the heading — measured on 2026-07-22, CALC+'s software-engineer median
was **$135.82/hr** against BLS's **$65.38/hr** for the same occupation, 2.08× apart, because one is a
fully burdened federal bill-rate ceiling and the other is a wage. Quoting the first as "what the job
pays" in a call is the specific damage this report exists to prevent.

## The citing convention — follow this rather than pasting numbers

`docs/knowledge-base/personal/market/market-insights.md` is **human/agent-authored narrative**. The ~90% of it that is
mechanically derivable is exactly the part that goes stale (it was 26 days out of date when this was
built); that part is now generated. The remaining 10% is judgment, and an LLM-written "what this
means" section is precisely where a confidently wrong rate claim would do real damage. So:

1. **Run the report first.** The numbers file is the source; do not recompute a figure by hand.
2. **Cite it, don't copy it.** A claim in the narrative names the file it came from:

   > Only 30% of read postings state a rate at all, and 22% of contract ones
   > (`data/reports/market-numbers-2026-07-22.json` · `rate_share_all_postings`,
   > `rate_share_contract`).

   The metric names are the keys in that file's `metrics` block, so a reader six weeks later can
   check the claim against the run it was drawn from rather than against today's.
3. **Never paste a table.** A pasted table is a copy that goes stale silently; a citation goes stale
   loudly, because the date is in the filename.
4. **Write only what the numbers do not say.** What to do about it, what a figure means for a
   specific negotiation, what changed in your own strategy. If a sentence is a restatement of a
   metric, delete it and cite instead.
5. **Nothing generated is written into that file, ever** — not by this command and not by an agent
   following it. `research/test_market.py` asserts the command writes only into `data/reports/`.

## Why there is no trend yet

Part 3 renders in both states, and today it refuses: *at least 3 snapshots, scored under the same
rubric, spanning at least 60 days.* Three points over two months is the smallest thing that can tell
a trend from a jump, and the rubric stamp is a hash of `profile/rubric.md` — a line drawn across a
rubric edit measures your prompt while reading as the market. Editing the rubric restarts the clock,
and the refusal says how many snapshots it set aside. The reasoning is in `research/snapshots.py`.

## Costs, and what is capped

Nothing here is scheduled, and the caps are why that matters:

* **CALC+** pages to exhaustion (~10 requests, ~10 s) because its results arrive price-ascending — a
  truncated pull would be a median of the cheapest rows presented as the median.
* **BLS** is one keyless POST of 16 series, hard-capped at 2 of the 25 queries an IP gets per day.
* **`--supply`** is the expensive one: Adzuna fetches a detail page per posting (~5 minutes) and
  Himalayas pages 50 times for ~100 developer rows. It buys per-source counts, not a distribution —
  those feeds are filtered and capped, so a distribution over them would read as market volume and
  would not be.
* **The six agency scrapers are rot-prone.** They parse live HTML and fail by returning zero rather
  than by raising; the per-source counts in Part 2 are the only detector.
