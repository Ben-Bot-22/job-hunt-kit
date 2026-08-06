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


# The body-shop skip lived here until 2026-07-30 — 6 skip-cases and 5 must-not-skip cases, removed
# with the rule. It keyed on how a posting was *written* (any-visa lines, EAD-category shopping,
# withheld clients) and was cut at Ben's instruction: over 2,185 analyzed jobs it labelled ~1%, and
# almost all of those were already dying on an independent rule — out-of-lane stack, non-US, or
# location. The regexes were a maintenance surface pinned to 2026-07 vendor boilerplate, guarding a
# decision the other rules already made. See docs/knowledge-base/decision-body-shop-skip-or-cap.md.

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
