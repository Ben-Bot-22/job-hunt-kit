"""The `boards` channel: a watchlist of Greenhouse and Lever boards, in, exact postings out.
Run:  .venv/bin/python -m pytest triage/ -q

Everything here is offline. `boards.fetch` takes its watchlist and its HTTP call as keyword arguments
for exactly that reason — the one thing it does that touches the world is a GET against a keyless
public listing endpoint, and it is injected here, so these are real end-to-end assertions about the
channel rather than assertions about a mock of it.

The payloads below are trimmed copies of **real observed responses** (Anthropic's Greenhouse board and
Lever's public demo board, fetched 2026-07-22). Field names, nesting, units and escaping are verbatim,
because those are the only things a fixture can get wrong in a way that matters: `min_cents` is cents
and Lever's `salaryRange.min` is not, Greenhouse's `content` is HTML *escaped*, and Lever states no
company name at all. Only the timestamps are relative to now — pinning those would make the freshness
window fail on a date rather than on a defect.

The failure directions, in the order they cost something:

  * **A board erroring and taking the others with it.** This channel's whole promise is that a
    watchlist has no scraper rot; a mistyped token that costs the run every other board's postings
    would trade one kind of fragility for another.
  * **Losing the employer's own pay numbers.** They arrive free in the listing and are the reason this
    channel beats mail. If they don't reach the JD text, the analyzer estimates a rate the employer
    already stated.
  * **A board job re-surfacing every morning.** Its identity is the API's own company and title, so
    the existing `seen` cache catches it — but only if the channel keeps the API's strings instead of
    inventing its own.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from core.models import composite_id, normalize_link

from . import channels
from .channels import boards


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


_GH_URL = boards._GREENHOUSE_LIST.format(token="anthropic")
_LEVER_URL = boards._LEVER_LIST.format(token="leverdemo")

# One Greenhouse posting, verbatim in shape: `content` HTML-escaped, `pay_input_ranges` in cents behind
# `?pay_transparency=true`, company and title stated, location nested under `location.name`.
_GH_PAID = {
    "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/5215052008?gh_src=abc",
    "company_name": "Anthropic",
    "title": "Amazon GTM Partnership, Startups",
    "location": {"name": "San Francisco, CA | New York City, NY | Seattle, WA"},
    "first_published": _ago(1).isoformat(),
    "updated_at": _ago(0.5).isoformat(),
    "pay_input_ranges": [{"min_cents": 26500000, "max_cents": 36500000,
                          "currency_type": "USD", "title": "Annual Salary:"}],
    "content": "&lt;p&gt;Anthropic&#39;s mission is to create reliable, interpretable, and steerable AI "
               "systems. You will own partnership strategy end to end, working with startups across "
               "the ecosystem, and you will write a great deal of Python along the way.&lt;/p&gt;",
}

# The same board's second posting: no published range, and outside a 3-day window.
_GH_STALE = {
    "absolute_url": "https://job-boards.greenhouse.io/anthropic/jobs/1111111111",
    "company_name": "Anthropic",
    "title": "Research Engineer, Interpretability",
    "location": {"name": "Remote - US"},
    "first_published": _ago(40).isoformat(),
    "updated_at": _ago(0.1).isoformat(),      # edited today — this must NOT make it fresh
    "pay_input_ranges": [],
    "content": "&lt;p&gt;We are looking for a research engineer to work on interpretability. Strong "
               "Python, strong writing, and a great deal of curiosity about what models are doing "
               "internally.&lt;/p&gt;",
}

# One Lever posting, verbatim in shape: title under `text`, no company field anywhere, `createdAt` in
# epoch MILLIseconds, `salaryRange` in whole units with a slug interval, body split across
# `descriptionPlain` and `lists`.
_LEVER_PAID = {
    "hostedUrl": "https://jobs.lever.co/leverdemo/c559265a-55ec-4f75-ac56-78290081f6e7",
    "applyUrl": "https://jobs.lever.co/leverdemo/c559265a-55ec-4f75-ac56-78290081f6e7/apply",
    "text": "Account Executive",
    "categories": {"location": "Amsterdam, Netherlands", "team": "Customer Success"},
    "createdAt": int(_ago(2).timestamp() * 1000),
    "workplaceType": "remote",
    "salaryRange": {"min": 10000, "max": 125000, "currency": "USD", "interval": "per-year-salary"},
    "descriptionPlain": "We are hiring an account executive to own the full sales cycle in EMEA, "
                        "working closely with customer success and with the product team.",
    "lists": [{"text": "Requirements", "content": "<li>Five years of quota-carrying experience</li>"
                                                  "<li>Fluent Dutch and English</li>"}],
}


def _fake_get(payloads: dict[str, object]):
    """Stands in for `core.fetch._get(...).json()` — same contract: return decoded JSON, or raise the
    way `raise_for_status` does, which is how a dead board token actually reaches us."""
    def get(url: str):
        if url not in payloads:
            raise httpx.HTTPStatusError("404 Not Found", request=None, response=None)  # type: ignore
        return payloads[url]
    return get


def _both():
    return _fake_get({_GH_URL: {"jobs": [_GH_PAID, _GH_STALE]}, _LEVER_URL: [_LEVER_PAID]})


_WATCHLIST = {"greenhouse": ["anthropic"], "lever": ["leverdemo"]}


# --- the postings themselves ----------------------------------------------------------------------

def test_a_configured_watchlist_produces_postings_from_both_ats() -> None:
    """The channel's first-order promise: name boards, get new postings. Two boards, two APIs, one
    list of `Job`s — and nothing in between asked for a key."""
    jobs = boards.fetch(3, boards=_WATCHLIST, get=_both())
    assert [(j.company, j.title, j.source_platform) for j in jobs] == [
        ("Anthropic", "Amazon GTM Partnership, Startups", "greenhouse"),
        ("Leverdemo", "Account Executive", "lever"),
    ]


def test_company_and_title_come_from_the_api_so_identity_needs_no_backfill() -> None:
    """The reason `boards` must not copy `paste`'s fetch-and-backfill shape (stage 4 · 03).

    A pasted URL has neither field, so it takes `Job.id`'s link fallback and needs a model call to earn
    a composite. A board states both, so the job's id is the ordinary composite the whole `seen`/
    `applied` corpus is keyed on — the moment it is created, with no model in the loop.
    """
    gh, lever = boards.fetch(3, boards=_WATCHLIST, get=_both())
    assert gh.id == composite_id("Anthropic", "Amazon GTM Partnership, Startups")
    assert gh.id == "anthropic|amazon gtm partnership startups|"
    assert lever.id == "leverdemo|account executive|"
    assert "://" not in gh.id and "://" not in lever.id      # not the link fallback


def test_an_already_seen_posting_is_not_resurfaced() -> None:
    """Runs `__main__._phase1`'s actual blocklist expression against a `seen` set built from yesterday's
    run. Failure direction: a board republishing its whole list turns every morning into 400 jobs Ben
    already rejected — the channel is a watchlist, so it re-reads the same board every single day."""
    jobs = boards.fetch(3, boards=_WATCHLIST, get=_both())
    blocked = {jobs[0].id}
    fresh = [j for j in jobs
             if j.id not in blocked and f"url:{normalize_link(j.link)}" not in blocked]
    assert [j.title for j in fresh] == ["Account Executive"]


def test_identity_is_stable_across_runs_of_the_same_board() -> None:
    """Two fetches of an unchanged board give the same ids, so `seen` keeps working. Failure direction:
    anything derived from fetch order, a timestamp or the tracking param on the apply URL."""
    first = boards.fetch(3, boards=_WATCHLIST, get=_both())
    second = boards.fetch(3, boards=_WATCHLIST, get=_both())
    assert [j.id for j in first] == [j.id for j in second]


def test_the_greenhouse_tracking_param_does_not_fork_the_link() -> None:
    """`?gh_src=` is provenance, not identity — the fixture carries the one a real board hands out."""
    gh = boards.fetch(3, boards={"greenhouse": ["anthropic"]}, get=_both())[0]
    assert gh.link == "https://job-boards.greenhouse.io/anthropic/jobs/5215052008?gh_src=abc"
    assert f"url:{normalize_link(gh.link)}" != "url:"


# --- the pay ranges -------------------------------------------------------------------------------

def test_the_employer_stated_greenhouse_range_reaches_the_jd_the_analyzer_reads() -> None:
    """Cents to units, and the employer's own label kept verbatim so the interval is theirs, not ours.

    It goes into `jd_text` rather than a new field on purpose: the analyzer's `rate` is read out of the
    JD, so a range parked somewhere nothing renders is captured and then never used.
    """
    gh = boards.fetch(3, boards={"greenhouse": ["anthropic"]}, get=_both())[0]
    assert "Compensation (employer-stated): Annual Salary: 265,000–365,000 USD" in gh.jd_text


def test_the_employer_stated_lever_range_is_not_read_as_cents() -> None:
    """Lever's `salaryRange.min` is whole units where Greenhouse's `min_cents` is cents. Dividing this
    one by 100 would advertise a $125k role at $1,250 and the analyzer would skip it on rate."""
    lever = boards.fetch(3, boards={"lever": ["leverdemo"]}, get=_both())[0]
    assert "Compensation (employer-stated): Pay range: 10,000–125,000 USD per year" in lever.jd_text


def test_a_posting_with_no_published_range_gets_no_compensation_line() -> None:
    """Most employers publish nothing. An empty `pay_input_ranges` must produce silence, not a line
    reading `0–0` that the analyzer would take as a stated rate of zero."""
    stale = boards.fetch(0, boards={"greenhouse": ["anthropic"]}, get=_both())[1]
    assert stale.title == "Research Engineer, Interpretability"
    assert "Compensation" not in stale.jd_text


def test_the_board_states_company_location_and_date_above_the_description() -> None:
    gh = boards.fetch(3, boards={"greenhouse": ["anthropic"]}, get=_both())[0]
    head = gh.jd_text.splitlines()[:4]
    assert head[0] == "Amazon GTM Partnership, Startups — Anthropic"
    assert head[1] == "Location: San Francisco, CA | New York City, NY | Seattle, WA"
    assert head[3] == f"Posted: {_ago(1).date().isoformat()}"
    assert gh.posted_hint == _ago(1).date().isoformat()


def test_the_stated_pay_line_cannot_trip_the_deterministic_prefilter() -> None:
    """The header is prepended to text the free regex gate reads. Its year rule needs the word
    'experience' adjacent and its travel rule needs the word 'travel', so a `265,000` and a `Posted:`
    date are inert — but this is the assertion that says so, because a header that silently hard-skips
    every board job would look exactly like a board supplying nothing."""
    from . import prefilter
    gh = boards.fetch(3, boards={"greenhouse": ["anthropic"]}, get=_both())[0]
    assert prefilter.hard_skip(gh) is None


# --- the JD arrives with the listing --------------------------------------------------------------

def test_the_description_comes_back_with_the_listing_so_nothing_is_fetched_twice() -> None:
    """One HTTP call per board, not one per posting. The job enters the pipeline already `full`, and
    `__main__._fetch` leaves a full job alone — the same guard `paste` relies on. Failure direction:
    a 400-posting board costing 401 requests every morning and getting rate-limited for it."""
    from .__main__ import _fetch
    calls: list[str] = []
    get = _both()
    jobs = boards.fetch(3, boards=_WATCHLIST, get=lambda u: (calls.append(u), get(u))[1])
    assert len(calls) == 2                                   # one per board, whatever the posting count
    assert [j.jd_source for j in jobs] == ["full", "full"]
    assert _fetch(jobs[0]).jd_text == jobs[0].jd_text        # no second round trip


def test_greenhouse_content_is_unescaped_by_the_shared_parser() -> None:
    """Greenhouse double-encodes: `&lt;p&gt;` in the JSON. The channel reuses `core.fetch`'s parser
    rather than writing a second one, so this asserts the escaping is actually undone — the failure is
    silent and ugly, an analyzer reading raw entity soup as the job description."""
    gh = boards.fetch(3, boards={"greenhouse": ["anthropic"]}, get=_both())[0]
    assert "&lt;" not in gh.jd_text and "<p>" not in gh.jd_text
    assert "reliable, interpretable, and steerable AI systems" in gh.jd_text


def test_lever_list_blocks_reach_the_jd_because_that_is_where_requirements_live() -> None:
    """Lever splits the body: prose in `descriptionPlain`, requirements and benefits in `lists`.
    Dropping the lists loses the half a rubric actually screens on."""
    lever = boards.fetch(3, boards={"lever": ["leverdemo"]}, get=_both())[0]
    assert "own the full sales cycle" in lever.jd_text
    assert "Requirements" in lever.jd_text and "Fluent Dutch and English" in lever.jd_text


# --- isolation and the window ---------------------------------------------------------------------

def test_a_board_that_errors_does_not_cost_the_other_boards() -> None:
    """The registry already isolates the CHANNEL; this isolates each BOARD inside it. A mistyped token
    or a company that deleted its board must cost that company's postings and nothing else."""
    watchlist = {"greenhouse": ["anthropic", "typo-not-a-board"], "lever": ["leverdemo"]}
    jobs = boards.fetch(3, boards=watchlist, get=_both())
    assert [j.company for j in jobs] == ["Anthropic", "Leverdemo"]


