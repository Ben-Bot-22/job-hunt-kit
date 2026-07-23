# The `boards` channel — a watchlist for companies you already want

> How to point the tool at a set of company job boards, why that is a watchlist rather than a search,
> and how to find and verify a board token before you commit a run to it. Companion to the channel
> table in the README and to step 7 of `/setup`.

## What it is

`boards` reads **one company's job board at a time** and asks it what is new —
`boards-api.greenhouse.io/v1/boards/<token>/jobs` for Greenhouse, `api.lever.co/v0/postings/<token>`
for Lever. You give it a list of board tokens; it hands back every posting on each of those boards
inside the freshness window. It is keyless, works on any OS, needs no inbox and scrapes nothing, so
there is nothing to rot: a board that changes its HTML doesn't touch us, and a board that goes away
404s and costs you that one board.

**These are company identifiers, not search keywords — you cannot ask a board for "AI Engineer".**
The only input the endpoint accepts is a company token; there is no keyword parameter and no global
search. So the channel is a **watchlist for someone who already has target employers**, not an answer
to "I just cloned this, find me a job". It does not solve cold start; it moves it one step — from
"which jobs" to "which companies". If you don't yet know which companies you want, `paste` (any job
URL, no configuration) is the channel that meets you there.

## How role filtering actually works

The channel pulls a company's **whole board** — every open posting, not a filtered slice. The
narrowing happens afterward, downstream, the same as for every other channel: the prefilter drops the
obvious misses, the cheap screen cuts further, and then your `profile/rubric.md` scores what survives.
So the thing doing the filtering is **your rubric, not the query.** A board of 60 postings becomes a
worklist of the handful that fit you because the rubric read all 60, not because the board was asked a
narrow question. This is why a company with a broad board is fine to watch: you are not paying in noise
in the output, you are paying in model calls on the way there (see *Choosing companies* below).

## Finding a token from a URL

The token is the company slug in the board's URL. Most companies host their careers page at
`careers.<company>.com` and hand the real board off to Greenhouse or Lever behind the scenes — so open
a posting and look at where the **Apply** button goes. That destination URL carries the token:

    https://job-boards.greenhouse.io/anthropic/jobs/123     ->  greenhouse: anthropic
    https://boards.greenhouse.io/anthropic                  ->  greenhouse: anthropic
    https://jobs.lever.co/gopuff/abc-123                    ->  lever: gopuff

If the Apply button stays on `careers.<company>.com` with no visible Greenhouse or Lever URL, the
company is on a different ATS (Workday, Ashby, Lever's competitors) and this channel can't watch it.

## Verifying a token before you commit to it

A token you found in a URL might be stale, might be the parent company's board rather than the
division you want, or might simply have nothing open in the window. Check it with one keyless GET
before you add it to config:

```bash
.venv/bin/python -c "from triage.channels import boards; print(len(boards.fetch(7, boards={'greenhouse': ['anthropic']})))"
```

That reports how many postings the token returns in a 7-day window — one HTTP call, no OAuth, no key.
Swap `greenhouse` for `lever` and the token for the one you're checking. A token that does not exist
returns nothing and logs a warning; a bad token costs that board only, never the run. The counts drift
day to day — a board busy in July can be silent in December — so treat the number as "is this alive",
not as a forecast.

## Choosing companies — the cost model

Every posting that survives the cheap screen costs **one model call.** So a board is a volume dial: two
or three tokens is a sensible first run, and a high-volume board (a large product company that
republishes a wide board) can be a whole run on its own. Start narrow and add tokens once you've seen
what a run costs and produces, rather than seeding ten and paying for all of them on day one.

Name the shape of what arrives so you enable it for the right reason: **Greenhouse and Lever boards are
overwhelmingly permanent roles at product companies.** If you want contract work, this is the wrong
channel — that is `agencies`, which reads staffing firms' boards. Nobody should enable `boards`
expecting contract reqs to show up.

## A starter list, if you don't have one

If your honest answer is "I don't know, what have you got", `.claude/skills/setup/starter-boards.md` is
a list of live, keyless boards with posting counts measured on one day. **It is a starting point, not a
recommendation** — the whole value of this channel is that the list is *yours*, so the right first move
is still to name the companies you actually want and pull their tokens out of their careers URLs. The
starter list also notes that **Lever is the thin side**: most commonly-cited Lever tokens
(`netlify`, `brex`, `plaid`, `ramp`, `carta`) have gone dead, and the live boards are overwhelmingly on
Greenhouse.

## Configuration

The channel is configured under `channels.boards` in `config/settings.yaml`:

```yaml
channels:
  boards:
    enabled: true
    greenhouse: [anthropic, stripe]
    lever: [gopuff]
```

`enabled: true` with **empty lists** is a valid, deliberate state, not a misconfiguration: the channel
reports `boards 0` in the run summary and does nothing. That is why `boards` can ship on-by-default
without pulling anything for a user who hasn't chosen their companies yet — an empty watchlist is a
quiet channel, not a broken one. Fill the lists when you have tokens; until then `boards 0` is correct.
