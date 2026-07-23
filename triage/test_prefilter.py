"""Minimal tests for the cheap prefilter gates.  Run:  .venv/bin/python -m pytest triage/ -q

The deterministic gate is tested because it is the one that can silently lose a job with no API call
and no second opinion. Every FALSE-POSITIVE case below is a real string from the 2026-07-20 run that
an earlier version of these regexes wrongly killed; they are here so the mistake can't come back.

The Sonnet gate is tested only for the property that survives a change of provider or library: it
**fails open**. Stage 3 moved it onto `core/llm.py`, where a refusal now arrives as a raised
`OutputParserException` rather than as `parsed_output=None` — so the direction worth pinning is that
every new way this call can fail still keeps the job. A screen that fails closed loses jobs Ben never
learns existed. Nothing here asserts the model's *judgment*; that is what `scripts/before_after.py`
is for, and it is deliberately not a test.
"""
from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException

from core.llm import ConfigurationError
from core.models import Job
from . import prefilter
from .prefilter import hard_skip


def _job(title: str = "Senior Full Stack Engineer", jd: str = "") -> Job:
    return Job(link="x", title=title, email_jd_text=jd)


# --- should SKIP -----------------------------------------------------------------------------------

def test_skips_ten_year_bar():
    # The 2026-07-13 mis-rank: this JD scored 83 and reached the apply list despite the stated bar.
    assert hard_skip(_job("Python Full Stack Developer", "Skills: 10+ Years of Experience, React, Python"))


def test_skips_twelve_year_bar():
    assert hard_skip(_job("Prompt Engineer", "12 Years of experience is required. PhD preferred."))


def test_skips_off_lane_title():
    assert hard_skip(_job("Sr. Java Full Stack Developer - Boston, MA"))
    assert hard_skip(_job("iOS Engineer (Swift / SwiftUI)"))


def test_skips_active_clearance():
    assert hard_skip(_job(jd="Must have an active TS/SCI clearance to be considered."))


def test_skips_heavy_travel():
    assert hard_skip(_job(jd="This role requires 75% travel to client sites."))


# --- should KEEP (regressions from the 2026-07-20 replay) -------------------------------------------

def test_keeps_company_age_boilerplate():
    """Darkroom: 'operating for 10 years' is company age, not a requirement. Real bar was 5+."""
    jd = ("a performance marketing agency that's been operating for 10 years, employs 100+ people. "
          "Must haves: 5+ years of professional software engineering experience.")
    assert hard_skip(_job("Full-Stack Engineer", jd)) is None


def test_keeps_range_using_low_end():
    """Fractal: 'Experience 5-10+ Years' gates at 5, not 10."""
    assert hard_skip(_job("Agentic AI Engineer", "Location Remote Experience 5-10+ Years")) is None


def test_keeps_lowest_bar_when_several_stated():
    """ArcheSys: '4-8 years' plus '2+ years' gates at 2."""
    jd = "4-8 years of professional software engineering experience. 2+ years of LLM experience."
    assert hard_skip(_job(jd=jd)) is None


def test_keeps_obtainable_clearance():
    """'Public Trust Clearance (or ability to obtain)' is not an ACTIVE clearance."""
    assert hard_skip(_job(jd="Clearance: Public Trust Clearance (or ability to obtain).")) is None


def test_keeps_seven_year_ask():
    """Genesis10 (fit 90) asks 7+ years — under the bar, and Ben stretches these."""
    assert hard_skip(_job(jd="7+ years of professional hands-on software development experience")) is None


def test_keeps_javascript_title():
    """'JavaScript' must not trip the 'java' alternative."""
    assert hard_skip(_job("JavaScript Full Stack Engineer", "React and Node")) is None


def test_keeps_incidental_java_mention():
    """A nice-to-have mention is not a primary stack — only the TITLE rejects."""
    assert hard_skip(_job(jd="Nice to have: exposure to Java or Go.")) is None


def test_keeps_light_travel():
    assert hard_skip(_job(jd="Light quarterly travel, about 10% travel.")) is None


