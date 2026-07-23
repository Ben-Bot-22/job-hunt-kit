"""Tests for semantic dedup — what collapses, what must never collapse, and what it costs.

Offline and (all but one test) with no model: the deterministic stand-in embedder from
`core/test_retrieval.py` gives real cosine geometry over these fixtures, because the fixtures are
**verbatim excerpts of real corpus records** and the pairs that matter here are near-identical text.
The single test that loads the real 67 MB `bge-small` skips itself when the weights aren't cached and
pins the actual similarities the corpus produced.

The failure directions being guarded, in order of what they cost:

  * **A wrong collapse.** It deletes a real job — never scored, never in the worklist, no trace. The
    corpus contains the exact pair that would do it: `Redhorse Corporation` posted
    `Senior Everything Engineer (Front End)` and `Mid-Level Everything Engineer (Front End)` in one
    run with JD text that is **byte-identical for its first 4,999 characters**. Cosine 0.986,
    Jaccard 0.997 — both similarity gates wide open. Only the rule "two titles at one employer are
    two reqs" stops it, and that is the single most load-bearing line in `dedup.py`.
  * **A collapse nobody can see.** A merge that isn't rendered is indistinguishable from a job that
    was never posted.
  * **A missed duplicate.** One wasted Opus call. Cheap, and deliberately the direction the
    thresholds lean.
  * **A duplicate that reaches the analyzer anyway** — the whole point is that it costs nothing.

Run:  .venv/bin/python -m pytest triage/ -q
"""
from __future__ import annotations

import pytest

from core.index import model_is_cached
from core.models import Job, job_from_dict, job_to_dict
from core.test_retrieval import FakeEmbedder     # a shared fixture, not a leaf reaching into a leaf

from . import config, dedup
from .worklist import render

# ---- real corpus text, verbatim -------------------------------------------------------------------
# `data/corpus/state-2026-07-20-094851.json`. Both members of each pair below carried JD text that was
# byte-identical over the excerpted range, so each pair shares one constant here — that is the corpus
# fact, not a convenience.

# Posted as `AI Engineer @ Global Payments Inc.` AND `AI Engineer @ Worldpay`, same 5,608-char JD.
# Exact-key dedup cannot see this: the key is `company|title`, and the company is what differs.
PAYMENTS_JD = """Ready to take your career global?
Make your mark at one of the biggest names in payments. We are seeking a highly skilled and \
forward-thinking AI Engineer to join our AI Engineering team. This role is ideal for a hands-on \
technologist with deep expertise in machine learning (ML) and deep learning (DL), and a strong \
working knowledge of Generative AI technologies. You will design, build, and optimize intelligent \
systems that power automation, personalization, and decision-making across our FinTech platforms. \
This is a unique opportunity to work at the intersection of cutting-edge AI research and real-world \
enterprise applications.
What You'll Own
Design, develop, and deploy ML, DL, and Generative AI models that solve complex business problems \
and deliver measurable value.
Build and maintain scalable ML pipelines and agentic workflows using modern frameworks."""

# Two DIFFERENT reqs — different seniority band, therefore different pay — sharing a JD body.
REDHORSE_JD = """About The Organization
Now is a great time to join Redhorse Corporation. We are a solution-driven company delivering data \
insights and technology solutions to customers with missions critical to U.S. national interests. \
We're looking for thoughtful, skilled professionals who thrive as trusted partners building \
technology-agnostic solutions and want to apply their talents supporting customers with difficult \
and important mission sets.

About The Role
Redhorse transforms the way the government uses data and technology. We are seeking "Everything \
Engineers" (Full-Stack Software Engineers with a Frontend Focus) to modernize a mission-critical \
legacy system managing billions of dollars in U.S. international security cooperation."""

# Two genuinely different client reqs that embed close — 0.918 cosine on the full records. The
# similarity is real; the overlap is zero, which is the distinction the second gate exists to make.
TMS_JD = """Job Description

Role: Senior Full Stack Engineer - AI & Next.js

Duration: Long Term

Location: United States- Remote

Role Summary

We are looking for a Senior Full Stack Engineer with strong experience in AI/LLM integration, \
modern Next.js development, and distributed systems architecture. The ideal candidate is an \
AI-first developer who actively uses tools like Copilot, Cursor, and Claude Code to accelerate \
development and help drive AI engineering best practices across the team.

Key Requirements

AI / LLM Integration (Must Have)

Hands-on experience integrating OpenAI, Azure OpenAI, Anthropic, or similar LLMs into production \
applications, including prompt engineering, streaming responses, and hallucination mitigation."""

PANASONIC_JD = """Overview
Senior AI Full Stack Engineer will design, build, and ship production-grade AI-powered applications \
that sit at the intersection of modern web engineering and the rapidly evolving world of generative \
AI and agentic systems.
We are looking for an engineer who is AI-native: someone who instinctively reaches for LLM APIs, \
RAG pipelines, multi-agent orchestration, and vector databases as core building blocks - while also \
owning the complete product surface from a performant React/Next.js front end through a scalable \
FastAPI or Node.js back end to cloud-deployed, observable production systems.
You will partner with AI Architects, data scientists, product managers, and UX designers to deliver \
AI-driven features across connected vehicle platforms and manufacturing intelligence."""


