"""Dedup state — three sources (triage-plan §5; applied-sync: docs/operating/triage-applied-sync.md).

  seen.json    : ids already analyzed (auto; don't re-analyze across runs — saves API + LinkedIn fetches).
  skiplist.md  : ids Ben applied to / rejected (hand-edited; never surface again).
  applied.json : jobs synced from Ben's applied Google Sheet (auto, via `/sync-applied`; see applied.py).

All three are checked BEFORE any fetch or analysis call. This module owns the first two; `applied.py` owns
the third (it carries richer per-record data + confidence gating), and `__main__` unions them together.
"""
from __future__ import annotations

import json

from .config import CORPUS_DIR, SKIPLIST

SEEN = CORPUS_DIR / "seen.json"


def load_seen() -> set[str]:
    try:
        return set(json.loads(SEEN.read_text()))
    except (OSError, ValueError):
        return set()


def save_seen(ids: set[str]) -> None:
    SEEN.write_text(json.dumps(sorted(ids), indent=0))


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
