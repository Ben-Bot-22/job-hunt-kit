"""The apply doc's ONE review section.  Run:  .venv/bin/python -m pytest triage/test_worklist.py -q

The page refuses jobs for three different kinds of reason, and the analysis keeps them distinct:

  * **SKIP** — a factual hard filter fired (non-US, rate under the floor, a clearance).
  * **CAP AT LOW_FIT** — inferred, and the role is a poor fit (role shape, mandatory-tech gap).
  * **HELD BACK** — inferred, and the role is a GOOD fit Ben is choosing against: intensity 4-5.

They used to render in two separate sections. As of 2026-07-30 they render in ONE, grouped by reason,
because Ben reviews them in one pass and the reason belongs on the sub-heading rather than in which
heading a job happened to fall under:

  *"it doesn't matter if they are rejected for intensity as long as i can look at them and audit… i
  need to review it personally to know so you need to show me. if it is clearly high intensity (4-5)
  you need confidence to exclude - it should go in the review section with rejected jobs and the
  reason."*

So the failure directions pinned here are all quiet ones: a job that vanishes because nobody
recognised its reason, a job rendered twice and read as two rejections, and an always-on role reaching
Focus today. Reasoning: `docs/knowledge-base/decision-work-life-balance-priority.md`.
"""
from __future__ import annotations

from core.models import Analysis, Job
from .worklist import REVIEW_HEADING, render

REVIEW = REVIEW_HEADING


def _job(company="Acme", title="Full Stack Developer", *, intensity=2, verdict="FIT", fit=72,
         reason="", red_flags=(), why="in lane", tier="PRIMARY"):
    j = Job(link=f"https://x.test/{company}", company=company, title=title, jd_source="full")
    j.final_tier = tier
    j.analysis = Analysis(tier=tier, fit_score=fit, intensity=intensity, verdict=verdict, why=why,
                          role_summary="", meets_goals="", held_back_reason=reason,
                          red_flags=list(red_flags))
    return j


def _section(text: str, heading: str) -> str:
    """Everything from one `##` heading to the next — what a reader actually sees under it."""
    body = text.split(heading, 1)[1]
    return body.split("\n## ")[0]


def _group(text: str, reason: str) -> str:
    """One `###` bucket inside the review section."""
    return _section(text, REVIEW).split(f"### {reason} ")[1].split("\n### ")[0]


# --- held back: visible, out of the rankings, auditable --------------------------------------------

def test_a_high_intensity_job_is_reviewable_and_not_in_the_rankings():
    """The point of the section. A strong-scoring always-on role must not sit in Focus today, and must
    still be somewhere Ben can read it and overrule the call."""
    text = render([_job("Startupco", intensity=5, fit=90, verdict="STRONG_FIT", reason="intensity",
                        red_flags=['"passion, not counting hours"'])],
                  days=3, skipped_pre=0)
    assert "Startupco" in _group(text, "intensity")
    assert "Startupco" not in _section(text, "▶ Focus today")


def test_the_quoted_tell_reaches_the_page():
    """Intensity is the most inferred number in the analysis. Without the phrase the scorer keyed on,
    Ben has no way to overrule it — and overruling it is the entire purpose of showing him the job."""
    text = render([_job("Startupco", intensity=5, reason="intensity",
                        red_flags=['"we work hard here"', "named on-call rotation"])],
                  days=3, skipped_pre=0)
    assert '"we work hard here"' in _section(text, REVIEW)


def test_a_held_back_job_keeps_its_real_verdict_on_the_line():
    """It was never skipped, and the corpus still holds it. Rendering it as a SKIP would tell Ben a
    judgment was made that nobody made — and these are roles he may well decide to apply to."""
    text = render([_job("Startupco", intensity=4, verdict="STRONG_FIT", fit=88, reason="intensity")],
                  days=3, skipped_pre=0)
    line = _group(text, "intensity")
    assert "STRONG_FIT" in line and "SKIP" not in line


