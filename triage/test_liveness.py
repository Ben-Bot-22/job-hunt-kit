"""Minimal tests for the availability check.  Run:  .venv/bin/python -m pytest triage/ -q

Offline only — the marker/status logic is tested directly. Real HTTP is exercised by the live smoke
check in the operator's guide, not by the test suite.

The property that actually matters: an UNREACHABLE page must never be reported CLOSED. A network blip
that silently deletes a good job from the apply list is worse than a stale listing.
"""
from __future__ import annotations

from .liveness import CLOSED, OPEN, UNKNOWN, _is_aggregator


def test_aggregators_are_never_trusted():
    """These hosts show 'Apply' forever. A 200 from them proves nothing about the underlying req."""
    assert _is_aggregator("https://remotevibecodingjobs.com/jobs/genesis10-senior-full-stack-dev-49206afa")
    assert _is_aggregator("https://www.remotevibecodingjobs.com/jobs/x")


def test_dice_is_checkable():
    assert not _is_aggregator("https://www.dice.com/job-detail/e3267a40-c2d3-42d0-b767-f60d4a0acc7c")


def test_linkedin_is_never_reported_open():
    """Measured 2026-07-20: the public page showed no closed-marker for three reqs confirmed closed in
    a signed-in browser. Reporting OPEN there would be a false green light — the worst output."""
    from . import liveness
    state, detail = liveness.check_one("https://www.linkedin.com/jobs/view/4437829090")
    assert state == UNKNOWN and "signed-in" in detail


def test_indeed_is_never_reported_open():
    from . import liveness
    assert liveness.check_one("https://www.indeed.com/viewjob?jk=abc")[0] == UNKNOWN


def test_closed_markers_match_real_pages(monkeypatch):
    """The exact strings LinkedIn and Dice served for the reqs that died during the 7/13->7/20 gap."""
    from . import liveness

    cases = [
        ("Agentic AI Developer ... Remote Contract No longer accepting applications", CLOSED),  # LinkedIn
        ("Senior Full Stack ... Sorry this job is no longer available. Similar Jobs", CLOSED),   # Dice
        ("Senior Full Stack Developer - Remote at Genesis10 ... Apply for this position", OPEN),
    ]
    for body, want in cases:
        monkeypatch.setattr(liveness.httpx, "get",
                            lambda *a, **k: type("R", (), {"status_code": 200, "text": body})())
        assert liveness.check_one("https://boards.greenhouse.io/x/jobs/1")[0] == want


def test_gone_status_is_closed(monkeypatch):
    """Dice returned 410 for expired postings during the 2026-07-20 run."""
    from . import liveness
    monkeypatch.setattr(liveness.httpx, "get",
                        lambda *a, **k: type("R", (), {"status_code": 410, "text": ""})())
    assert liveness.check_one("https://www.dice.com/job-detail/x")[0] == CLOSED


def test_network_failure_is_unknown_not_closed(monkeypatch):
    """THE safety property: never let a network blip delete a live job from the apply list."""
    from . import liveness

    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(liveness.httpx, "get", boom)
    state, detail = liveness.check_one("https://boards.greenhouse.io/x/jobs/1")
    assert state == UNKNOWN and "unreachable" in detail


def test_bot_wall_is_unknown(monkeypatch):
    """Indeed's Cloudflare interstitial returns 200 with real length — it is not evidence of closure."""
    from . import liveness
    monkeypatch.setattr(liveness.httpx, "get", lambda *a, **k: type(
        "R", (), {"status_code": 200, "text": "Just a moment... Additional Verification Required"})())
    assert liveness.check_one("https://boards.greenhouse.io/x/jobs/1") == (UNKNOWN, "bot-walled")


def test_no_link_is_unknown():
    from . import liveness
    assert liveness.check_one("")[0] == UNKNOWN
