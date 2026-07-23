"""Deterministic channel-tier router + composite sort (triage-plan §2).

The model proposes a tier while analyzing; this finalizes it from the signal fields so the tiering is
consistent and tunable via config (primary_agencies / secondary_platforms). Then sort by
tier -> verdict -> fit -> intensity -> JD completeness.
"""
from __future__ import annotations

from . import config
from core.models import Job

_TIER_RANK = {"PRIMARY": 0, "SECONDARY": 1, "OPPORTUNISTIC": 2}
_VERDICT_RANK = {"STRONG_FIT": 0, "FIT": 1, "LOW_FIT": 2, "SKIP": 3}

_CONTRACTISH = {"contract", "contract-to-hire", "cth", "", "unknown"}
_REMOTEISH = {"remote", "hybrid", "", "unknown"}


def finalize_tier(job: Job) -> str:
    a = job.analysis
    if a is None:
        return "OPPORTUNISTIC"
    hay = f"{job.company} {job.source_platform}".lower()
    is_agency = a.is_agency or any(x in hay for x in config.primary_agencies())
    is_platform = any(x in hay for x in config.secondary_platforms())
    # PRIMARY = agency contract, remote/DFW — the fastest-fill lane.
    if a.verdict != "SKIP" and is_agency and a.employment_type in _CONTRACTISH and a.cadence in _REMOTEISH:
        return "PRIMARY"
    if is_platform:
        return "SECONDARY"
    return a.tier  # trust the model's judgment when no deterministic signal fires


def sort_key(job: Job):
    a = job.analysis
    return (
        _TIER_RANK.get(job.final_tier or "OPPORTUNISTIC", 2),
        _VERDICT_RANK.get(a.verdict if a else "SKIP", 3),
        -(a.fit_score if a else 0),
        a.intensity if a else 5,
        0 if job.jd_source == "full" else 1,
    )