def test_a_sane_hours_job_is_untouched_by_the_held_back_split():
    """The regression guard on the split itself: it must take the crunch roles and nothing else."""
    text = render([_job("Genesis10", intensity=3, verdict="STRONG_FIT", fit=90)], days=3, skipped_pre=0)
    assert REVIEW not in text
    assert "Genesis10" in _section(text, "▶ Focus today")


def test_a_high_intensity_job_leaves_the_rankings_even_when_it_also_skipped():
    """Held-back is verdict-blind as of 2026-07-30. There is one review section now, so a SKIP that is
    also always-on has no second home to be routed to — and the reason on its heading is the specific
    gate the scorer named, not the intensity, because `non-us` is the more useful word."""
    text = render([_job("Offshore", intensity=5, verdict="SKIP", fit=10, reason="non-us",
                        why="non-US")], days=3, skipped_pre=0)
    assert "Offshore" in _group(text, "non-us")


def test_a_skipped_correspondence_job_still_renders_in_live_correspondence():
    """Until 2026-07-31 this section filtered out `verdict == "SKIP"`, so a job a human emailed about
    that also scored SKIP rendered in NO section at all: not ranked (correspondence jobs are pulled
    out before ranking), not in Live correspondence (the SKIP filter), not in the review section either
    (also pulled out before that split runs). On 2026-07-31, 5 of 7 correspondence jobs from one run's
    'Built In' alerts vanished this way. The section already says 'NOT fresh leads' — verdict was
    never a reason to hide one."""
    j = _job("PNC Bank", title="Software Developer Lead", verdict="SKIP", fit=15,
             why="legacy mainframe stack mismatch")
    j.from_correspondence = True
    j.email_sender = "Built In <support@builtin.com>"
    text = render([j], days=3, skipped_pre=0)
    assert "PNC Bank" in _section(text, "📬 Live correspondence")


def test_an_always_on_job_the_scorer_did_not_refuse_is_ranked_not_hidden():
    """The inverse of the rule this file pinned until 2026-08-04, and the regression that change exists
    to prevent.

    `intensity >= 4` used to pull a job out of the ranked list on its own, whatever the scorer had
    recorded. On 2026-08-03 that hid six roles for an on-call duty, a 24/7 rotation, incident
    response, 20-30% travel and "move fast, deploy daily" — two of them the joint-highest-scoring jobs
    of the run. Ben: *"a job is a job and i will travel… you should not skip them. you should just
    rank them lower and name the suspect wording."*

    So a blank `held_back_reason` now means exactly what it says — nothing was refused — no matter how
    high the intensity, and the hours show up as a warning on the line instead of as a disappearance.
    """
    text = render([_job("Oldstate", intensity=5, reason="")], days=3, skipped_pre=0)
    assert "Oldstate" in _section(text, "▶ Focus today")
    assert REVIEW not in text, "a job the scorer refused nothing on must not reach the review section"
    assert "⚠ hours" in text, "a ranked intensity-5 role must still say so on its line"


def test_stated_over_40_percent_travel_is_the_one_hours_gate_that_still_refuses():
    """`travel` is checkable — a percentage the posting states — which is why it survived the change
    that retired the inferred threshold. Ben, 2026-08-04: *"a trigger is >40% travel -- that is a
    line."* It must land in the review section WITH its link, because the point of the section is that
    he can evaluate one and pull it back in."""
    text = render([_job("Roadwarrior", intensity=4, reason="travel", why="60% travel")],
                  days=3, skipped_pre=0)
    assert "Roadwarrior" in _group(text, "travel")
    assert "https://x.test/Roadwarrior" in _group(text, "travel")


# --- one section, grouped by reason -----------------------------------------------------------------

def test_refusals_group_under_their_reason():
    """'Show me everything rejected because of X' is the question the flat list could not answer."""
    text = render([_job("A", verdict="SKIP", reason="non-us", why="India"),
                   _job("B", verdict="SKIP", reason="rate", why="$28/hr"),
                   _job("C", verdict="SKIP", reason="non-us", why="Canada")],
                  days=3, skipped_pre=0)
    non_us = _group(text, "non-us")
    assert "@ A" in non_us and "@ C" in non_us and "@ B" not in non_us
    assert "### rate " in _section(text, REVIEW)


