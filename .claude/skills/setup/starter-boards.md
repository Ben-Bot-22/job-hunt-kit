# Starter board tokens

A `boards` watchlist the user can start from when they don't have one ready. Every token below was
checked against the live listing API on **2026-07-22**; the counts are what the channel actually
returned for that window on that day, not an estimate.

**These are a starting point, not a recommendation.** The channel is a watchlist — its value is that
it is *the user's* list. Ask for the companies they want to work for first, and pull the tokens out of
their careers-page URLs. Use this file for the person who says "I don't know, what have you got".

| ATS | token | 7 days | 30 days | who |
|---|---|---|---|---|
| greenhouse | `anthropic` | 18 | 113 | AI lab, remote-friendly, publishes pay ranges |
| greenhouse | `gitlab` | 27 | 102 | all-remote by construction |
| greenhouse | `cloudflare` | 18 | 95 | infrastructure, wide geography |
| greenhouse | `stripe` | 42 | 147 | high volume — one board is a whole run |
| greenhouse | `databricks` | 36 | 171 | data platform, high volume |
| greenhouse | `mongodb` | 45 | 114 | database, high volume |
| greenhouse | `elastic` | 42 | 109 | distributed company, search/observability |
| greenhouse | `reddit` | 14 | 68 | consumer product |
| greenhouse | `figma` | 11 | 38 | design tooling, front-end heavy |
| greenhouse | `vercel` | 11 | 23 | front-end platform, small board |
| greenhouse | `duolingo` | 2 | 19 | small board, slow — a good second token, not a first |
| lever | `gopuff` | 16 | 29 | the largest live Lever board found |
| lever | `binance` | 17 | 64 | crypto exchange, mostly non-US |
| lever | `swordhealth` | 1 | 2 | small board — included so the Lever path isn't a single point |

**Two or three tokens is a good first run.** Every posting in the window that survives the cheap
screen costs one Opus call, so `stripe` + `databricks` + `mongodb` is ~120 postings a week before the
screen has cut anything. Start narrow and add.

Lever is the thin side of this list on purpose: most Lever tokens that are commonly cited have gone
away (`netlify`, `brex`, `plaid`, `ramp`, `carta`, `matterport` all 404 or return nothing as of the
date above). Greenhouse is where the live boards are. `leverdemo` — the token in `config/example/` —
is Lever's own demo board: it returns hundreds of postings but they are old, so it usually reports 0
inside a 7-day window. It is there to exercise the code path, not to find anyone a job.

## Finding a token from a URL

    https://job-boards.greenhouse.io/anthropic/jobs/123    ->  greenhouse: anthropic
    https://boards.greenhouse.io/anthropic                 ->  greenhouse: anthropic
    https://jobs.lever.co/gopuff/abc-123                   ->  lever: gopuff

Many companies host their board at `careers.<company>.com` — open a posting and look at where the
**Apply** button goes; that URL usually carries the token.

## Checking a token before committing to it

Only after the user has chosen the `boards` channel — this makes a real request:

```bash
.venv/bin/python -c "from triage.channels import boards; print(len(boards.fetch(7, boards={'greenhouse': ['anthropic']})))"
```

Keyless, one GET, no OAuth. A token that doesn't exist returns nothing and logs a warning; a bad token
costs that board only, never the run. The counts above will drift — they are a snapshot of one
Wednesday, and a board that was busy in July can be silent in December.
