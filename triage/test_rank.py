"""The sort IS the priority function.  Run:  .venv/bin/python -m pytest triage/test_rank.py -q

Ben's order is channel, then work-life balance, then fit, then remote, then rate. Until 2026-07-30 the
code sorted tier -> verdict -> fit -> intensity, which put work-life balance fourth — where it only
broke a tie between two jobs sharing a tier, a verdict AND a 0-100 fit score. That tie essentially
never occurs, so `profile/rubric.md` called low intensity "non-negotiable" while the code made it the
weakest constraint in the file, and nothing about the output ever showed it.

That is the failure these pin: not a crash, a ranking that quietly disagrees with the rubric it claims
to implement.

The order shipped is `tier -> verdict -> intensity -> fit -> JD completeness`: intensity above the fit
SCORE and below the verdict GRADE. An intermediate draft put intensity second, above the verdict, and
that inverted the hard-gate caps — see `test_a_capped_low_fit_role_never_floats_on_being_undemanding`.
Reasoning: `docs/knowledge-base/decision-work-life-balance-priority.md`.
"""
from __future__ import annotations

from core.models import Analysis, Job
from . import rank


def _job(tier="PRIMARY", *, intensity=3, verdict="FIT", fit=70, jd_source="full", title="Engineer"):
    j = Job(link=f"https://x.test/{title}-{fit}-{intensity}", company="Acme", title=title,
            jd_source=jd_source)
    j.final_tier = tier
    j.analysis = Analysis(tier=tier, fit_score=fit, intensity=intensity, verdict=verdict,
                          why="", role_summary="", meets_goals="")
    return j


def _order(*jobs):
    return [j.title for j in sorted(jobs, key=rank.sort_key)]


def test_sane_hours_outranks_a_better_scoring_busier_role():
    """The whole change in one assertion, at the intensities that actually reach this list.

    3-vs-2 and not 5-vs-2: `triage/worklist.py` pulls intensity 4-5 out of the rankings entirely, so a
    test on those pins a comparison production never makes. Within what remains, a fit-88 busier role
    reading above a fit-74 calmer one is the thing Ben read every morning, and it is the opposite of
    his stated #2 priority.
    """
    busier = _job(intensity=3, fit=88, title="busier")
    sane = _job(intensity=2, fit=74, title="sane")
    assert _order(busier, sane) == ["sane", "busier"]


def test_a_capped_low_fit_role_never_floats_on_being_undemanding():
    """The regression that decided the order of keys #2 and #3, 2026-07-30.

    The hard gates live in the VERDICT, not the score: a coordinator title or a mandatory-tech gap is
    capped at LOW_FIT however high the keyword match ran. Capped roles are also undemanding, so they
    score LOW intensity — and with intensity above the verdict, the cap inverted into a promotion. On
    the real `data/corpus/state-2026-07-29-144502.json` run that put a LOW_FIT role at fit 32 /
    intensity 2 above two STRONG_FIT roles at fit 85 in the same tier.
    """
    capped = _job(verdict="LOW_FIT", fit=32, intensity=2, title="coordinator")
    real = _job(verdict="STRONG_FIT", fit=85, intensity=3, title="engineer")
    assert _order(capped, real) == ["engineer", "coordinator"]


def test_channel_still_wins_over_work_life_balance():
    """Channel is #1 and intensity is #2 — promoting intensity must not have overshot into first.
    An agency contract at intensity 4 still leads a laid-back opportunistic perm role."""
    agency = _job("PRIMARY", intensity=4, fit=60, title="agency")
    perm = _job("OPPORTUNISTIC", intensity=1, fit=95, verdict="STRONG_FIT", title="perm")
    assert _order(perm, agency) == ["agency", "perm"]


def test_fit_still_decides_between_two_jobs_of_equal_intensity():
    """Fit is #3, not discarded — within one tier and one intensity the better-scoring role leads."""
    assert _order(_job(fit=62, title="weak"), _job(fit=91, verdict="STRONG_FIT", title="strong")) \
        == ["strong", "weak"]


def test_verdict_outranks_the_raw_score():
    """A capped role (LOW_FIT, hard gate named) must not climb over an uncapped one on score alone —
    the cap is a judgment and the number underneath it is not."""
    capped = _job(verdict="LOW_FIT", fit=59, title="capped")
    clear = _job(verdict="FIT", fit=61, title="clear")
    assert _order(capped, clear) == ["clear", "capped"]


def test_a_job_with_no_analysis_sorts_last_rather_than_crashing():
    """Ranking runs over whatever survived scoring, including a job that never got a judgment."""
    unscored = Job(link="https://x.test/none", title="unscored")
    unscored.final_tier = "PRIMARY"
    assert _order(_job(title="scored"), unscored) == ["scored", "unscored"]


def test_a_title_only_job_sorts_below_an_otherwise_identical_full_jd():
    """JD completeness is the last tiebreak and stays last: a judgment made on a title alone is the
    least trustworthy one on the page, so it goes underneath its equals."""
    assert _order(_job(jd_source="title_only", title="thin"), _job(title="full")) == ["full", "thin"]
