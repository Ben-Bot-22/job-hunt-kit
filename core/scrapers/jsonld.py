"""Shared schema.org JobPosting (JSON-LD) extraction — reused by Mondo, Motion, Apex.

Many job sites embed a `<script type="application/ld+json">` JobPosting on each detail page.
Parsing that is far more stable than CSS-selector HTML scraping.
"""
from __future__ import annotations

import json
import re

from .posting import strip_html

_SCRIPT = re.compile(
    r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
    re.S | re.I,
)
_UNITS = {"HOUR": "/hr", "YEAR": "/yr", "WEEK": "/wk", "DAY": "/day", "MONTH": "/mo"}


def jobpostings(page: str) -> list[dict]:
    """All JobPosting objects found in a page's JSON-LD blocks."""
    out: list[dict] = []
    for m in _SCRIPT.finditer(page):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        out.extend(o for o in _walk(data) if _is_jobposting(o))
    return out


def _walk(data):
    if isinstance(data, list):
        for x in data:
            yield from _walk(x)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for x in graph:
                yield from _walk(x)
        yield data


def _is_jobposting(o: dict) -> bool:
    t = o.get("@type")
    return ("JobPosting" in t) if isinstance(t, list) else (t == "JobPosting")


def employment_type(jp: dict) -> str:
    et = jp.get("employmentType", "")
    return ",".join(str(x) for x in et) if isinstance(et, list) else str(et)


def is_contract(jp: dict) -> bool:
    et = employment_type(jp).lower()
    return any(k in et for k in ("contract", "temporary"))


def company(jp: dict) -> str:
    org = jp.get("hiringOrganization")
    return org.get("name", "") if isinstance(org, dict) else ""


def location(jp: dict) -> tuple[str, bool]:
    """(metro_label, is_remote)."""
    remote = str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    loc = jp.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = loc.get("address", {}) if isinstance(loc, dict) else {}
    if isinstance(addr, list):
        addr = addr[0] if addr else {}
    city = (addr or {}).get("addressLocality", "") or ""
    region = (addr or {}).get("addressRegion", "") or ""
    metro = "Remote" if remote else ", ".join(p for p in (city, region) if p)
    return metro, remote


def salary(jp: dict) -> str:
    bs = jp.get("baseSalary") or jp.get("estimatedSalary")
    if not isinstance(bs, dict):
        return ""
    val = bs.get("value")
    if isinstance(val, dict):
        lo, hi = val.get("minValue"), val.get("maxValue")
        unit = _UNITS.get(str(val.get("unitText", "")).upper(), "")
        if lo or hi:
            return f"${lo or '?'}-{hi or '?'}{unit}"
        if val.get("value"):
            return f"${val.get('value')}{unit}"
    return ""


def description(jp: dict, limit: int = 6000) -> str:
    return strip_html(jp.get("description", "") or "", limit)


def posted(jp: dict) -> str:
    """Posting date as YYYY-MM-DD (schema.org `datePosted`), or '' if absent."""
    return str(jp.get("datePosted") or "")[:10]
