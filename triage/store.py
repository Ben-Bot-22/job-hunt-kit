"""Dedup state — three sources (triage-plan §5; applied-sync: docs/operating/triage.md).

  seen.json    : ids already analyzed (auto; don't re-analyze across runs — saves API + LinkedIn fetches).
  skiplist.md  : ids Ben applied to / rejected (hand-edited; never surface again).
  applied.json : jobs synced from Ben's applied Google Sheet (auto, via `/sync-applied`; see applied.py).

All three are checked BEFORE any fetch or analysis call. This module owns the first two; `applied.py` owns
the third (it carries richer per-record data + confidence gating), and `__main__` unions them together.
"""
from __future__ import annotations

import json

from . import config
from .config import SKIPLIST


def seen_path():
    """Resolved on every call, not bound at import.

    `SEEN = CORPUS_DIR / "seen.json"` at module scope froze the real corpus path into this module the
    moment it was imported, so a test redirecting `config.CORPUS_DIR` at a temp directory redirected
    the readers and not the writer. `triage/test_merge.py` did exactly that and wrote three fixture
    ids into the owner's live `data/corpus/seen.json` — and, on a fresh clone, created a `data/`
    directory that made `triage/test_paste.py` fail. The corpus is a month of accumulated judgments;
    nothing in the suite may be able to touch it by accident.
    """
    return config.CORPUS_DIR / "seen.json"


def load_seen() -> set[str]:
    try:
        return set(json.loads(seen_path().read_text()))
    except (OSError, ValueError):
        return set()


def save_seen(ids: set[str]) -> None:
    path = seen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(ids), indent=0))


def load_skiplist() -> set[str]:
    """Ids Ben has recorded. A real id line contains pipes (company|title|city); notes after '#' ignored."""
    ids: set[str] = set()
    if not SKIPLIST.exists():
        return ids
    for line in SKIPLIST.read_text().splitlines():
        candidate = line.split("#", 1)[0].strip()
        if "|" in candidate:  # only lines carrying a composite id
            ids.add(candidate)
    return ids
