---
name: research-company
description: Pre-apply research on a company — agency or direct employer, what else is on their board, and your own history with them — from a company name, a job URL, or the top picks of a triage run. Use before applying to anything, or when asked to look a company or an agency up.
---

# Research a company before applying

The checks Ben otherwise does by hand in six browser tabs: **who are these people, what else have
they got open, and have I dealt with them before.** The engine is `research/` in this repo; you are
the part of it that has web search.

Runs on a fresh clone with nothing configured — no inbox, no corpus, no API key. Anything it can't
reach becomes an open question, and closing those is your job (step 3).

## 1. Work out what you were pointed at

| you were given | do this |
|---|---|
| a company name (`TEKsystems`, `Genesis10`) | that's the target |
| a job URL, or an email with one | pass the **URL** — resolving who the employer is is the loop's first job, not yours |
| a JD in a file | pass the company name plus `--jd-file <path>` — that's what finds the same req in the corpus under a *different* company name |
| "the top picks from this morning" | read the newest `matches/<date>.md`, take the companies of the top N (default 5, ask if unsure), pass them all in one call |

## 2. Run it

```bash
.venv/bin/python -m research "TEKsystems"                        # one company
.venv/bin/python -m research https://jobs.example.com/eng/123    # a link you already have
.venv/bin/python -m research "Acme" "TEKsystems" "Genesis10"     # the top picks, in one go
.venv/bin/python -m research "Acme" --jd-file data/runs/acme-jd.txt
```

The brief is markdown on stdout; the status line on stderr says whether it was researched or served
from cache. Useful flags: `--refresh` (ignore the cache), `--max-age DAYS` (default 14). On a clone
with nothing installed:
`pip install -r research/requirements.txt -r triage/requirements.txt`.

Briefs cache to `data/research/<company>.json`, so the fifth lookup of the same agency this month is
free. A brief older than the window is re-fetched, never served stale — the volatile part of a brief
is "what they have open".

**Choosing the lookups yourself.** The loop plans with an API key when there is one and falls back to
a fixed order when there isn't; the brief says which happened. Either way each tool is also available
on its own, so you can pivot on what you read:

```bash
.venv/bin/python -m research --tool list_jobs "TEKsystems"      # their whole board
.venv/bin/python -m research --tool read_page <url>             # one page as text
.venv/bin/python -m research --tool check_history "TEKsystems"  # applied / skiplist / scored corpus
```

The pivot worth knowing: **when a page reveals the poster is an agency shopping someone else's req,
the next question is `check_history`** — the same JD is often in the corpus under another name, which
is one req being shopped by three agencies.

## 3. Close the open questions — this step is not optional

Every brief ends in `## Open questions`. That list is the whole interface between the Python engine
and you. Answer what you can **with your own web search**, one short answer per question, and say
plainly when you couldn't answer one. Never fill a gap with a guess: a confidently wrong careers page
sends Ben at another company's listings, and "couldn't check" costs him one manual lookup.

Then write the answers back so the next lookup gets them for free:

```bash
.venv/bin/python -m research --answer "TEKsystems" <<'EOF'
- **Direct employer?** No — TEKsystems is an Allegis staffing firm; the client isn't named in the posting.
- **Rate?** Not stated anywhere public; ask on the first call.
- **How long has this req been up?** Couldn't establish — no dated copy found.
EOF
```

## 4. Report

Show Ben the brief itself (it is already readable markdown), with your answers folded in, and lead
with the one line that changes what he does:

- **agency, not the employer** — he isn't talking to the decision-maker;
- **already applied / on the skiplist** — don't cold-apply;
- **same JD under another company** — the same req, shopped twice;
- **one lonely backfill vs. a board with twelve openings**.

Don't restate the whole brief in prose, and don't recommend applying or not applying — this is a
pre-apply check, not a scoring pass.

## Notes

- **Portable on purpose.** Nothing here needs a particular agent: it is a CLI, plain markdown, and
  whatever web search you have. Read `docs/knowledge-base/research-cross-agent-portability.md` before changing that.
- Briefs cache as JSON and **do not** feed the retrieval index. That was cut deliberately.
- The loop is capped at three lookups. If the brief says it stopped at the cap, there may be more to
  find — say so rather than presenting it as complete.
