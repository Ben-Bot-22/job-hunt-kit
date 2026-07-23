"""The command line the `/research-company` skill drives.

One shape — targets are always positional, and the two other jobs are flags on the same parser:

    python -m research "TEKsystems"                    a brief, cached, printed as markdown
    python -m research https://jobs.example.com/123    same, starting from a link
    python -m research "Acme" "TEKsystems" "Genesis10" the top picks after a triage run, in one go

    python -m research --tool list_jobs "TEKsystems"   one tool, on its own — for an agent that
    python -m research --tool read_page <url>          wants to choose the next lookup itself
    python -m research --tool check_history "Acme"     instead of taking the default order

    python -m research --answer "TEKsystems" < answers.md   fold answers into the cached brief

Flags rather than subcommand verbs, deliberately (see `docs/operating/research-company.md`): a
company is a free-text string, so a bare verb in the first position is ambiguous with a company
literally named "tool", and verbs parsed off `argv` ahead of argparse silently ignore `--cache-dir`.

Everything here runs with no API key: the three tools are HTTP and local files. A key upgrades the
*planner* (see `agent.choose_model`); it is never required to get a brief. That is what makes this
the one thing in the repo that works on a fresh clone (spec, user stories 16–18).

Markdown goes to stdout and status lines go to stderr, so `python -m research X > brief.md` is a
brief and not a log.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import boards, cache, history
from .agent import research_company


def _brief_for(target: str, *, jd: str, refresh: bool, max_age: int, cache_dir: Path) -> str:
    """One target -> markdown, through the cache. The freshness rule lives here and nowhere else."""
    if not refresh:
        hit = cache.load(target, max_age_days=max_age, cache_dir=cache_dir)
        if hit:
            age = "today" if hit.age_days == 0 else f"{hit.age_days}d old"
            print(f"· {target}: cached {hit.researched} ({age}) — {hit.path}", file=sys.stderr)
            return hit.brief.markdown

    brief = research_company(target, jd=jd)
    path = cache.save(brief, target=target, cache_dir=cache_dir)
    print(f"· {target}: researched, {len(brief.open_questions)} open question(s) — {path}",
          file=sys.stderr)
    return brief.markdown


TOOLS = ("list_jobs", "read_page", "check_history")


def _run_tool(action: str, argument: str) -> int:
    """One tool, printed as plain text. The escape hatch for an agent that wants to plan for itself."""
    if action == "list_jobs":
        result = boards.list_company_jobs(argument)
        if not result.ok:
            print(result.detail)
            return 1
        print(f"{result.source} board: {result.url}")
        for posting in result.postings:
            print(f"- {posting.title}" + (f" — {posting.location}" if posting.location else ""))
        if not result.postings and result.text:
            print(result.text[:4000])
    elif action == "read_page":
        text = boards.read_page(argument)
        if not text:
            print(f"⚠ couldn't read {argument}")
            return 1
        print(text[:8000])
    elif action == "check_history":
        found = history.check_my_history(argument)
        if found.detail:   # empty when the record answered cleanly and had something to say
            print(found.detail)
        for applied in found.applied:
            print(f"- applied {applied.date}: {applied.company} — {applied.title} {applied.note}")
        for skipped in found.skipped:
            print(f"- skiplisted {skipped.job_id} — {skipped.reason}")
        for scored in found.scored:
            print(f"- scored {scored.fit_score} ({scored.verdict}) — {scored.title}, "
                  f"last seen {scored.last_seen}")
        for same in found.same_jd:
            print(f"- ⚠ same JD under {same.company} — {same.title} (overlap {same.overlap:.2f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m research",
        description="Pre-apply company research: who they are, what's open, your history with them.")
    parser.add_argument("targets", nargs="+", help="company names and/or job URLs")
    parser.add_argument("--jd-file", type=Path, default=None,
                        help="the JD you're looking at — lets the corpus be checked for the same req "
                             "under another company name (single target only)")
    parser.add_argument("--refresh", action="store_true", help="ignore any cached brief")
    parser.add_argument("--max-age", type=int, default=cache.MAX_AGE_DAYS, metavar="DAYS",
                        help=f"serve a cached brief up to this old (default {cache.MAX_AGE_DAYS})")
    parser.add_argument("--cache-dir", type=Path, default=cache.CACHE_DIR)
    parser.add_argument("--tool", choices=TOOLS, default=None,
                        help="run one tool against the first target and print it, instead of "
                             "producing a brief — for an agent choosing its own lookups")
    parser.add_argument("--answer", action="store_true",
                        help="read answers to the open questions on stdin and fold them into the "
                             "cached brief for the first target")
    args = parser.parse_args(argv)
    target = args.targets[0]

    if args.tool:
        return _run_tool(args.tool, target)

    if args.answer:
        try:
            path = cache.append_answers(target, sys.stdin.read(), cache_dir=args.cache_dir)
        except FileNotFoundError:
            print(f"no cached brief for {target} — run `python -m research \"{target}\"` first",
                  file=sys.stderr)
            return 1
        print(f"· answers written to {path}", file=sys.stderr)
        return 0

    jd = args.jd_file.read_text() if args.jd_file else ""
    if jd and len(args.targets) > 1:
        print("--jd-file applies to one target; ignoring it for the rest", file=sys.stderr)

    for i, target in enumerate(args.targets):
        if i:
            print("\n---\n")
        print(_brief_for(target, jd=jd if i == 0 else "", refresh=args.refresh,
                         max_age=args.max_age, cache_dir=args.cache_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
