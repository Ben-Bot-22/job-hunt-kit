"""Deterministic channel-tier router + composite sort (triage-plan §2).

The model proposes a tier while analyzing; this finalizes it from the signal fields so the tiering is
consistent and tunable via config (primary_agencies / secondary_platforms). Then sort by
tier -> verdict -> intensity -> fit -> JD completeness — Ben's priority order, channel first and
work-life balance ahead of the fit SCORE but behind the verdict GRADE (2026-07-30; intensity was
fifth and therefore dead).
"""
from __future__ import annotations

from . import config
from core.models import Job

_TIER_RANK = {"PRIMARY": 0, "SECONDARY": 1, "OPPORTUNISTIC": 2}
_VERDICT_RANK = {"STRONG_FIT": 0, "FIT": 1, "LOW_FIT": 2, "SKIP": 3}

_CONTRACTISH = {"contract", "contract-to-hire", "cth", "", "unknown"}


def finalize_tier(job: Job) -> str:
    a = job.analysis
    if a is None:
        return "OPPORTUNISTIC"
    hay = f"{job.company} {job.source_platform}".lower()
    is_agency = a.is_agency or any(x in hay for x in config.primary_agencies())
    is_platform = any(x in hay for x in config.secondary_platforms())
    # PRIMARY = agency contract of ANY cadence (remote OR onsite) — the fastest-fill lane now that Ben
    # is relocation-open. Cadence no longer gates this: onsite agency contract leads too.
    if a.verdict != "SKIP" and is_agency and a.employment_type in _CONTRACTISH:
        return "PRIMARY"
    if is_platform:
        return "SECONDARY"
    return a.tier  # trust the model's judgment when no deterministic signal fires


def sort_key(job: Job):
    """Ben's stated priority order: channel, then quality grade, then work-life balance, then score.

    Intensity used to sit LAST-but-one, where it only broke a tie between two jobs sharing a tier, a
    verdict *and* a 0-100 fit score — a tie that essentially never happens, so the rubric called low
    intensity "non-negotiable" while the code made it the weakest constraint in the file. The failure
    direction that fixes: a crunch role at fit 88 reading above a sane-hours role at fit 74, every
    morning, for a priority Ben ranked #2.

    **Intensity sits above the fit SCORE and below the verdict GRADE, and the order of those two is
    not cosmetic (Ben's call, 2026-07-30).** The hard gates live in the VERDICT, not in the score: a
    coordinator title or a mandatory-tech gap is CAPPED at LOW_FIT no matter how high the keyword
    score ran (`profile/rubric.md`, NON-ENGINEERING ROLE SHAPE / MANDATORY-TECH GAP). Capped roles are
    also undemanding, so they score LOW intensity — which means putting intensity above the verdict
    floats exactly the junk the caps exist to suppress. Measured on the real
    `data/corpus/state-2026-07-29-144502.json` run, an intensity-first key put a LOW_FIT role at fit
    32 / intensity 2 ABOVE two STRONG_FIT roles at fit 85 in the same tier. Quality grade first, then
    hours, then score.

    Reasoning and measurements: `docs/knowledge-base/decision-work-life-balance-priority.md`.
    """
    a = job.analysis
    return (
        _TIER_RANK.get(job.final_tier or "OPPORTUNISTIC", 2),
        _VERDICT_RANK.get(a.verdict if a else "SKIP", 3),
        a.intensity if a else 5,
        -(a.fit_score if a else 0),
        0 if job.jd_source == "full" else 1,
    )
