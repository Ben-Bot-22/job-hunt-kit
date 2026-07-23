"""Brief caching.  Run:  .venv/bin/python -m pytest research/ -q

Two failure directions are worth the test, and they point in opposite directions:

  1. **A stale brief served as current.** "What have they got open" answered from three weeks ago
     sends Ben at a req that closed a fortnight back — the cache would be actively lying, which is
     worse than not caching at all.
  2. **A cache that never hits.** The whole reason it exists is that the same dozen agencies recur
     all month; a key that varies with spelling means every lookup pays full price.
"""
from __future__ import annotations

from datetime import date

from . import cache
from .agent import Brief


def _brief(company="TEKsystems", researched="2026-07-20", markdown="# TEKsystems\n\nbody"):
    return Brief(company=company, markdown=markdown, employer="agency",
                 employer_why="the name itself reads as an agency", researched=researched,
                 open_questions=["What rate is this paying?"])


def test_a_fresh_brief_is_served_from_disk(tmp_path):
    """The recurring-agency case: same name next week, no network, no planner call."""
    cache.save(_brief(), target="TEKsystems", cache_dir=tmp_path)

    hit = cache.load("TEKsystems", cache_dir=tmp_path, today=date(2026, 7, 27))

    assert hit is not None
    assert hit.age_days == 7
    assert hit.brief.from_cache and hit.brief.employer == "agency"
    assert hit.brief.open_questions == ["What rate is this paying?"]


def test_a_stale_brief_is_a_miss_so_the_caller_looks_again(tmp_path):
    """Past the window there is no half-answer: `None`, and the caller re-fetches. A brief from
    three weeks ago answers "still open?" from a world that has moved on."""
    cache.save(_brief(), target="TEKsystems", cache_dir=tmp_path)

    assert cache.load("TEKsystems", cache_dir=tmp_path, today=date(2026, 8, 20)) is None
    # ...and the window is a parameter, so a caller who wants today's answer can demand it.
    assert cache.load("TEKsystems", cache_dir=tmp_path, max_age_days=0,
                      today=date(2026, 7, 21)) is None


def test_the_key_survives_the_spelling_and_a_url_keys_on_the_company_domain(tmp_path):
    """A key that varies with punctuation is a cache that never hits. A company URL keys on the
    company, so the link and the name are one file — an aggregator link, which carries no company
    domain, keys on itself rather than on a name we'd have to invent."""
    cache.save(_brief(), target="TEKsystems", cache_dir=tmp_path)

    assert cache.load("teksystems, inc.", cache_dir=tmp_path, today=date(2026, 7, 21)) is not None
    assert cache.cache_key("https://jobs.teksystems.com/roles/91") == "teksystems"
    assert cache.cache_key("https://remotevibecodingjobs.com/jobs/123") == \
        "remotevibecodingjobs-com-jobs-123"


def test_a_link_that_resolves_a_name_is_findable_under_that_name_afterwards(tmp_path):
    """The aggregator case: the link carries no company, the lookups resolve Genesis10, and asking
    about "Genesis10" by name next week must not pay full price for a brief already on disk. One
    brief under the name, a one-line alias under the link — never two copies ageing separately."""
    link = "https://remotevibecodingjobs.com/jobs/123"
    path = cache.save(_brief(company="Genesis10"), target=link, cache_dir=tmp_path)

    assert path.name == "genesis10.json"
    for asked in ("Genesis10", link):
        hit = cache.load(asked, cache_dir=tmp_path, today=date(2026, 7, 21))
        assert hit is not None and hit.brief.company == "Genesis10", asked

    # ...and answers written against the link land on the brief itself, not on the pointer.
    cache.append_answers(link, "- Client is a bank; not named in the posting.", cache_dir=tmp_path)
    assert "not named in the posting" in cache.load("Genesis10", cache_dir=tmp_path,
                                                    today=date(2026, 7, 21)).brief.markdown


def test_an_alias_pointing_nowhere_is_a_miss(tmp_path):
    """A hand-cleared `data/research/` leaves pointers behind. A dangling one means look it up
    again — the one thing it must not do is raise in the middle of a batch over the top picks."""
    link = "https://remotevibecodingjobs.com/jobs/9"
    (tmp_path / f"{cache.cache_key(link)}.json").write_text('{"alias": "gone"}')

    assert cache.load(link, cache_dir=tmp_path) is None


def test_an_unreadable_cache_file_is_a_miss_not_a_crash(tmp_path):
    """Corrupt, half-written or written by an older shape — all of them mean "look it up again",
    never an exception in the middle of a batch over the top picks."""
    (tmp_path / "acme.json").write_text("{not json")

    assert cache.load("Acme", cache_dir=tmp_path) is None


def test_agent_answers_fold_into_the_cached_brief_and_dont_stack(tmp_path):
    """Path 2 — the driving agent answers the open questions with its own web search. Writing them
    back is what makes that work paid once; re-answering replaces the section rather than appending
    a second copy of it."""
    cache.save(_brief(), target="TEKsystems", cache_dir=tmp_path)

    cache.append_answers("TEKsystems", "- Rate: $70–80/hr per two 2026 postings", cache_dir=tmp_path)
    cache.append_answers("TEKsystems", "- Rate: $75/hr, confirmed", cache_dir=tmp_path)

    hit = cache.load("TEKsystems", cache_dir=tmp_path, today=date(2026, 7, 21))
    assert hit.brief.markdown.count("## Answered by the agent") == 1
    assert "confirmed" in hit.brief.markdown
    assert "# TEKsystems" in hit.brief.markdown          # the brief itself survives the answers
