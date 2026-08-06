"""What may enter the Tier-2 browser queue.  Run:  .venv/bin/python -m pytest core/ -q

The queue is a work list for a human-driven Chrome session, so its cost is paid in round-trips and in
attention, not in CPU. That makes the two failure directions asymmetric in an unusual way:

  * a fetchable job WRONGLY excluded -> a real JD is never scored on its full text. Expensive.
  * an unfetchable link wrongly INCLUDED -> a wasted navigation, and it lands in the run summary's
    couldn't-fetch count as if a real posting had been lost.

So exclusion is deliberately a short, evidence-backed list rather than a heuristic — see
`_BROWSER_UNFETCHABLE` in `core/models.py` for what each entry cost before it was added.
"""
from __future__ import annotations

from core.models import Analysis, Job, needs_browser_fetch


def _job(link: str, jd_source: str = "snippet", verdict: str = "FIT") -> Job:
    j = Job(company="acme", title="engineer", link=link)
    j.jd_source = jd_source
    j.analysis = Analysis(tier="PRIMARY", fit_score=70, intensity=3, verdict=verdict,
                          why="x", role_summary="x", meets_goals="yes")
    return j


def test_a_promising_job_with_a_partial_jd_is_queued():
    assert needs_browser_fetch(_job("https://www.linkedin.com/jobs/view/123"))


def test_dice_tracking_wrappers_are_never_queued():
    """`elinks.dice.com` is marketing mail, not a posting.

    Across the 2026-07-23 and 2026-07-27 runs, 40 of these were queued and yielded zero JDs. One
    resolved cleanly to Dice's own LinkedIn *company page*, which is what proved they were never
    posting links to begin with rather than expired ones.
    """
    for link in ["https://elinks.dice.com/s/c/AbCdEf123",
                 "https://elinks.dice.com/a/sc/XyZ789"]:
        assert not needs_browser_fetch(_job(link)), link


def test_a_real_dice_posting_is_still_queued():
    """The exclusion is on the tracking host, not on Dice — a real `dice.com/job` link still counts."""
    assert needs_browser_fetch(_job("https://www.dice.com/job/detail/abc-123"))


def test_the_greenhouse_dashboard_is_not_a_posting():
    """A logged-in dashboard URL carries no job; it was scored `Untitled @ unknown` on 2026-07-27."""
    assert not needs_browser_fetch(_job("https://my.greenhouse.io/dashboard"))


def test_a_full_jd_is_not_queued_again():
    assert not needs_browser_fetch(_job("https://www.linkedin.com/jobs/view/123", jd_source="full"))


def test_a_skipped_job_is_not_queued():
    assert not needs_browser_fetch(_job("https://www.linkedin.com/jobs/view/123", verdict="SKIP"))


def test_a_job_with_no_link_is_not_queued():
    assert not needs_browser_fetch(_job(""))
