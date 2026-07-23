"""The research loop and the brief.  Run:  .venv/bin/python -m pytest research/ -q

Offline by rule, like the rest of this repo's suite: every case drives an injected `fetch` and a
scripted `model`, which is the entire reason both are parameters.

Three failure directions are worth the test:

  1. **An uncapped loop.** A model that always asks for one more lookup burns tokens and wall-clock
     on a company with a large board, and Ben is sitting there waiting on it.
  2. **Inventing a source.** A careers page reported for a domain we never saw sends him to another
     company's listings and he acts on it; "couldn't check" costs him one manual lookup.
  3. **A silent gap.** Anything the tools couldn't answer that never reaches "Open questions" reads
     as a clean result — which is the one thing this brief must never do.
"""
from __future__ import annotations

import json
from pathlib import Path

from .agent import MAX_PASSES, Decision, _dedupe_questions, keyless_plan, research_company

NOWHERE = Path("/nonexistent-corpus-for-tests")
NO_SKIPLIST = NOWHERE / "skiplist.md"

GREENHOUSE_BOARD = json.dumps({"jobs": [
    {"id": 1, "title": "Senior Full Stack Developer", "location": {"name": "Remote"},
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"}]})


def _dead_fetch(url: str) -> str:
    """Every door shut — a 404 on the boards, a raise on the reader."""
    raise RuntimeError(f"404 {url}")


def _pages(pages: dict):
    def fetch(url: str) -> str:
        if url not in pages:
            raise RuntimeError(f"404 {url}")
        return pages[url]
    return fetch


def _scripted(*decisions: Decision):
    """A model that plays the given decisions in order, then stops."""
    queue = list(decisions)

    def model(view: str) -> Decision:
        return queue.pop(0) if queue else Decision(action="stop", why="script exhausted")
    return model


def _always_more(action="list_jobs", argument="Acme"):
    """The runaway: never satisfied, always one more lookup. Counts how often it was consulted."""
    calls = []

    def model(view: str) -> Decision:
        calls.append(view)
        return Decision(action=action, argument=argument, why="one more")
    return model, calls


def _research(target, **kw):
    kw.setdefault("corpus_dir", NOWHERE)
    kw.setdefault("skiplist", NO_SKIPLIST)
    return research_company(target, **kw)


def test_a_model_that_never_stops_is_stopped_at_three_passes():
    """The cap is enforced by the loop, not trusted to the model. Without it a bad planning turn is
    an unbounded bill and an unbounded wait on a run Ben is watching."""
    model, calls = _always_more()
    brief = _research("Acme", fetch=_dead_fetch, model=model)

    assert brief.state.passes == MAX_PASSES == 3
    assert len(brief.state.lookups) == 3
    # Consulted once per pass plus the turn where the cap fires and the model is never asked.
    assert len(calls) == 3
    assert brief.state.capped
    assert any("cap" in q for q in brief.open_questions), brief.open_questions


def test_board_and_careers_pages_unreachable_reports_the_gap_and_invents_nothing():
    """The failure direction that costs something: a confidently wrong careers page. With every door
    shut the brief must say so — and must not name a URL it never got an answer from."""
    brief = _research("Acme", fetch=_dead_fetch,
                      model=_scripted(Decision(action="list_jobs", argument="Acme")))

    assert "couldn't find open roles for Acme" in brief.markdown
    assert "nothing open" not in brief.markdown          # a gap is not an answer
    assert "acme.com/careers" not in brief.markdown      # never guessed, so never quoted as a source
    assert any("what else do they have open" in q for q in brief.open_questions)


def test_a_board_that_answers_empty_is_a_real_answer_not_a_gap():
    """`ok` with zero postings means 'nothing open', which is different from 'couldn't look'. Reading
    them as the same thing is what makes a tool untrustworthy in both directions."""
    fetch = _pages({"https://boards-api.greenhouse.io/v1/boards/acme/jobs": json.dumps({"jobs": []})})
    brief = _research("Acme", fetch=fetch,
                      model=_scripted(Decision(action="list_jobs", argument="Acme")))

    assert "has nothing open right now" in brief.markdown
    assert not any("what else do they have open" in q for q in brief.open_questions)


def test_an_unanswerable_question_reaches_open_questions_verbatim():
    """The model's own "I couldn't work this out" is the whole interface to the driving agent. If it
    is dropped on the `stop` turn — the turn where it is most likely to be raised — the brief reads
    as complete when it isn't."""
    unanswerable = "What rate is this req actually paying? The posting doesn't say."
    brief = _research("Acme", fetch=_dead_fetch,
                      model=_scripted(Decision(action="stop", why="nothing reachable",
                                               open_questions=[unanswerable])))

    assert unanswerable in brief.open_questions
    assert unanswerable in brief.markdown


def test_every_unresolved_item_reaches_open_questions_even_when_the_model_raises_none():
    """A gap the model never mentions is still a gap. Nothing looked up at all must produce three
    honest questions, not an empty checklist."""
    brief = _research("Acme", fetch=_dead_fetch,
                      model=_scripted(Decision(action="stop", why="not even trying")))

    joined = " ".join(brief.open_questions)
    assert "direct employer, or an agency" in joined     # who they are
    assert "currently have open" in joined               # what's on the board
    assert "dealt with Acme before" in joined            # the local record
    assert brief.state.passes == 0


def test_a_failed_page_read_is_reported_in_the_couldnt_fetch_voice():
    """`read_page` returning "" covers a raise, a bot-wall and a stub page alike. All three are
    "couldn't fetch", and none of them may pass as "read it, nothing there"."""
    brief = _research("https://remotevibecodingjobs.com/jobs/123", fetch=_dead_fetch,
                      model=_scripted(Decision(action="read_page",
                                               argument="https://remotevibecodingjobs.com/jobs/123")))

    assert "⚠ couldn't read https://remotevibecodingjobs.com/jobs/123" in brief.markdown
    assert any("couldn't read" in q for q in brief.open_questions)


def test_the_loop_pivots_on_what_it_reads_and_calls_the_agency_by_its_evidence():
    """The Genesis10 case: no board is reachable, the agency page then says whose req it is, and the
    brief must quote the line it decided on rather than asserting 'agency' bare."""
    page = ("Genesis10 is a professional technology services firm. We are seeking a Full Stack "
            "Developer for our client, a Major Financial Institution, on a 12-month contract. "
            "Genesis10 places consultants with Fortune 500 organizations across the United States "
            "and offers benefits including medical, dental and vision coverage to its consultants.")
    fetch = _pages({"https://r.jina.ai/https://genesis10.com/careers": page})
    brief = _research("Genesis10", fetch=fetch, model=_scripted(
        Decision(action="list_jobs", argument="Genesis10"),
        Decision(action="read_page", argument="https://genesis10.com/careers"),
        Decision(action="stop", why="employer resolved")))

    assert brief.employer == "agency"
    assert "our client" in brief.employer_why
    assert "genesis10.com/careers" in brief.employer_why


def test_undetermined_is_said_out_loud_rather_than_guessed():
    """A board answering under their name is not evidence of a direct employer — an agency has a
    board too. Guessing 'direct' here tells Ben he's talking to the decision-maker when he isn't."""
    fetch = _pages({"https://boards-api.greenhouse.io/v1/boards/acme/jobs": GREENHOUSE_BOARD})
    brief = _research("Acme", fetch=fetch,
                      model=_scripted(Decision(action="list_jobs", argument="Acme")))

    assert brief.employer == "undetermined"
    assert "Undetermined" in brief.markdown
    assert any("direct employer, or an agency" in q for q in brief.open_questions)


def test_history_findings_land_in_the_brief(tmp_path):
    """The missed hit is the expensive one: cold-applying somewhere already in process. A history
    lookup that finds something must show it, with the note Ben wrote."""
    (tmp_path / "applied.json").write_text(json.dumps([
        {"company": "The College Board", "title": "Senior Full Stack Engineer",
         "apply_date": "2026-07-10", "note": "panel scheduled 7/17"}]))
    brief = _research("College Board", corpus_dir=tmp_path, skiplist=tmp_path / "skiplist.md",
                      fetch=_dead_fetch,
                      model=_scripted(Decision(action="check_history", argument="College Board")))

    assert "**Applied** 2026-07-10" in brief.markdown
    assert "panel scheduled 7/17" in brief.markdown


def test_a_planner_that_dies_still_produces_a_brief_that_says_so():
    """The planner is a network call like any other. Its failure must degrade to the honest partial
    brief, not to an exception in the middle of a triage run."""
    def broken(view: str) -> Decision:
        raise RuntimeError("connection reset")

    brief = _research("Acme", fetch=_dead_fetch, model=broken)

    assert "# Acme" in brief.markdown
    assert any("couldn't reach the planning model" in q for q in brief.open_questions)


def test_with_no_key_the_default_checks_still_run_and_the_brief_says_nothing_pivoted():
    """The cold clone (user stories 16–17): no key, and a brief still comes out. What's lost is the
    pivot, and the loss must be stated — a fixed-order brief that reads like a planned one is the
    version of this that quietly misleads."""
    brief = _research("Acme", fetch=_dead_fetch, model=keyless_plan("Acme"))

    assert [l.action for l in brief.state.lookups] == ["list_jobs", "check_history"]
    assert any("No planning model was available" in q for q in brief.open_questions)


def test_the_no_planner_notice_survives_a_url_target_where_the_cap_fires_first():
    """A URL target spends all three passes on the default checks, so the cap stops the loop before
    any `stop` of ours is reached. The notice is raised on the first turn for exactly that reason —
    and this is the mode the skill tells the agent to prefer, so losing it there loses it always."""
    brief = _research("https://remotevibecodingjobs.com/jobs/123", fetch=_dead_fetch,
                      model=keyless_plan("https://remotevibecodingjobs.com/jobs/123"))

    assert [l.action for l in brief.state.lookups] == ["read_page", "list_jobs", "check_history"]
    assert any("No planning model was available" in q for q in brief.open_questions)


def test_the_brief_documents_the_three_ways_to_answer_its_open_questions():
    """The open-questions list is the interface; without the three paths written next to it, the
    reader has a checklist and no idea who is supposed to close it."""
    brief = _research("Acme", fetch=_dead_fetch, model=_scripted(Decision(action="stop")))

    assert "PERPLEXITY_API_KEY" in brief.markdown
    assert "own web search" in brief.markdown


# --- the planner restates itself across passes -------------------------------------------------------

# Verbatim from the first live `research_company("Genesis10")` (2026-07-21) — the run the ticket owed.
# Pass 1 and pass 2 both asked who the end client was, in different words, and both reached the brief.
_LIVE_GENESIS10_QUESTIONS = [
    "Who is the actual end client behind Genesis10's 'Senior Full Stack Developer - Remote' req "
    "(agencies rarely name the employer)?",
    "Is the STRONG_FIT 90 role still open, or already filled/expired since it was seen 2026-07-20?",
    "Who is the actual end client behind Genesis10's 'Senior Full Stack Developer - Remote' "
    "placement? (web search Genesis10 + the JD text to find the real employer)",
    "Is the already-scored 'Senior Full Stack Developer - Remote' (STRONG_FIT 90) the same req as "
    "this Genesis10 posting, or a distinct role?",
]


def test_a_restated_question_is_dropped_and_the_first_phrasing_kept():
    """Three passes each emit their own open_questions and they are concatenated, so an unclosed gap
    gets asked again in different words. Exact-match dedup never fired on it. Seven questions where
    five were meant reads as a longer to-do list than the research actually produced."""
    out = _dedupe_questions(_LIVE_GENESIS10_QUESTIONS)

    assert len(out) == 3
    assert out[0] == _LIVE_GENESIS10_QUESTIONS[0]          # first phrasing wins
    assert not any("web search Genesis10 + the JD text" in q for q in out)


def test_two_questions_about_one_subject_both_survive():
    """The failure direction that costs something. A dropped duplicate costs one redundant line; a
    dropped *distinct* question costs a gap Ben never sees — so 'is it still open?' and 'is it the
    same req?' both stay, even though both are about the same posting."""
    out = _dedupe_questions(_LIVE_GENESIS10_QUESTIONS)

    assert any("still open, or already filled" in q for q in out)
    assert any("same req as this Genesis10 posting" in q for q in out)


def test_dedupe_is_stable_on_edge_shapes():
    assert _dedupe_questions([]) == []
    assert _dedupe_questions(["short one", "short one"]) == ["short one", "short one"]  # < 4 words: no shingles, kept
    assert _dedupe_questions(["a b c d e", "a b c d e"]) == ["a b c d e"]
