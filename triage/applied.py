"""Applied-jobs dedup cache (full reference: docs/operating/triage-applied-sync.md).

Ben logs every application in a Google Sheet — free-form and messy (company often blank; the title lands
in whichever column he pasted into; identity sometimes only inferable from the link domain). `/sync-applied`
reads that sheet, Claude normalizes each row in-session, and this module turns those normalized rows into
canonical block keys stored in `data/corpus/applied.json`. The ranker unions those keys into `blocked` so a job
Ben has already applied to never surfaces again.

Two keys per record — a candidate matches if EITHER hits:
  - composite key = composite_id(company, title, city)  — the SAME identity the ranker keys jobs on
  - url key       = 'url:' + normalized apply URL        — catches company/title normalization drift

Keys are computed HERE (via the ranker's own composite_id), never trusted from the caller, so an applied
row and the ranked job for the same posting always collapse to the same string.

Confidence gates silent dedup: `high`/`medium` auto-block; `low` is stored but NOT blocked — it's surfaced
for Ben's eyeball instead, because a false dedup (hiding a job he never applied to) is the costly error.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel

from .config import CORPUS_DIR
from core.models import composite_id, normalize_link as _normalize_link

log = logging.getLogger("triage.applied")

APPLIED = CORPUS_DIR / "applied.json"
AUTO_BLOCK = {"high", "medium"}   # confidences that silently dedup; "low" is held for review only


class AppliedRecord(BaseModel):
    row: int = 0                  # the sheet's 'No' column — a stable anchor across re-syncs
    apply_date: str = ""
    company: str = ""
    title: str = ""
    city: str = ""
    url: str = ""
    confidence: Literal["high", "medium", "low"] = "high"
    note: str = ""                # how company/title were inferred, or why it's low-confidence
    composite_key: str = ""       # derived
    url_key: str = ""             # derived

    def keys(self) -> set[str]:
        """Block keys this record contributes. Composite only when specific enough to not over-match
        (a real ranked job always has a title, so a title-less applied row would never collide anyway)."""
        out: set[str] = set()
        if self.title and (self.company or self.city):
            out.add(self.composite_key)
        if self.url_key:
            out.add(self.url_key)
        return out


def _build(row: dict) -> AppliedRecord:
    conf = str(row.get("confidence") or "high").lower()
    if conf not in ("high", "medium", "low"):
        conf = "low"                      # unknown → conservative: hold for review, don't auto-block
    rec = AppliedRecord(
        row=int(row.get("row", 0) or 0),
        apply_date=str(row.get("apply_date", "") or ""),
        company=str(row.get("company", "") or ""),
        title=str(row.get("title", "") or ""),
        city=str(row.get("city", "") or ""),
        url=str(row.get("url", "") or ""),
        confidence=conf,
        note=str(row.get("note", "") or ""),
    )
    rec.composite_key = composite_id(rec.company, rec.title, rec.city)
    rec.url_key = f"url:{_normalize_link(rec.url)}" if rec.url else ""
    return rec


def sync_from_rows(rows: list[dict]) -> dict:
    """Rebuild applied.json from Claude's normalized rows. The SHEET is the source of truth, so this fully
    REPLACES the cache each run (no stale rows survive an edit). Returns a summary for the caller to show."""
    records = [_build(r) for r in rows if any(r.get(k) for k in ("company", "title", "url"))]
    APPLIED.write_text(json.dumps([r.model_dump() for r in records], indent=2))
    return {
        "records": len(records),
        "block_keys": len({k for r in records if r.confidence in AUTO_BLOCK for k in r.keys()}),
        "auto_blocked": [{"row": r.row, "company": r.company, "title": r.title}
                         for r in records if r.confidence in AUTO_BLOCK],
        "held_for_review": [{"row": r.row, "company": r.company, "title": r.title,
                             "note": r.note or "low confidence"}
                            for r in records if r.confidence not in AUTO_BLOCK],
    }


def load_records() -> list[AppliedRecord]:
    try:
        return [AppliedRecord(**d) for d in json.loads(APPLIED.read_text())]
    except (OSError, ValueError):
        return []


def load_blocked() -> set[str]:
    """Keys the ranker unions into `blocked` — auto-block (high/medium) records only."""
    return {k for r in load_records() if r.confidence in AUTO_BLOCK for k in r.keys()}