def test_a_capped_role_reaches_a_reason_group_without_ever_being_a_skip():
    """`role-shape` and `years-bar` are CAPS at LOW_FIT, never SKIPs. While grouping ran over the SKIP
    list alone, both tokens were unreachable — the vocabulary named buckets that could not exist."""
    text = render([_job("Coordinator Co", verdict="LOW_FIT", fit=45, intensity=4,
                        reason="role-shape", why="duties are coordination")],
                  days=3, skipped_pre=0)
    assert "Coordinator Co" in _group(text, "role-shape")


def test_a_refusal_with_no_reason_falls_into_a_catch_all():
    """A grouping that drops its leftovers is a grouping that deletes jobs. The scorer will not always
    set the field — an old state file predates it entirely — and every one of those must still render."""
    text = render([_job("Nameless", verdict="SKIP", reason="", why="thin posting")],
                  days=3, skipped_pre=0)
    assert "Nameless" in _section(text, REVIEW)


def test_the_catch_all_renders_last():
    """It is the bucket with the least to say. A named reason above it is what someone came to read."""
    text = render([_job("Nameless", verdict="SKIP", reason=""),
                   _job("Offshore", verdict="SKIP", reason="non-us")], days=3, skipped_pre=0)
    review = _section(text, REVIEW)
    assert review.index("### non-us ") < review.index("### other / unspecified ")


def test_every_refused_job_appears_exactly_once():
    """Grouping must partition, not fan out: a job listed twice reads as two separate rejections, and
    one listed zero times is a job the tool silently deleted."""
    jobs = [_job("A", verdict="SKIP", reason="non-us"), _job("B", verdict="SKIP", reason=""),
            _job("C", verdict="LOW_FIT", reason="stack-gap", intensity=5),
            _job("D", verdict="SKIP", reason="non-us"), _job("E", intensity=4, reason="intensity")]
    review = _section(render(jobs, days=3, skipped_pre=0), REVIEW)
    for name in "ABCDE":
        assert review.count(f"@ {name}*") == 1, f"{name} rendered {review.count(f'@ {name}*')} times"


def test_the_section_count_matches_what_is_in_it():
    """The heading count is the first thing read and the only claim on the page about completeness."""
    jobs = [_job("A", verdict="SKIP", reason="non-us"), _job("B", intensity=5, reason="intensity"),
            _job("C", verdict="SKIP", reason="")]
    text = render(jobs, days=3, skipped_pre=0)
    assert f"{REVIEW} (3)" in text


def test_an_unscored_job_still_renders_in_its_own_block():
    """The errored split runs before the held-back one and must survive it: a failed call is the
    absence of a judgment, so it is neither rejected nor held back."""
    j = _job("Insight Global", verdict="SKIP", fit=0, intensity=5, why="analysis_error: overloaded")
    j.analysis_errored = True
    text = render([j], days=3, skipped_pre=0)
    assert "Insight Global" in _section(text, "NOT SCORED")
    assert REVIEW not in text


def test_nothing_vanishes_between_the_rankings_and_the_review():
    """The invariant the whole page rests on: every scored job renders somewhere, exactly once. The
    held-back split subtracts from the ranked list, and a subtraction with no matching addition is how
    a run silently loses jobs."""
    jobs = [_job(f"Co{i}", intensity=(i % 5) + 1, verdict=v, reason=r)
            for i, (v, r) in enumerate([("STRONG_FIT", ""), ("FIT", ""), ("LOW_FIT", "role-shape"),
                                        ("SKIP", "non-us"), ("SKIP", ""), ("FIT", "intensity"),
                                        ("LOW_FIT", "stack-gap"), ("STRONG_FIT", "")])]
    text = render(jobs, days=3, skipped_pre=0)
    for j in jobs:
        assert text.count(f"`{j.id}`") == 1, f"{j.company} rendered {text.count(f'`{j.id}`')} times"
