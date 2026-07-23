"""Offline tests for the scoring call site.  Run:  .venv/bin/python -m pytest triage/ -q

Stage 3 moved `analyze` onto `core/llm.py` — the last of the three call sites, and the only one that
touches the judgment Ben reads every weekday morning. Nothing here asserts what the model *decides*:
that is what `scripts/before_after.py` is for, and it is deliberately not a test (spec §"Verification
is light-touch by explicit decision"). What is pinned is everything around the call that the path
change could have altered without changing an answer:

  * **the precedent block reaching the prompt**, because stage 2's whole capability is inert if it
    silently stops arriving — and it fails *soft* by design, so nothing would ever go red;
  * the prompt shape, because a system block flattened from a list to a string drops the
    `cache_control` marker and re-bills the goal profile on every one of a run's ~350 scored jobs;
  * the failure direction, because a refusal now arrives as a raised `OutputParserException` where
    the native path returned `parsed_output=None`. Both must land the job in "Rejected / skipped"
    with the error as its reason — visible and attributable, never a `None` that crashes ranking.
"""
from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException

from core.llm import ConfigurationError
from core.models import Analysis, Job
from core.settings import profile_exists
from . import analyze

#: Analysis is scored against `profile/rubric.md`, which is injected whole into the prompt — so these
#: exercise the real path only once a rubric exists. On an unseeded clone there is none, and the
#: analyzer correctly refuses rather than scoring against nothing. Skipping keeps that refusal a
#: feature instead of reporting it as four broken tests. See docs/agents/tests.md.
needs_rubric = pytest.mark.skipif(
    not profile_exists(),
    reason="scores against profile/rubric.md, which no clone has until it is seeded. Run "
           "`python -m core.example` (the demo seeker's rubric) or `python -m core.setup`.")

_JD = ("We are hiring a Senior Full Stack Engineer. React, TypeScript, Node, Python, GCP. "
       "Remote, W2 contract, $70/hr. ") * 4

_PRECEDENT = ("HOW YOU JUDGED SIMILAR JOBS BEFORE:\n"
              "- Genesis10 — Senior Full Stack Developer: STRONG_FIT 90\n")


def _job(title: str = "Senior Full Stack Engineer", jd: str = _JD) -> Job:
    return Job(link="https://boards.test/jobs/1", company="Acme", title=title,
               source_platform="linkedin", posted_hint="3 days ago", fetched_jd=jd, jd_source="full")


def _analysis(**kw) -> Analysis:
    base = dict(tier="PRIMARY", fit_score=88, intensity=3, verdict="STRONG_FIT",
                why="in lane, remote, contract", role_summary="full stack build",
                meets_goals="yes", red_flags=[], resume_keywords=["React"])
    base.update(kw)
    return Analysis(**base)


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
    def install(f=None):
        f = _Fake(_analysis()) if f is None else f
        monkeypatch.setattr(analyze, "_analyze_model", lambda: f)
        return f
    return install


# --- the seam: prompt assembly, pure, no provider and no key --------------------------------------

def test_precedent_reaches_the_prompt_and_the_jd_is_read_into_last():
    """Stage 2's memory is only worth anything if it is actually in the message.

    Order matters as much as presence: precedent first, the JD last, so the thing being judged is
    what the model reads into rather than what it reads away from.
    """
    user = analyze.user_message(_job(), _PRECEDENT)
    assert _PRECEDENT.strip() in user
    assert user.index("Genesis10") < user.index("JOB DESCRIPTION:")
    assert user.rstrip().endswith(_JD.strip()[-40:])


def test_an_empty_corpus_yields_a_valid_prompt_not_a_malformed_one():
    """Day one for a stranger: no history at all, and the message is exactly the pre-stage-2 one.

    The failure this guards is cosmetic-looking and isn't: a leading blank block would be the only
    visible sign that retrieval broke, and there would be nothing to assert on.
    """
    user = analyze.user_message(_job(), "")
    assert user.startswith("TITLE: Senior Full Stack Engineer")
    assert "JOB DESCRIPTION:" in user


def test_a_job_with_no_jd_text_still_asks_for_a_judgment():
    """title_only jobs are real — a fetch that failed must not send an empty JOB DESCRIPTION."""
    user = analyze.user_message(_job(jd=""), "")
    assert "(no JD text available" in user


def test_the_jd_is_capped():
    """The goal profile is cached; the JD is not, so every extra character is billed on every job."""
    user = analyze.user_message(_job(jd="x" * 50_000), "")
    assert user.count("x") == analyze._MAX_JD


# --- the call site ---------------------------------------------------------------------------------

@needs_rubric
def test_analyze_retrieves_its_own_precedent(fake, monkeypatch):
    """`analyze()` asks for precedent itself rather than trusting the caller to pass it.

    Both scoring paths — phase 1 and the phase-3 re-analysis on the browser-fetched JD — go through
    here, and one of them forgetting is how the memory goes half-missing with nothing failing.
    """
    monkeypatch.setattr(analyze.precedent, "for_job", lambda job: _PRECEDENT)
    f = fake()
    analyze.analyze(_job())
    ((_, _), (_, user)) = f.calls[0]
    assert "Genesis10" in user


@needs_rubric
def test_an_explicit_precedent_argument_suppresses_retrieval(fake, monkeypatch):
    """`precedents=""` means "none", not "go and find some" — it is what the before/after script
    passes, so that a sampled job cannot retrieve itself and copy back its own stored score."""
    monkeypatch.setattr(analyze.precedent, "for_job",
                        lambda job: pytest.fail("retrieval should not have run"))
    f = fake()
    analyze.analyze(_job(), precedents="")
    ((_, _), (_, user)) = f.calls[0]
    assert user.startswith("TITLE:")


@needs_rubric
def test_the_system_block_stays_a_cached_list(fake):
    """Prompt shape. Flattened to a bare string this is the goal profile re-billed ~350 times a run,
    and no test output would change — only the invoice."""
    f = fake()
    analyze.analyze(_job(), precedents="")
    (system_role, system), (human_role, _) = f.calls[0]
    assert (system_role, human_role) == ("system", "human")
    assert system[0]["text"] == analyze._system()
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_a_refusal_becomes_a_visible_skip(fake):
    """The failure shape the migration introduced: a refusal raises where it used to return None.

    Either way the job must land in "Rejected / skipped" carrying the error, so a run that started
    failing calls looks like failed calls rather than like a quiet morning.
    """
    fake(_Fake(raises=OutputParserException("did not validate")))
    a = analyze.analyze(_job(), precedents="")
    assert (a.verdict, a.fit_score) == ("SKIP", 0)
    assert a.why.startswith("analysis_error:")
    assert a.red_flags == ["analysis error"]


@needs_rubric
def test_a_misconfigured_provider_becomes_a_visible_skip(fake):
    """A stranger with the wrong key gets every job marked with the reason, not an empty worklist."""
    fake(_Fake(raises=ConfigurationError("ANTHROPIC_API_KEY is not set")))
    a = analyze.analyze(_job(), precedents="")
    assert a.verdict == "SKIP"
    assert "ANTHROPIC_API_KEY" in a.why


def test_a_none_parse_is_an_analysis_not_a_none(fake):
    """Belt and braces, and it fixes a latent hole: the native path returned `parsed_output` straight
    through, so a `None` there left `Job.analysis = None` and blew up in ranking, three phases from
    the cause. It is an `Analysis` now, with the reason on it."""
    fake(_Fake(None))
    a = analyze.analyze(_job(), precedents="")
    assert isinstance(a, Analysis)
    assert a.verdict == "SKIP"
