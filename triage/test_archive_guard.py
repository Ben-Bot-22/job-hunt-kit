"""Nothing leaves an inbox without a look at who sent it.  Run:  .venv/bin/python -m pytest triage/test_archive_guard.py -q

On 2026-07-29 a live recruiter email — `"Akshay Srivastava" <gt4-mu0-nd5@user.dice.com>`, IMCS Group,
never replied to — was moved out of the inbox. Cause: widening `_AUTOMATED_SENDER` to match board domains
*with subdomains* was correct (it fixed ~50 misclassified Dice blasts) and also made `user.dice.com`,
Dice's private recruiter relay, read as automated. A `_PRIVATE_RELAY` carve-out fixed that one host, but
a named host list always lags the next board that starts relaying human mail.

So this pins the general guard, and pins it as **behaviour and failure direction only**. There is
deliberately no catalogue of sender strings here: the owner asked for the behaviour prevented and
*visible*, not for an assertion per vocabulary word — a word list that has to be edited in two places to
add a term is a word list that stops being edited. Replayed against the 2026-07-29 corpus the guard holds
2 of 20 emails, both of them written by a person, and archives every blast.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "Nothing leaves the inbox without a look at who sent it — a named human sender is held back."
from .channels.common import archive_list_lines, has_human_display_name
from .worklist import render
from core.models import Analysis, Job


def _mail(mid: str, sender: str, subject: str = "A role for you", corr: bool = False) -> Job:
    j = Job(link=f"https://x.test/{mid}", company="Acme", title="Full Stack Developer")
    j.email_mid, j.email_sender, j.email_subject, j.from_correspondence = mid, sender, subject, corr
    j.analysis = Analysis(tier="PRIMARY", fit_score=70, intensity=3, verdict="FIT", why="in lane",
                          role_summary="", meets_goals="")
    return j


def _plan(*jobs):
    return archive_list_lines(list(jobs), {j.link for j in jobs}, "jobs-triage", "2026-07-29")


# --- the incident ------------------------------------------------------------------------------------

def test_the_imcs_recruiter_is_held_back_even_though_the_domain_reads_as_automated():
    """The exact email that was archived. `user.dice.com` is under a domain `_AUTOMATED_SENDER` matches,
    so classification alone said 'archive'; the From: header says a person wrote it."""
    j = _mail("<imcs@a>", '"Akshay Srivastava" <gt4-mu0-nd5@user.dice.com>', "Full Stack Developer role")
    assert j.from_correspondence is False       # classified automated, as it was on the day
    plan = _plan(j)
    assert plan.count == 0
    assert len(plan.held) == 1
    assert "<imcs@a>" not in "\n".join(plan.lines)


def test_the_guard_does_not_need_the_relay_host_to_be_known():
    """The point of the general guard: a board nobody has listed yet, relaying human mail, is still held."""
    j = _mail("<new@a>", '"Priya Raman" <x9f-22a@messages.some-new-board.example>')
    assert _plan(j).count == 0


# --- the other direction, which must not regress ----------------------------------------------------

def test_blasts_still_archive():
    """The guard is worthless if it holds everything: a run that archives nothing archives nothing."""
    blasts = [_mail("<a@1>", "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"),
              _mail("<b@2>", '"Dice" <dice@connect.dice.com>'),
              _mail("<c@3>", '"Indeed" <donotreply@jobalert.indeed.com>')]
    plan = _plan(*blasts)
    assert plan.count == 3 and plan.held == []


def test_a_bare_address_with_no_display_name_is_not_treated_as_a_person():
    """There is no name to read, so this guard abstains — `from_correspondence` is what covers it."""
    assert has_human_display_name("jobalerts-noreply@linkedin.com") is False


# --- visible, not merely prevented ------------------------------------------------------------------

def test_a_held_email_is_named_in_the_worklist_with_its_sender_and_subject():
    """A guard nobody can see is indistinguishable from a guard that stopped working. The apply doc is
    the only thing the owner reads, so the held list has to render there — recognisably."""
    j = _mail("<imcs@a>", '"Akshay Srivastava" <gt4-mu0-nd5@user.dice.com>', "Full Stack role, remote")
    text = render([j], days=3, skipped_pre=0, archive=_plan(j))
    held = text.split("HELD BACK")[1]
    assert "Akshay Srivastava" in held
    assert "Full Stack role, remote" in held


def test_every_archived_email_is_named_with_its_sender_and_subject():
    """The audit half of the same requirement. The list used to carry a bare message-id and a job count,
    so the 2026-07-29 apply-doc table had to be rebuilt by hand from a subagent's mailbox report."""
    j = _mail("<a@1>", "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", "8 new jobs for you")
    plan = _plan(j)
    assert "8 new jobs for you" in "\n".join(plan.lines)
    assert "jobalerts-noreply@linkedin.com" in "\n".join(plan.lines)
    archived = render([j], days=3, skipped_pre=0, archive=plan).split("Archived this run")[1]
    assert "8 new jobs for you" in archived and "<a@1>" in archived


def test_the_subject_reaches_the_job_from_the_email(monkeypatch):
    """`email_subject` is only useful if the extractor actually sets it — the field is new."""
    from .channels import common
    em = {"mid": "<m@1>", "sender": '"Dice" <dice@connect.dice.com>', "subject": "Your job alert",
          "date": "", "content": "", "urls": ["https://boards.greenhouse.io/acme/jobs/1"],
          "is_reply": False}
    monkeypatch.setattr(common, "_extract_model", lambda: (_ for _ in ()).throw(RuntimeError("no key")))
    (job,) = common._extract_from_email(em)     # falls back to link recovery, which still calls _mk
    assert job.email_subject == "Your job alert"