def _job(company, title, jd, **kw):
    return Job(link=f"https://x/{company}/{title}".replace(" ", "-"), company=company, title=title,
               fetched_jd=jd, jd_source="full", **kw)


def _collapse(jobs):
    return dedup.collapse(jobs, embedder=FakeEmbedder())


# ---- the case this exists for ---------------------------------------------------------------------

def test_one_req_under_two_company_names_collapses():
    """User story 7, pinned to the corpus pair that motivated it."""
    jobs = _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                      _job("Worldpay", "AI Engineer", PAYMENTS_JD)])
    assert len(jobs) == 1
    assert [d["company"] for d in jobs[0].duplicates] == ["Worldpay"]


def test_a_three_way_repost_collapses_to_one():
    """The spec's actual scenario — TEKsystems, Insight Global and Apex on one client req."""
    jobs = _collapse([_job("TEKsystems", "AI Engineer", PAYMENTS_JD),
                      _job("Insight Global", "AI Engineer", PAYMENTS_JD),
                      _job("Apex Systems", "AI Engineer", PAYMENTS_JD)])
    assert len(jobs) == 1
    assert len(jobs[0].duplicates) == 2


# ---- and the case that must never happen ----------------------------------------------------------

def test_two_different_roles_at_one_employer_do_not_collapse():
    """The expensive failure. These are two reqs at different seniority bands; merging them would
    have deleted one with no line anywhere saying it existed."""
    jobs = _collapse([_job("Redhorse Corporation", "Senior Everything Engineer (Front End)", REDHORSE_JD),
                      _job("Redhorse Corporation", "Mid-Level Everything Engineer (Front End)", REDHORSE_JD)])
    assert len(jobs) == 2
    assert all(not j.duplicates for j in jobs)


def test_the_redhorse_pair_clears_both_similarity_gates():
    """The control. Without this, the test above could be passing because the fixtures aren't similar
    — and the point is that they are *maximally* similar and are held apart by the title rule alone."""
    senior = _job("Redhorse Corporation", "Senior Everything Engineer (Front End)", REDHORSE_JD)
    mid = _job("Redhorse Corporation", "Mid-Level Everything Engineer (Front End)", REDHORSE_JD)
    assert dedup._jaccard(dedup._shingles(senior.jd_text),
                          dedup._shingles(mid.jd_text)) >= config.dedup_overlap()
    assert not dedup._titles_allow_merge(senior, mid)

    # Same text under two different company names is the same req, and does collapse.
    assert dedup._titles_allow_merge(senior, _job("Apex Systems", "Mid-Level Everything Engineer", ""))


def test_similar_but_distinct_reqs_are_not_collapsed():
    """0.918 cosine on the real records, zero shared phrasing. High similarity is not sameness, and
    the overlap gate is what knows the difference."""
    jobs = _collapse([_job("TMS LLC", "Senior Full Stack Engineer - AI & Next.js", TMS_JD),
                      _job("Panasonic Automotive North America", "Senior AI Full Stack Engineer",
                           PANASONIC_JD)])
    assert len(jobs) == 2


def test_a_live_correspondence_thread_is_never_absorbed():
    """A human wrote to Ben about this one. It is not a lead, it is a process he may already be in —
    it gets its own worklist section, and it must not vanish into an agency's repost of the same req."""
    jobs = _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                      _job("Worldpay", "AI Engineer", PAYMENTS_JD, from_correspondence=True)])
    assert len(jobs) == 2


def test_a_thin_posting_is_never_collapsed():
    """Two title-only postings share a boilerplate footer and nothing else. Below the text floor
    there is no evidence, so there is no merge."""
    thin = "Apply now for this exciting opportunity! Equal opportunity employer."
    assert len(_collapse([_job("TEKsystems", "AI Engineer", thin),
                          _job("Apex Systems", "AI Engineer", thin)])) == 2


# ---- a duplicate has to cost nothing --------------------------------------------------------------

def test_the_duplicate_never_reaches_the_analyzer(monkeypatch):
    """Acceptance: collapse lands before the paid call. `_phase1` fetches, collapses, then maps
    `_process` over the survivors — so this runs the real `_process` over the real collapse output
    and counts Opus calls."""
    from . import __main__ as main

    calls = []
    monkeypatch.setattr(main.prefilter, "hard_skip", lambda j: "")
    monkeypatch.setattr(main.prefilter, "cheap_screen", lambda j: (True, ""))
    monkeypatch.setattr(main, "analyze", lambda j: calls.append(j) or None)

    for job in _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                          _job("Worldpay", "AI Engineer", PAYMENTS_JD)]):
        main._process(job)
    assert len(calls) == 1


