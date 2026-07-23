"""Have I dealt with these people before?  Run:  .venv/bin/python -m pytest research/ -q

Offline by rule, like the rest of the suite — every case runs against fixture files in tmp_path, and
the JD text in them is copied verbatim from the corpus so the thresholds are pinned to real postings,
not to invented prose.

The failure direction that costs something: **a missed hit**. It means cold-applying somewhere Ben is
already in process — the College Board near-miss `test_correspondence.py` guards from the other side.
A spurious hit costs one line in a brief. So the assertions lean on recall: name drift still matches,
and one req shopped by two agencies is surfaced even though nothing about the two postings agrees
except the prose.

The second failure direction: an unreadable corpus reported as a clean slate. "No history" is a
statement about the record; it must never be what a broken file looks like.
"""
from __future__ import annotations

import json

from .history import check_my_history, same_company

# Two agencies shopping one client req — Trident Consulting and Themesoft Inc., both "Agentic AI
# Developer", both in the corpus on 2026-07-13. Verbatim excerpts; note that even the years bar
# differs (10 vs 3–8), which is why title/company matching alone would never catch this.
TRIDENT_JD = """Trident Consulting is seeking a "Agentic AI Developer" for one of our clients in
Charlotte, NC. Length of Assignment: 1 year w/ extension. Type: Contract (W2). Rate: $90/hr.
Required Qualifications:
10 years of experience in software development or data engineering
Hands-on experience in Generative AI or LLM-based applications
Experience building APIs, microservices, or distributed systems
Implement agents and sub-agents (planner, executor, critic, router) using Claude Agent SDK / Lang Graph
Build tools and MCP integrations, design clean tool schemas, idempotent operations, and robust error handling.
Implement RAG pipelines: ingestion, chunking, embedding (Bedrock Titan), hybrid retrieval, citation rendering."""

THEMESOFT_JD = """Position: Agentic AI Developer
Location: United States - Remote
Required Qualifications:
3-8 years of experience in software development or data engineering
Hands-on experience in Generative AI or LLM-based applications
Experience building APIs, microservices, or distributed systems
Key roles:
Implement agents and sub-agents (planner, executor, critic, router) using Claude Agent SDK / Lang Graph
Build tools and MCP integrations, design clean tool schemas, idempotent operations, and robust error handling.
Implement RAG pipelines: ingestion, chunking, embedding (Bedrock Titan), hybrid retrieval, citation rendering."""

# An unrelated posting, also full-stack boilerplate — the noise floor the threshold has to clear.
COLLEGE_BOARD_JD = """The College Board is hiring a Senior Full Stack Engineer for the Assessment
platform. You will build React front ends and Java services on AWS, partner with product managers on
roadmap, and mentor engineers. Requires strong testing practice and accessibility awareness."""


def _corpus(tmp_path, jobs=(), applied=()):
    """A fixture corpus: one state file plus applied.json, in the layout ticket 01 established."""
    corpus = tmp_path / "corpus"
    corpus.mkdir(exist_ok=True)
    (corpus / "state-2026-07-13-102938.json").write_text(json.dumps({"jobs": list(jobs)}))
    (corpus / "applied.json").write_text(json.dumps(list(applied)))
    return corpus


def _skiplist(tmp_path, text: str):
    path = tmp_path / "skiplist.md"
    path.write_text(text)
    return path


def _job(company, title, jd="", verdict="FIT", score=70, link=""):
    return {"company": company, "title": title, "fetched_jd": jd,
            "link": link or f"https://x.test/{title.lower().replace(' ', '-')}",
            "analysis": {"verdict": verdict, "fit_score": score}}


# --- the applied record ------------------------------------------------------------------------

