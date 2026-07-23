"""Briefs on disk — look TEKsystems up for the fifth time this month for free.

Agencies recur. The corpus has the same dozen names posting all month, and the pre-apply checks on
them come back the same: who they are, what their board looks like, what Ben's record with them says.
Paying three network lookups and a planner call for that every time is the waste this module removes.

Two rules, and the second is the one that matters:

    a brief inside the freshness window is served from disk;
    a brief outside it is **re-fetched**, never served stale.

`MAX_AGE_DAYS` is 14 because the volatile part of a brief is "what they have open" — a board moves in
weeks, an agency's identity doesn't. Three weeks would answer "still open?" from a world that no
longer exists (spec §Persistence, user story 14).

**Briefs cache as JSON and stop there.** They deliberately do not feed the retrieval index — cut in
the spec as speculative, and it would make stage 1 depend on stage 2 for no measured benefit.

The stored file is the whole brief, not a pointer to one: markdown, the employer verdict, and the
open questions. That is what lets an agent answer the open questions once (`append_answers`) and have
the *answered* brief be what the next lookup serves.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import boards, history
from .agent import Brief

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "research"

# Two weeks. See the module docstring — this is a judgement about how fast a board moves, not a knob.
MAX_AGE_DAYS = 14

_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass
class Cached:
    """A brief read back off disk. `age_days` is why the caller is being handed it (or isn't)."""
    brief: Brief
    path: Path
    researched: str
    age_days: int


def cache_key(name_or_url: str) -> str:
    """The filename stem for a target, computed *before* the research runs.

    A name keys through `history.company_key`, the same normaliser the history check matches on — so
    "TEKsystems" and "teksystems, inc." are one file, and a key here means what it means there. A URL
    keys on the company's own domain when it carries one; an aggregator link carries no company
    domain, so it keys on host+path — ugly, but stable, and honest about what was actually looked up.
    We never invent the employer's name here: resolving it is the loop's job, not the cache's.
    """
    target = (name_or_url or "").strip()
    if target.startswith(("http://", "https://")):
        domain = boards.company_domain(target)
        if domain:
            return _slugify(history.company_key(boards._name_from_domain(domain) or domain))
        parsed = urlparse(target)
        return _slugify(f"{parsed.netloc}{parsed.path}")[:80]
    return _slugify(history.company_key(target) or target)


def _slugify(text: str) -> str:
    return _SLUG.sub("-", (text or "").lower()).strip("-") or "unnamed"


def path_for(name_or_url: str, *, cache_dir: Path = CACHE_DIR) -> Path:
    return Path(cache_dir) / f"{cache_key(name_or_url)}.json"


def load(name_or_url: str, *, max_age_days: int = MAX_AGE_DAYS, cache_dir: Path = CACHE_DIR,
         today: date | None = None) -> Cached | None:
    """The cached brief when it is fresh enough to serve, `None` otherwise.

    `None` covers all four "go and look again" cases — never cached, stale, unreadable, or written by
    an older shape. A cache that half-answers is worse than one that misses. A dangling alias is one
    of those cases: it reads as a miss, not as an error.
    """
    path = _canonical(path_for(name_or_url, cache_dir=cache_dir))
    try:
        stored = json.loads(path.read_text())
        researched = str(stored["researched"])
        age = ((today or date.today()) - date.fromisoformat(researched)).days
    except Exception:  # noqa: BLE001 — missing, corrupt and old-shape all mean "look it up again"
        return None
    if age < 0 or age > max_age_days:
        return None
    return Cached(brief=_to_brief(stored), path=path, researched=researched, age_days=age)


def save(brief: Brief, *, target: str = "", cache_dir: Path = CACHE_DIR,
         today: date | None = None) -> Path:
    """Write the brief under the **resolved company**, and point the target at it. Returns the brief.

    The two keys differ exactly when the research resolved a name we didn't have going in — an
    aggregator link, which carries no company domain, turning out to be Genesis10. Writing the brief
    under the link alone would mean asking about "Genesis10" by name next week pays full price for an
    answer already on disk; writing a second copy under the name would mean two briefs ageing and
    getting answered independently. So: one brief, and a one-line alias file beside it.

    What no key can fix: a *different* job link at the same agency is still a miss, because who the
    employer is isn't known until after the lookups have run.
    """
    canonical = path_for(brief.company or target, cache_dir=cache_dir)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    researched = brief.researched or (today or date.today()).isoformat()
    canonical.write_text(json.dumps({
        "company": brief.company,
        "target": target or brief.company,
        "researched": researched,
        "employer": brief.employer,
        "employer_why": brief.employer_why,
        "open_questions": brief.open_questions,
        "markdown": brief.markdown,
    }, indent=2) + "\n")

    alias = path_for(target or brief.company, cache_dir=cache_dir)
    if alias != canonical:
        alias.write_text(json.dumps({"alias": canonical.stem, "target": target}, indent=2) + "\n")
    return canonical


def _canonical(path: Path) -> Path:
    """Follow an alias file to the brief it points at. **One hop only** — an alias is written pointing
    at a real brief, never at another alias, so a chain means the directory has been hand-edited and
    the honest answer is the miss that `load` will produce."""
    try:
        alias = json.loads(path.read_text()).get("alias")
    except Exception:  # noqa: BLE001 — not JSON, not there: `load` reports it as a miss either way
        return path
    return path.with_name(f"{alias}.json") if alias else path


_ANSWERS = "## Answered by the agent"


def append_answers(name_or_url: str, answers_markdown: str, *, cache_dir: Path = CACHE_DIR,
                   today: date | None = None) -> Path:
    """Fold an agent's answers back into the cached brief, under one heading.

    This is path 2 of the three documented ways to close the open questions (`agent.py` docstring):
    the agent driving the skill answers them with its own web search. Writing them back here is what
    makes that work paid once — the next lookup inside the window serves the *answered* brief.

    The section is headed and dated, because everything above it is deterministic output of the three
    tools and everything below it is a model's reading of a web search. A cached brief that blurs the
    two is a brief nobody can audit six weeks later.

    Raises `FileNotFoundError` if there is no cached brief to answer; there is nothing sensible to
    write answers onto.
    """
    path = _canonical(path_for(name_or_url, cache_dir=cache_dir))
    stored = json.loads(path.read_text())
    body = (answers_markdown or "").strip()
    if not body:
        return path
    markdown = stored.get("markdown", "")
    if _ANSWERS in markdown:
        markdown = markdown.split(_ANSWERS)[0].rstrip()  # replace, so re-running doesn't stack copies
    heading = f"{_ANSWERS} ({(today or date.today()).isoformat()}, from its own web search)"
    stored["markdown"] = f"{markdown.rstrip()}\n\n{heading}\n\n{body}\n"
    path.write_text(json.dumps(stored, indent=2) + "\n")
    return path


def _to_brief(stored: dict) -> Brief:
    """JSON -> Brief. `state` stays None: the lookups themselves are not replayable, and the brief
    text already records where they went ("Where I looked")."""
    return Brief(
        company=stored.get("company", ""),
        markdown=stored.get("markdown", ""),
        employer=stored.get("employer", "undetermined"),
        employer_why=stored.get("employer_why", ""),
        open_questions=list(stored.get("open_questions", [])),
        researched=str(stored.get("researched", "")),
        from_cache=True,
    )
