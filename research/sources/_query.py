"""What the keyword-driven sources ask for, in one place.

Adzuna and JSearch bill (in requests, or in a free-tier quota) *per term*, so the list length is the
cost of a pull and both sources import the same one — two lists that drifted would mean the
contract-versus-permanent comparison was drawn over two different queries.

These are the six terms the frozen pipeline ran for a month; carried over verbatim so a market number
measured before this move and one measured after are comparable. The agency scrapers do not use them —
they take whatever their board has and filter on dev-ish URL slugs instead.
"""
from __future__ import annotations

TERMS: tuple[str, ...] = (
    "React developer",
    "full stack developer",
    "TypeScript developer",
    "Node developer",
    "software engineer",
    "frontend developer",
)
