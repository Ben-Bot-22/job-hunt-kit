"""Extract a posted pay rate (hourly-equivalent) from free-text job descriptions.

Source `rate` fields are often blank or an algorithmic *estimate* — a live 50-row Adzuna sample came
back 100% `salary_is_predicted` with min == max. The real number usually lives in the description
("$85.00 – $90.00 per hour", "$120,000 - $150,000 per year", "$150k"). This returns a clean
posted-rate string like "$85-90/hr", or None when none is stated.

It lives in `core/` because two different halves of stage 5 need the same answer: the retrospective
reads it over the user's own scraped JDs, and the external sources read it over rate strings a feed
hands back unparsed. Two copies would mean two different medians for the same corpus.

**The failure direction is asymmetric and the sanity window is what encodes it.** A missed rate costs
one row of a distribution. A *fabricated* rate — an address, an ID, a headcount read as money — walks
into a negotiation as a number the user believes came from a posting. So `_ok` refuses anything
outside $10–600/hr hourly-equivalent, and the lone-number last resort only fires on text that is
unambiguously money (comma-grouped thousands, or a `k` suffix).
"""
from __future__ import annotations

import re

_HOURLY = ("hour", "hr", "/hr")
_YEARLY = ("year", "/yr", "yr", "annual", "annum", "p.a")
_UNIT = r"(per\s*hour|/\s*hr|/\s*hour|hourly|an\s*hour|per\s*year|/\s*yr|/\s*year|yearly|annually|annum|a\s*year)"
_N = r"\$\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k\b)?"
_N2 = r"\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k\b)?"  # 2nd number: $ optional ("$70 - 100/hr")

_RANGE = re.compile(_N + r"\s*(?:-|–|—|to)\s*" + _N2 + r"\s*" + _UNIT + "?", re.I)
_SINGLE_UNIT = re.compile(_N + r"\s*" + _UNIT, re.I)
_SALARY = re.compile(_N, re.I)


def _val(num: str, k: str | None) -> float:
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


def _yearly(v: float, unit: str | None, k: str | None) -> bool:
    u = (unit or "").lower()
    if any(w in u for w in _HOURLY):
        return False
    if any(w in u for w in _YEARLY):
        return True
    return bool(k) or v >= 1000  # no explicit unit -> infer from magnitude


def _hourly(v: float, yearly: bool) -> float:
    return v / 2080 if yearly else v


def _ok(h: float) -> bool:
    return 10 <= h <= 600  # sanity window for a dev hourly-equivalent


def extract(text: str) -> str | None:
    if not text or "$" not in text:
        return None

    m = _RANGE.search(text)
    if m:
        k1, k2, unit = m.group(2), m.group(4), m.group(5)
        lo, hi = _val(m.group(1), k1), _val(m.group(3), k2)
        yr = _yearly(max(lo, hi), unit, k1 or k2)
        lo_h, hi_h = _hourly(lo, yr), _hourly(hi, yr)
        if _ok(lo_h) and _ok(hi_h) and lo_h <= hi_h:
            return f"${round(lo_h)}-{round(hi_h)}/hr"

    m = _SINGLE_UNIT.search(text)
    if m:
        h = _hourly(_val(m.group(1), m.group(2)), _yearly(_val(m.group(1), m.group(2)), m.group(3), m.group(2)))
        if _ok(h):
            return f"${round(h)}/hr"

    # last resort: a lone salary that clearly *is* money (comma-grouped or k-suffixed)
    for m in _SALARY.finditer(text):
        num, k = m.group(1), m.group(2)
        if "," not in num and not k:
            continue
        h = _hourly(_val(num, k), _yearly(_val(num, k), None, k))
        if _ok(h):
            return f"${round(h)}/hr"
    return None