# --- the body-shop skip ----------------------------------------------------------------------------
#
# The two directions here are NOT symmetric, and the asymmetry is the whole design. A missed body shop
# costs Ben one wasted read. A rule that cannot tell a body shop from a staffing agency costs him his
# PRIMARY tier — agency reqs are his fastest fills, and 41 of the 1,134-job corpus come from 28 named
# agencies. Every string below is real, quoted from `data/corpus/state-*.json`, and the KEEP cases are
# the postings that a rule keyed on "staffing firm", "visa", or "in-person interview" would have killed.

def test_skips_any_visa():
    """Atem Corp: 'Fulltime Any Visa'. Nobody but a shop placing bodies writes that line."""
    assert hard_skip(_job("Python Developer", "Job Title: Python Developer Dallas TX Fulltime Any Visa"))


def test_skips_any_workable_visa():
    """Enterprise Mobility Inc: 'Visa: Any workable visa.' — a vendor req under a recognizable name."""
    assert hard_skip(_job(jd="Bachelor's in Computer Science is minimum required. Visa: Any workable visa."))


def test_skips_ead_category_shopping():
    """Quantum Technologies: a work-auth line dealing in EAD categories, plus a withheld client."""
    jd = ("Bill Rate: $80-$90 Project Duration: 24 Months+ Client: To Be Discussed Later "
          "Work Authorization: US-Citizen, H-1B, OPT-EAD, GC-EAD")
    assert hard_skip(_job("Senior AI Full Stack Developer", jd))


def test_skips_ead_categories_even_when_excluded():
    """MPower Plus: 'no OPT, GC_EAD and CPT'. The vocabulary is the tell, not its polarity."""
    assert hard_skip(_job(jd="Job Type: Full-time( no OPT, GC_EAD and CPT) Skill Requirements: TypeScript"))


def test_skips_local_drivers_licence_only():
    """The spec's named tell. No corpus hit yet — pinned so the pattern can't rot unnoticed."""
    assert hard_skip(_job(jd="Only local candidates with a valid DL. DL copy is a must at submission."))


def test_skips_two_weak_tells_together():
    """VRK IT Vision: 'Mode of Interview', 'LinkedIn profile is a must and should match the resume',
    'Need a senior Resource with 13+ Years'. No single one of those is enough; three are."""
    jd = ("Duration:- 21 months Mode of Interview:- Teams Meeting NOTE:- A LinkedIn profile is a must "
          "and should match the resume. Need a senior Resource with 13+ Years of over all experien")
    assert hard_skip(_job("AI Engineer", jd))


# --- and must NOT skip (the expensive direction) ----------------------------------------------------

def test_keeps_a_named_agency_posting_a_named_client_req():
    """Genesis10, fit 90 — the calibration rubric's STRONG_FIT bar, and an agency req.

    It describes its client generically ('a Major Financial Institution'), which is exactly what the
    'generic vendor with no client named' tell must not be allowed to mean.
    """
    jd = ("Genesis10 is currently seeking a Senior Full Stack Developer - Remote position with a Major "
          "Financial Institution located in Cleveland, OH. This is a 5+ month contract opportunity.")
    assert hard_skip(_job("Senior Full Stack Developer - Remote", jd)) is None


def test_keeps_a_staffing_firm_stating_a_citizenship_requirement():
    """DKKD Staffing: 'Must be US Citizen or Legal/Permanent Resident Green Card (no C2C)'.

    Work-authorization language and the letters 'C2C' are not tells. 20 corpus postings mention green
    cards and 17 mention corp-to-corp; keying on either would take out real agencies.
    """
    jd = ("CITIZENSHIP: Must be US Citizen or Legal/Permanent Resident Green Card (no C2C) "
          "TITLE: Staff Engineer, AI & Agentic Development")
    assert hard_skip(_job("Staff Engineer, AI & Agentic Development", jd)) is None