def test_applied_company_is_reported_with_date_and_note(tmp_path):
    """A missed applied hit is the expensive one: Ben cold-applies to a role he is already in process
    for. The date and the sheet's note are what let him tell "applied Monday" from "applied in May"."""
    corpus = _corpus(tmp_path, applied=[
        {"row": 4, "apply_date": "6/24", "company": "The College Board",
         "title": "Senior Full Stack Engineer", "url": "https://collegeboard.test/jobs/1",
         "confidence": "high", "note": "via Motion Recruitment"}])
    h = check_my_history("College Board", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert h.found and h.ok
    assert h.applied[0].date == "6/24"
    assert h.applied[0].note == "via Motion Recruitment"
    assert h.applied[0].confidence == "high"


def test_applied_row_matches_on_the_apply_url_when_the_company_column_is_blank(tmp_path):
    """The sheet is free-form and the company column is often empty; the link still names who it went
    to. Requiring the company column would drop real hits on the messiest rows."""
    corpus = _corpus(tmp_path, applied=[
        {"row": 1, "apply_date": "6/21", "company": "", "title": "Software Engineer III",
         "url": "https://jobs.collegeboard.org/apply/998", "confidence": "low"}])
    h = check_my_history("College Board", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert [a.matched_on for a in h.applied] == ["url"]


# --- the skiplist ------------------------------------------------------------------------------

def test_skiplist_company_is_reported_with_its_recorded_reason(tmp_path):
    """Verbatim from profile/skiplist.md. A skiplist hit without the reason tells Ben he said no once
    but not why — which is exactly the state in which he re-approaches anyway."""
    skiplist = _skiplist(tmp_path, "\n".join([
        "# Skiplist — jobs Ben has APPLIED to or REJECTED (never surface again)",
        "<!-- examples: acme|senior react contractor|   # applied — 2026-07-04 -->",
        "toptal|artificial intelligence fullstack engineer|   # rejected — 2026-07-07, "
        "Toptal = 90-min Codility algo-test gate, conflicts with fast placement",
    ]))
    h = check_my_history("Toptal", corpus_dir=_corpus(tmp_path), skiplist=skiplist)
    assert len(h.skipped) == 1
    assert "Codility algo-test gate" in h.skipped[0].reason
    assert h.skipped[0].title == "artificial intelligence fullstack engineer"


def test_skiplist_prose_and_examples_are_not_read_as_entries(tmp_path):
    """The file's own header and commented-out examples carry pipes and words; treating either as a
    recorded decision would put a fake rejection in front of Ben."""
    skiplist = _skiplist(tmp_path, "Format:  `<id>   # applied | rejected — YYYY-MM-DD, note`\n"
                                   "<!-- acme|senior react contractor|   # applied — 2026-07-04 -->")
    h = check_my_history("Acme", corpus_dir=_corpus(tmp_path), skiplist=skiplist)
    assert h.skipped == []


# --- the scored corpus -------------------------------------------------------------------------

def test_scored_corpus_hit_carries_the_verdict_and_the_run_date(tmp_path):
    """The pipeline already judged this company once; the brief should say what it decided rather than
    making Ben re-derive it."""
    corpus = _corpus(tmp_path, jobs=[_job("Genesis10", "Senior Full Stack Developer - Remote",
                                          verdict="STRONG_FIT", score=90)])
    h = check_my_history("Genesis10", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert h.scored[0].verdict == "STRONG_FIT" and h.scored[0].fit_score == 90
    assert h.scored[0].last_seen == "2026-07-13"


def test_company_name_drift_still_matches(tmp_path):
    """`The College Board` vs `College Board`, `Genesis10` vs `Genesis 10 Inc.` — a hit lost to
    spacing or a legal suffix is a missed hit, and those cost a cold apply."""
    assert same_company("The College Board", "College Board")
    assert same_company("Genesis10", "Genesis 10, Inc.")
    assert not same_company("Insight Global", "Global Payments Inc.")


# --- one req, two agencies ---------------------------------------------------------------------

def test_same_jd_under_a_different_company_is_a_distinct_finding(tmp_path):
    """The finding that is hardest to spot by hand: Trident and Themesoft posted the same client req,
    with different titles' framing, different locations and a different years bar. Nothing matches
    except the prose — so if this isn't surfaced, Ben applies to the same job twice through two
    agencies and both submissions get rejected as duplicates by the client."""
    corpus = _corpus(tmp_path, jobs=[
        _job("Trident Consulting", "Agentic AI Developer", TRIDENT_JD),
        _job("Themesoft Inc.", "Agentic AI Developer", THEMESOFT_JD),
        _job("The College Board", "Senior Full Stack Engineer", COLLEGE_BOARD_JD)])
    h = check_my_history("Trident Consulting", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert [s.company for s in h.same_jd] == ["Themesoft Inc."]
    assert h.same_jd[0].overlap >= 0.25
    assert h.same_jd[0].probe_title == "Agentic AI Developer"


def test_a_brand_new_jd_can_be_matched_before_it_has_ever_been_scored(tmp_path):
    """The standalone case: the req in front of Ben right now isn't in the corpus, so there is no
    posting of his own to probe with. Passing the JD is what makes the check work on a first look."""
    corpus = _corpus(tmp_path, jobs=[_job("Themesoft Inc.", "Agentic AI Developer", THEMESOFT_JD)])
    h = check_my_history("Trident Consulting", jd=TRIDENT_JD, corpus_dir=corpus,
                         skiplist=tmp_path / "none.md")
    assert [s.company for s in h.same_jd] == ["Themesoft Inc."]


def test_unrelated_postings_do_not_read_as_the_same_req(tmp_path):
    """The other direction: two full-stack JDs share plenty of vocabulary. If boilerplate tripped the
    threshold, every brief would claim an agency is shopping the req and the finding would be noise."""
    corpus = _corpus(tmp_path, jobs=[
        _job("The College Board", "Senior Full Stack Engineer", COLLEGE_BOARD_JD),
        _job("Themesoft Inc.", "Agentic AI Developer", THEMESOFT_JD)])
    h = check_my_history("The College Board", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert h.same_jd == []


# --- nothing found vs. couldn't look ------------------------------------------------------------

def test_no_history_is_a_real_answer(tmp_path):
    """A company Ben has never touched: found is False, ok is True, and the message says so plainly."""
    h = check_my_history("Acme", corpus_dir=_corpus(tmp_path, jobs=[_job("Other", "Dev")]),
                         skiplist=_skiplist(tmp_path, ""))
    assert not h.found and h.ok
    assert h.detail.startswith("no history with Acme")


def test_an_unreadable_corpus_is_not_a_clean_slate(tmp_path):
    """The failure that costs something here: a corrupt state file reported as "no history" tells Ben
    he has never dealt with these people, which is a claim the module never established."""
    corpus = _corpus(tmp_path)
    (corpus / "state-2026-07-13-102938.json").write_text("{ truncated")
    h = check_my_history("Acme", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert not h.ok and not h.found
    assert h.detail.startswith("⚠ couldn't read")
    assert "no history" not in h.detail


def test_a_broken_applied_cache_is_unreadable_not_empty(tmp_path):
    """applied.json holding something that isn't a list of records parses fine and yields no hits —
    the one shape in which "nothing applied to" and "cache is broken" look identical from outside."""
    corpus = _corpus(tmp_path)
    (corpus / "applied.json").write_text(json.dumps({"rows": []}))
    h = check_my_history("Acme", corpus_dir=corpus, skiplist=tmp_path / "none.md")
    assert not h.ok and "applied record" in h.detail


def test_a_fresh_clone_reports_nothing_recorded_rather_than_a_failure(tmp_path):
    """Cold start (spec §user story 16): no corpus, no skiplist, no applied sheet. That is a clean
    no-history answer, not an error — the tool has to work before setup."""
    empty = tmp_path / "corpus"
    empty.mkdir()
    h = check_my_history("Acme", corpus_dir=empty, skiplist=tmp_path / "none.md")
    assert h.ok and not h.found
    assert "nothing recorded yet" in h.detail
    assert {s.state for s in h.sources} == {"absent"}
