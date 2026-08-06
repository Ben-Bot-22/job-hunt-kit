# triage — the daily job-triage pipeline

A leaf package: it may import `core/`, never another leaf (`core/test_layering.py` enforces it).

It pulls postings from whichever channels are enabled, fetches the full job description behind each
link, scores it against `profile/rubric.md` with Opus, and writes a **ranked markdown worklist** — top
picks first, then everything else with a one-line reason, fit / role / red flags / résumé keywords.

**The operator's guide is [`../docs/operating/triage.md`](../docs/operating/triage.md)** — the run, the
channels, tuning, archiving, dedup, Tier-2 and the gotchas. It is the reference; this page is the
package's front door and does not repeat it. Design rationale is in
[`../docs/knowledge-base/plan-triage-build.md`](../docs/knowledge-base/plan-triage-build.md).

## Run it

Through a coding agent — **`/job-triage`** — because two steps are the agent's tools rather than the
script's: Tier-2 browser retrieval of bot-walled JDs, and moving processed mail out of the inbox.

```bash
python -m triage                 # Phase 1 → worklist + state + browser queue
python -m triage --merge         # Phase 3 → re-rank with the browser-fetched JDs
python -m triage --paste <url>   # score one posting, nothing to configure
python -m triage --sample 5      # 5 representative whole emails, fully processed
```

Bare in a terminal it still works, but gives Tier 1 only — no walled JDs, no archiving.

## The modules

| | |
|---|---|
| `__main__.py` | three-phase orchestration |
| `channels/` | the job-input registry — one `fetch(days, sample) -> list[Job]` per source, each isolated so a broken channel costs that channel and not the run |
| `dedup.py` | collapses one req posted under two company names, before any paid call |
| `precedent.py` | injects the 3 most similar past decisions alongside the JD |
| `prefilter.py` | two cheap gates ahead of the expensive call |
| `preflight.py` | what is missing before a run, what it costs, the command that fixes it |
| `analyze.py` · `rank.py` · `worklist.py` | score, order, render |
| `store.py` · `applied.py` | the "already handled" set — `seen.json`, `skiplist.md`, `applied.json` |
| `config.py` | the accessors |

## Configuration

Three files, split by what changes them — **`../profile/rubric.md`** (the scoring anchor; the whole
file is the prompt, nothing parses it, so no edit to it can stop the tool loading), **`../profile/profile.yaml`**
(identity), **`../config/settings.yaml`** (operations). Secrets live in `../.env` and nowhere else.

`JOBSDB_CONFIG_HOME=<dir>` points both halves at one directory — `../config/example/` is a complete
one for a fictional seeker, so `JOBSDB_CONFIG_HOME=config/example python -m triage --paste <url>` is a
real run that touches nothing of yours.