def test_keeps_a_direct_employer_refusing_to_sponsor():
    """AllOne Health: 'This role does not offer H-1B, OPT, or other employer-sponsored work visas.'

    44 corpus postings name H-1B or OPT and nearly all are direct employers saying NO. Bare visa
    acronyms are therefore the opposite of a body-shop tell, which is why only the EAD forms match.
    """
    jd = ("Must be authorized to work in the US without employer-sponsored work authorization. This role "
          "does not offer H-1B, OPT, or other employer-sponsored work visas.")
    assert hard_skip(_job("Senior Engineer", jd)) is None


def test_keeps_an_employer_with_an_in_person_interview():
    """Versant Media, Acuity Insurance and Allocate all state one. None is a body shop.

    In-person-only was named as a tell in the spec; the corpus narrowed it to a corroborating one.
    """
    jd = ("As part of our selection process, external candidates may be required to attend an in-person "
          "interview with a VERSANT Media employee at one of our locations prior to a hiring decision.")
    assert hard_skip(_job("Senior Full Stack Engineer", jd)) is None


def test_keeps_a_recruiter_asking_for_a_resume():
    """Proven Recruiting: 'Please email your resume to ...'. One weak tell alone never skips."""
    jd = ("Please email your resume to mstramel@provenrecruiting.com if you're excited to explore this "
          "opportunity with our client. Share your updated resume when ready.")
    assert hard_skip(_job("Full Stack Engineer", jd)) is None


# --- Gate 2: the Sonnet screen, offline ------------------------------------------------------------

_JD = "React and TypeScript and Node and Python. " * 20   # over the 80-char floor, under the cap


class _Fake:
    """Stands in for the runnable `core.llm.structured` returns. Records what it was invoked with."""

    def __init__(self, result=None, raises: Exception | None = None):
        self.result, self.raises, self.calls = result, raises, []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def fake(monkeypatch):
    def install(f):
        monkeypatch.setattr(prefilter, "_screen_model", lambda: f)
        return f
    return install


def test_screen_reports_a_kill(fake):
    f = fake(_Fake(prefilter._Screen(keep=False, reason="Salesforce-primary role")))
    assert prefilter.cheap_screen(_job(jd=_JD)) == (False, "Salesforce-primary role")


def test_screen_keeps_the_job_when_the_call_raises(fake):
    """The failure shape the migration introduced: a refusal is an exception, not a None.

    On the native path this was `parsed_output is None`. If that difference had been missed the job
    would still be screened out — silently, for a reason that has nothing to do with the job.
    """
    fake(_Fake(raises=OutputParserException("did not validate")))
    assert prefilter.cheap_screen(_job(jd=_JD)) == (True, "")


def test_screen_keeps_the_job_when_the_provider_is_misconfigured(fake):
    """A stranger with no key gets every job screened *in*, not every job screened out."""
    fake(_Fake(raises=ConfigurationError("ANTHROPIC_API_KEY is not set")))
    assert prefilter.cheap_screen(_job(jd=_JD)) == (True, "")


def test_screen_sends_the_cached_system_block_and_a_capped_jd(fake):
    """Prompt shape, which the path change could have altered without changing any answer.

    The system prompt must stay a *list* of blocks carrying `cache_control` — flattened to a bare
    string it is re-billed on every one of a run's ~350 screens. And the JD must still be truncated,
    because the whole point of this gate is that it is cheap.
    """
    f = fake(_Fake(prefilter._Screen(keep=True, reason="in lane")))
    prefilter.cheap_screen(_job("Full Stack Engineer", "x" * 10_000))
    (system_role, system), (human_role, user) = f.calls[0]
    assert (system_role, human_role) == ("system", "human")
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == prefilter._SCREEN_SYSTEM
    assert user.count("x") == prefilter._MAX_JD
    assert "TITLE: Full Stack Engineer" in user


def test_screen_makes_no_call_for_a_thin_jd(fake):
    """Too little text to judge — Opus decides, and the cheap gate doesn't spend a call to say so."""
    f = fake(_Fake(raises=AssertionError("should not have been called")))
    assert prefilter.cheap_screen(_job(jd="Remote. Apply here!")) == (True, "")
    assert f.calls == []
