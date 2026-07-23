"""Alert vs. live-correspondence classification.  Run:  .venv/bin/python -m pytest triage/ -q

Guards the 2026-07-20 findings. Both failure directions cost something real, but they are NOT symmetric:

  * correspondence misread as an alert -> a live thread gets archived out of the inbox, and a role Ben
    is already interviewing for is presented as a fresh lead to cold-apply to.
  * an alert misread as correspondence -> one email stays in the inbox. Harmless.

So the classifier is default-safe: anything not provably automated is treated as correspondence.
"""
from __future__ import annotations

from .channels.common import _is_correspondence, archive_list_lines
from core.models import Job


def _em(sender: str, is_reply: bool = False) -> dict:
    return {"sender": sender, "is_reply": is_reply, "mid": "<x@y>"}


# --- automated alerts (safe to archive) -------------------------------------------------------------

def test_job_alert_senders_are_automated():
    for s in ["LinkedIn <jobalerts-noreply@linkedin.com>",
              "Indeed <alert@indeedemail.com>",
              "Dice <noreply@dice.com>",
              "ZipRecruiter <no-reply@ziprecruiter.com>",
              "Glassdoor <noreply@glassdoor.com>",
              "Some Board <do-not-reply@example.com>",
              "Digest <notifications@example.com>"]:
        assert not _is_correspondence(_em(s)), s


# --- live correspondence (never archive, never a fresh lead) ----------------------------------------

def test_human_recruiter_is_correspondence():
    """Motion Recruitment's College Board thread — Ben was mid-interview-process when it ranked #2."""
    assert _is_correspondence(_em("Shivam Awasthi <shivam@motionrecruitment.com>"))


def test_reply_headers_win_even_for_automated_looking_sender():
    """A reply is a conversation regardless of who the address looks like."""
    assert _is_correspondence(_em("noreply@bigcorp.com", is_reply=True))


def test_unknown_sender_defaults_to_correspondence():
    """Default-safe: not provably automated => treat as a conversation."""
    assert _is_correspondence(_em("Alyssa Harry <alyssa@goengineer.com>"))
    assert _is_correspondence(_em(""))


# --- the archive list must never contain correspondence ---------------------------------------------

def _job(mid: str, corr: bool) -> Job:
    j = Job(link=f"https://x.test/{mid}", company="C", title="T")
    j.email_mid, j.from_correspondence = mid, corr
    return j


def test_archive_list_excludes_correspondence():
    alert, human = _job("<alert@a>", False), _job("<human@b>", True)
    keys = {alert.link, human.link}
    lines, n = archive_list_lines([alert, human], keys, "jobs-triage", "2026-07-20")
    assert n == 1
    body = "\n".join(lines)
    assert "<alert@a>" in body and "<human@b>" not in body


def test_archive_list_empty_when_only_correspondence():
    human = _job("<human@b>", True)
    lines, n = archive_list_lines([human], {human.link}, "jobs-triage", "2026-07-20")
    assert n == 0 and lines == []
