"""Alert vs. live-correspondence classification.  Run:  .venv/bin/python -m pytest triage/ -q

Guards the 2026-07-20 findings. Both failure directions cost something real, but they are NOT symmetric:

  * correspondence misread as an alert -> a live thread gets archived out of the inbox, and a role Ben
    is already interviewing for is presented as a fresh lead to cold-apply to.
  * an alert misread as correspondence -> the email stays in the inbox AND the job is rendered in the
    do-not-cold-apply section instead of the apply set.

That second cost was recorded here as "one email stays in the inbox. Harmless." until 2026-07-27, when
~50 Dice blasts landed in the correspondence section in a single run: the two genuine leads in it became
unusable (a reader cannot tell which of 52 lines a human actually wrote) and 180 jobs were held back from
the archive list. It is cheaper than archiving a live thread, so the default below is unchanged — but it
is not free, and a sender that is *provably* a job board must be caught.

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
    plan = archive_list_lines([alert, human], keys, "jobs-triage", "2026-07-20")
    assert plan.count == 1
    body = "\n".join(plan.lines)
    assert "<alert@a>" in body and "<human@b>" not in body


def test_archive_list_empty_when_only_correspondence():
    human = _job("<human@b>", True)
    plan = archive_list_lines([human], {human.link}, "jobs-triage", "2026-07-20")
    assert plan.count == 0 and plan.lines == [] and plan.held == []


# --- job-board subdomains (the 2026-07-27 bug) ------------------------------------------------------

def test_job_board_subdomain_senders_are_automated():
    """The address a board actually sends from is a subdomain, not the bare domain.

    `dice@connect.dice.com` is the sender on every Dice job alert. The pattern used to spell a literal
    `@dice.com`, which does not match it, so ~50 blasts were read as human correspondence in the
    2026-07-27 run. Matching must be on the registrable domain.
    """
    for s in ['"Dice" <dice@connect.dice.com>',
              "Dice <no-reply@marketing.dice.com>",
              "LinkedIn <jobs-listings@e.linkedin.com>",
              "Indeed <invitetoapply@indeed.com>",
              "ZipRecruiter <jobs@mail.ziprecruiter.com>",
              "Glassdoor <noreply@mail.glassdoor.com>"]:
        assert not _is_correspondence(_em(s)), s


def test_a_reply_still_wins_over_a_board_domain():
    """Broadening the domains must not archive a thread Ben is in.

    If he replied, `In-Reply-To` is set and the message is a conversation whatever the sender looks
    like — that guard is what makes broadening the domain list safe.
    """
    assert _is_correspondence(_em('"Dice" <dice@connect.dice.com>', is_reply=True))


def test_a_human_at_a_staffing_firm_is_still_correspondence():
    """The broadened list names job BOARDS, not every recruiter — agency mail stays correspondence."""
    assert _is_correspondence(_em("Grace Kim <gkim@mondo.com>"))
    assert _is_correspondence(_em("Sudha Atre <satre@tricomtech.com>"))
