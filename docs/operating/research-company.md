# `/research-company` — how it's driven, and why it's shaped this way

The pre-apply checks: who these people are, what else they have open, and what your own record says
about them. The skill is `.claude/skills/research-company/SKILL.md`; the engine is `research/`,
driven as `python -m research`. This file is the decisions behind that shape — the runbook itself is
in the skill, and it is not repeated here.

## The CLI is one parser, with flags rather than verbs

```
python -m research "TEKsystems" "Genesis10"          brief(s), through the cache
python -m research --tool list_jobs "TEKsystems"     one tool, printed raw
python -m research --answer "TEKsystems" < ans.md    fold answers into the cached brief
```

Subcommand verbs (`research tool …`, `research answer …`) were the first shape and were replaced,
for two reasons:

1. **A company is free text.** The primary call has a bare company name in the first position, so a
   verb in that position is ambiguous with a company literally named "tool" — and the ambiguity
   resolves silently, against the user.
2. **Verbs parsed off `argv` ahead of argparse ignore the parser's own flags.** `--cache-dir` and
   `--max-age` applied to briefs and not to `--answer`, which is the kind of split that is only ever
   discovered by something going in the wrong directory.

The rejected alternative was argparse subparsers, which is the clean form of verbs — but it would
force `python -m research brief "TEKsystems"` on the common case to fix an uncommon one.

## Two keys, one brief

Briefs cache to `data/research/<company>.json`, keyed through `history.company_key`, so
`TEKsystems` / `teksystems, inc.` / `https://jobs.teksystems.com/…` are one file.

An **aggregator** link is the awkward case: it carries no company domain, so before the lookups run
there is no name to key on, and after they run there is. Handled with an alias — the brief is written
under the resolved company, and the link gets a one-line pointer file next to it:

```json
{ "alias": "genesis10", "target": "https://remotevibecodingjobs.com/jobs/123" }
```

So the link and the name both hit, and there is still only one brief to age and one brief to answer.
Rejected: writing the full JSON under both keys — two copies that age independently and get answered
independently is a cache that disagrees with itself.

**What this does not fix:** a *different* job link at the same agency is still a full re-research,
because who the employer is isn't known until after the lookups. That is accepted, not overlooked.

## Freshness

14 days. The volatile part of a brief is "what they have open" — a board moves in weeks, an agency's
identity doesn't. Past the window the brief is re-fetched, never served stale; `--refresh` forces it,
`--max-age` overrides it.

## Answers are the agent's, and are labelled as such

`--answer` appends under a dated `## Answered by the agent (<date>, from its own web search)`
heading, replacing any previous copy of that section. Everything above the heading is deterministic
output of the three tools; everything below it is a model reading a search. A cached brief that blurs
the two is one nobody can audit six weeks later.

## With no API key

`agent.choose_model` picks the real planner when `ANTHROPIC_API_KEY` is set and `keyless_plan` when
it isn't. Keyless runs the same three tools in a fixed order — read the link you were given, list the
board, check the local record — and raises one open question saying nothing pivoted. That notice is
attached to the **first** turn, not the last: a URL target spends the whole three-lookup budget on
the defaults, so the cap ends the loop before any `stop` of ours is reached.

An agent driving the skill can do better than the fixed order without a key at all: `--tool` exposes
each lookup on its own, so it can choose the next one from what it just read.