def test_the_posting_with_the_most_jd_text_survives():
    """The survivor is scored on behalf of the whole cluster, so it should be the one with the most
    for the analyzer to read."""
    short = _job("Worldpay", "AI Engineer", PAYMENTS_JD)
    long = _job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD + "\nBenefits: medical, dental.")
    assert _collapse([short, long])[0].company == "Global Payments Inc."


# ---- a merge Ben cannot see is a job that vanished -------------------------------------------------

def test_the_absorbed_posting_keeps_its_id_and_link():
    """`_phase1` marks these seen and counts their emails resolved. Without the id the absorbed job
    comes back tomorrow; without the link Ben can't check the merge."""
    jobs = _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                      _job("Worldpay", "AI Engineer", PAYMENTS_JD)])
    d = jobs[0].duplicates[0]
    assert d["id"] == "worldpay|ai engineer|"
    assert d["link"].endswith("Worldpay/AI-Engineer")


def test_the_worklist_reports_what_merged_and_why():
    from core.models import Analysis

    jobs = _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                      _job("Worldpay", "AI Engineer", PAYMENTS_JD)])
    jobs[0].analysis = Analysis(tier="PRIMARY", fit_score=70, intensity=3, verdict="FIT",
                                why="Remote AI role.", role_summary="AI engineering.",
                                meets_goals="Remote, AI stack.")
    jobs[0].final_tier = "PRIMARY"
    out = render(jobs, days=3, skipped_pre=0)

    assert "## ⧉ Collapsed duplicates" in out
    assert "AI Engineer @ Worldpay" in out
    assert "similarity 1.00" in out and "JD overlap 100%" in out


def test_a_collapse_onto_a_skipped_job_is_still_reported():
    """The section is complete, not a view of the top picks. A SKIPped survivor renders in
    'Rejected / skipped', and its merge would otherwise never be shown at all."""
    from core.models import Analysis

    jobs = _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                      _job("Worldpay", "AI Engineer", PAYMENTS_JD)])
    jobs[0].analysis = Analysis(tier="PRIMARY", fit_score=20, intensity=3, verdict="SKIP",
                                why="Onsite.", role_summary="AI engineering.", meets_goals="No.")
    assert "AI Engineer @ Worldpay" in render(jobs, days=3, skipped_pre=0)


def test_duplicates_survive_the_state_file_round_trip():
    """Phase 3 reloads the state file and rewrites the worklist. Losing the merges there would make
    them disappear from the final document Ben actually reads."""
    jobs = _collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                      _job("Worldpay", "AI Engineer", PAYMENTS_JD)])
    assert job_from_dict(job_to_dict(jobs[0])).duplicates == jobs[0].duplicates


# ---- failing soft means scoring everything ---------------------------------------------------------

def test_disabled_scores_every_posting(monkeypatch):
    monkeypatch.setattr(config, "dedup_enabled", lambda: False)
    assert len(_collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                          _job("Worldpay", "AI Engineer", PAYMENTS_JD)])) == 2


def test_a_broken_embedder_costs_calls_rather_than_jobs():
    """No model on disk, no numpy, a network blip mid-download: every one of those has to end with
    the run scoring everything, never with the run dropping something."""
    class Exploding(FakeEmbedder):
        def embed_documents(self, texts):
            raise RuntimeError("no model")

    jobs = [_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
            _job("Worldpay", "AI Engineer", PAYMENTS_JD)]
    assert dedup.collapse(jobs, embedder=Exploding()) == jobs


def test_a_single_job_is_returned_untouched():
    jobs = [_job("Worldpay", "AI Engineer", PAYMENTS_JD)]
    assert dedup.collapse(jobs) == jobs        # no embedder constructed, so no 67 MB download


# ---- the one test that loads the real model --------------------------------------------------------

@pytest.mark.skipif(not model_is_cached(), reason="BAAI/bge-small-en-v1.5 weights are not cached")
def test_the_real_model_separates_the_three_corpus_pairs():
    """The thresholds are only meaningful against the embedder they were measured on. Real
    `bge-small` over these excerpts: the Worldpay pair 1.0000, the Redhorse pair 0.9873, TMS/Panasonic
    0.9153 — so the cosine gate alone stops the third pair and could not have stopped the second."""
    from core.index import FastEmbedEmbeddings

    embedder = FastEmbedEmbeddings()
    assert len(dedup.collapse([_job("Global Payments Inc.", "AI Engineer", PAYMENTS_JD),
                               _job("Worldpay", "AI Engineer", PAYMENTS_JD)],
                              embedder=embedder)) == 1
    assert len(dedup.collapse(
        [_job("Redhorse Corporation", "Senior Everything Engineer (Front End)", REDHORSE_JD),
         _job("Redhorse Corporation", "Mid-Level Everything Engineer (Front End)", REDHORSE_JD)],
        embedder=embedder)) == 2
    assert len(dedup.collapse(
        [_job("TMS LLC", "Senior Full Stack Engineer - AI & Next.js", TMS_JD),
         _job("Panasonic Automotive North America", "Senior AI Full Stack Engineer", PANASONIC_JD)],
        embedder=embedder)) == 2
