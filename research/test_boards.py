"""Board listing and the cold trail.  Run:  .venv/bin/python -m pytest research/ -q

Offline by rule, like the rest of this repo's suite — every case drives the injected `fetch`.

The failure direction that costs something here is **inventing a source**. An empty board reported as
"nothing open", or a careers URL produced for a domain we never saw, sends Ben to the wrong company's
listings and he acts on it. A reported gap costs him one manual lookup. So the assertions below are
mostly about what the module refuses to claim.
"""
from __future__ import annotations

import json

from .boards import (Posting, board_url, careers_page, guess_company_domain, list_company_jobs)

GREENHOUSE_BOARD = json.dumps({"jobs": [
    {"id": 1, "title": "Senior Full Stack Developer", "location": {"name": "Remote"},
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"},
    {"id": 2, "title": "Platform Engineer", "location": {"name": "Austin, TX"},
     "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"}]})
LEVER_BOARD = json.dumps([
    {"id": "abc", "text": "Backend Engineer", "categories": {"location": "Remote"},
     "hostedUrl": "https://jobs.lever.co/acme/abc"}])
ASHBY_BOARD = json.dumps({"jobs": [
    {"id": "x", "title": "Founding Engineer", "location": "Remote",
     "jobUrl": "https://jobs.ashbyhq.com/acme/x"}]})


def _fake_fetch(pages: dict):
    """A fetch that serves only the URLs it was given — everything else is a shut door."""
    def fetch(url: str) -> str:
        if url not in pages:
            raise RuntimeError(f"404 {url}")
        return pages[url]
    return fetch


def test_board_urls_are_the_per_job_endpoints_with_the_id_dropped():
    """The three endpoints `fetch.py` already parses. A wrong path 404s and looks like 'no board',
    which would silently downgrade every lookup to the cold trail."""
    assert board_url("greenhouse", "acme") == "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    assert board_url("lever", "acme") == "https://api.lever.co/v0/postings/acme?mode=json"
    assert board_url("ashby", "acme") == "https://api.ashbyhq.com/posting-api/job-board/acme"


def test_each_platform_parses_its_own_board_fixture():
    """Each API names the title/location/apply-link fields differently; a mis-mapped url field would
    put a plausible brief in front of Ben with links that go nowhere."""
    for platform, body, want in (
        ("greenhouse", GREENHOUSE_BOARD,
         Posting("Senior Full Stack Developer", "Remote", "https://boards.greenhouse.io/acme/jobs/1")),
        ("lever", LEVER_BOARD,
         Posting("Backend Engineer", "Remote", "https://jobs.lever.co/acme/abc")),
        ("ashby", ASHBY_BOARD,
         Posting("Founding Engineer", "Remote", "https://jobs.ashbyhq.com/acme/x")),
    ):
        r = list_company_jobs("Acme", fetch=_fake_fetch({board_url(platform, "acme"): body}))
        assert r.ok and r.source == platform
        assert r.postings[0] == want


def test_a_board_with_nothing_open_is_an_answer_not_a_failure():
    """The honesty rule runs both ways. This board answered — reporting 'couldn't check' would send
    Ben to do a manual lookup that has already been done."""
    r = list_company_jobs("https://boards.greenhouse.io/acme/jobs/1",
                          fetch=_fake_fetch({board_url("greenhouse", "acme"): '{"jobs": []}'}))
    assert r.ok and r.postings == [] and r.source == "greenhouse"


def test_a_board_link_is_followed_straight_to_its_board():
    """The link you already have names the board — no probing the other two platforms."""
    r = list_company_jobs("https://boards.greenhouse.io/acme/jobs/1",
                          fetch=_fake_fetch({board_url("greenhouse", "acme"): GREENHOUSE_BOARD}))
    assert r.ok and r.company == "acme" and len(r.postings) == 2
    assert r.attempts == [board_url("greenhouse", "acme")]


def test_cold_trail_order_board_then_careers():
    """The order the ticket specifies: all three boards tried first, /careers only after they fail."""
    page = "We're hiring! " + "Open roles at Acme. " * 30
    r = list_company_jobs("https://acme.com/blog/post",
                          fetch=_fake_fetch({"https://r.jina.ai/https://acme.com/careers": page}))
    assert r.ok and r.source == "careers-page" and r.url == "https://acme.com/careers"
    assert r.attempts == [board_url("greenhouse", "acme"), board_url("lever", "acme"),
                          board_url("ashby", "acme"), "https://acme.com/careers"]


def test_an_aggregator_link_names_no_company_so_nothing_is_probed():
    """remotevibecodingjobs and friends host somebody else's posting — there is no slug to try and
    no domain of theirs to read, and neither is invented."""
    r = list_company_jobs("https://remotevibecodingjobs.com/jobs/genesis10-x", fetch=_fake_fetch({}))
    assert not r.ok and r.attempts == [] and r.url == ""


def test_jobs_is_tried_when_careers_is_not_there():
    page = "Open roles. " * 40
    r = careers_page("acme.com", fetch=_fake_fetch({"https://r.jina.ai/https://acme.com/jobs": page}))
    assert r.ok and r.url == "https://acme.com/jobs"
    assert r.attempts == ["https://acme.com/careers", "https://acme.com/jobs"]


def test_cold_trail_ends_in_an_honest_failure_not_an_invented_url():
    """THE property: nothing answered, so nothing is claimed. No URL, no 'nothing open'."""
    r = list_company_jobs("Genesis10", fetch=_fake_fetch({}))
    assert not r.ok and r.url == "" and r.postings == []
    assert "couldn't" in r.detail and "Genesis10" in r.detail


def test_a_bot_walled_careers_page_is_not_content():
    """A Cloudflare interstitial comes back 200 with real length — reusing `_is_block_page` keeps it
    from being reported as the company's careers page."""
    r = careers_page("acme.com", fetch=_fake_fetch({
        "https://r.jina.ai/https://acme.com/careers": "Just a moment... " * 40}))
    assert not r.ok


def test_no_domain_in_the_input_means_no_careers_attempt():
    """A bare company name gives us no domain, and we do not go looking for one."""
    r = careers_page("", fetch=_fake_fetch({}))
    assert not r.ok and r.attempts == []
    assert guess_company_domain("Acme") == ""