def test_every_board_failing_is_an_empty_list_and_not_an_exception() -> None:
    """It would be caught by the registry and reported as `boards CRASHED`, which reads as "you are
    missing jobs". A watchlist where every token happens to be down is a `boards 0`."""
    assert boards.fetch(3, boards=_WATCHLIST, get=_fake_get({})) == []


def test_an_unknown_ats_key_is_skipped_rather_than_crashing_the_channel() -> None:
    jobs = boards.fetch(3, boards={"greenouse": ["anthropic"], "lever": ["leverdemo"]}, get=_both())
    assert [j.company for j in jobs] == ["Leverdemo"]


def test_a_posting_outside_the_freshness_window_is_not_returned() -> None:
    """And `updated_at` does not rescue it: the stale fixture was edited today and first published 40
    days ago. Freshness is when the posting went live, otherwise a typo fix reads as a new job."""
    fresh = boards.fetch(3, boards=_WATCHLIST, get=_both())
    assert "Research Engineer, Interpretability" not in [j.title for j in fresh]
    everything = boards.fetch(0, boards=_WATCHLIST, get=_both())
    assert "Research Engineer, Interpretability" in [j.title for j in everything]


def test_sample_caps_the_run_so_a_watchlist_can_be_smoke_tested() -> None:
    assert len(boards.fetch(0, sample=1, boards=_WATCHLIST, get=_both())) == 1


def test_an_undated_posting_is_kept_rather_than_dropped() -> None:
    """A board that states no dates would otherwise go permanently silent, which is unrecoverable
    without noticing. Keeping it costs one noisy first run; `seen` handles it from the second."""
    undated = {**_GH_PAID, "first_published": None, "updated_at": None}
    jobs = boards.fetch(3, boards={"greenhouse": ["anthropic"]},
                        get=_fake_get({_GH_URL: {"jobs": [undated]}}))
    assert [j.title for j in jobs] == ["Amazon GTM Partnership, Startups"]
    assert jobs[0].posted_hint == ""


def test_a_posting_with_no_link_or_no_title_is_dropped() -> None:
    """No link means nothing to apply to. No title is worse than it looks: the company falls back to
    the board token, so every title-less posting on one board would share the id `<token>||` — stage
    4 · 01's `"||"` collision wearing a board's name."""
    junk = {"jobs": [{"absolute_url": "", "title": "No link", "content": "x" * 200},
                     {"absolute_url": "https://job-boards.greenhouse.io/a/jobs/9", "content": "x" * 200},
                     "not even a dict"]}
    assert boards.fetch(0, boards={"greenhouse": ["a"]},
                        get=_fake_get({boards._GREENHOUSE_LIST.format(token="a"): junk})) == []


# --- the registry ---------------------------------------------------------------------------------

def test_boards_is_registered_between_mail_and_paste() -> None:
    """Registry order decides which channel's copy of a duplicate posting survives the collapse, and
    the order encodes what each copy is worth: mail's carries an `email_mid` and can archive; a
    board's carries employer-stated company, title and pay; a paste's carries model-backfilled guesses.
    """
    assert list(channels.ALL) == ["mail", "boards", "agencies", "paste", "gmail"]  # the stub is last
    assert channels.ALL["boards"] is boards.fetch


def test_the_configured_watchlist_is_empty_by_default() -> None:
    """A fresh clone must not start hitting other people's boards because a channel defaults to on."""
    from . import config
    assert config.board_tokens() == {"greenhouse": [], "lever": []}
