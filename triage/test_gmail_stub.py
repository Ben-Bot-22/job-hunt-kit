"""The `gmail` stub: registered, disabled, and loud.
Run:  .venv/bin/python -m pytest triage/ -q

There is no channel here to test — that is the point. What these tests protect is the *shape of the
absence*, and the failure directions are not symmetric:

  * **A stub that quietly returns `[]` looks exactly like a working channel whose window was empty.**
    A user who enabled Gmail would read `gmail 0` in the run summary every morning and conclude their
    inbox had no jobs in it. Raising is what makes "not built" legible, so the raise is behaviour and
    is tested as such.
  * **A stub that is enabled crashes every run.** `config.channel_enabled` defaults to True for a
    channel with no config block (stage 4 · 02), so registering this one without shipping
    `enabled: false` would put `gmail CRASHED` on Ben's summary line every morning until he noticed —
    which teaches him to ignore that line, and the line is the whole detection mechanism for a
    genuinely rotted channel.
  * **A docstring that stops carrying the contract.** The module docstring *is* the spec for whoever
    implements this, and the two things it exists to prevent — an implementer using Gmail's own
    message id, and re-deriving the correspondence check — are exactly the two that look harmless.
"""
from __future__ import annotations

import pytest

from . import channels, config
from .channels import gmail_api


def test_the_stub_is_registered_as_a_channel() -> None:
    """It is in `ALL`, so the seam is visible in the registry rather than in a README line."""
    assert channels.ALL["gmail"] is gmail_api.fetch


def test_the_built_channels_plus_the_stub_are_the_whole_registry() -> None:
    """`gmail` is LAST. Registry order decides which channel's copy of a duplicate posting survives
    (stage 4 · 04), and a channel that cannot produce a job must not be in front of one that can."""
    assert list(channels.ALL) == ["mail", "boards", "agencies", "paste", "gmail"]


def test_it_raises_rather_than_quietly_returning_nothing() -> None:
    """The failure direction this whole ticket exists for: `[]` reads as a working, quiet channel."""
    with pytest.raises(NotImplementedError):
        gmail_api.fetch(3)
    with pytest.raises(NotImplementedError):
        gmail_api.fetch(3, 5)


def test_the_raise_points_at_the_contract() -> None:
    """The message has to name the file, or the first thing an implementer does is guess."""
    with pytest.raises(NotImplementedError) as e:
        gmail_api.fetch(7)
    msg = str(e.value)
    assert "triage/channels/gmail_api.py" in msg
    assert "mail" in msg and "paste" in msg      # what to use instead, today


def test_it_ships_disabled_so_a_real_run_never_calls_it() -> None:
    """Ben's config must say `false` in writing — absence would mean ON and crash every run."""
    assert config.channel_enabled("gmail") is False


def test_a_disabled_stub_reports_off_not_crashed() -> None:
    """End-to-end through the registry with the real stub: `gmail off`, and nothing raised.

    This is the assertion that ties the two halves together. `fetch_all` catches the raise, so an
    enabled stub would render as CRASHED rather than blow up the run — correct, and still wrong to
    ship, because a permanent CRASHED line trains you to stop reading the one line that tells you a
    channel died.
    """
    results = channels.fetch_all(3, channels={"gmail": gmail_api.fetch})
    assert [(r.name, r.status, len(r.jobs)) for r in results] == [("gmail", "disabled", 0)]
    assert channels.counts_line(results) == "gmail off"


def test_an_enabled_stub_is_isolated_like_any_other_broken_channel() -> None:
    """If someone flips the flag before implementing it, they lose Gmail and nothing else."""
    good = channels.Job(link="https://x.test/1", company="Acme", title="Engineer")
    candidates, _ = channels.ingest(
        3, channels={"gmail": gmail_api.fetch, "mail": lambda d, s=None: [good]},
        enabled=lambda name: True)
    assert candidates == [good]
    line = channels.counts_line(channels.LAST_RUN)
    assert line.startswith("gmail CRASHED (NotImplementedError:")


def test_the_docstring_carries_the_things_an_implementer_gets_wrong() -> None:
    """The docstring is the deliverable. These four are the ones a reasonable person gets wrong.

    Pinned as substrings rather than prose-checked because the alternative is nothing: a later edit
    that tidies the docstring and drops the Message-ID paragraph costs the next implementer an
    archive list where every `rfc822msgid:` lookup silently finds no message.
    """
    doc = gmail_api.__doc__ or ""
    assert "Message-ID" in doc and "threadId" in doc            # the identifier, and what it is not
    assert "_is_correspondence" in doc and "do not re-derive" in doc.lower()
    assert "gmail.readonly" in doc and "gmail.modify" in doc    # the scopes, and which one is optional
    assert "list[Job]" in doc and "PRE-dedup" in doc            # the return contract


def test_the_docstring_names_the_helpers_to_reuse_verbatim() -> None:
    """"Replaces only the transport" is only useful if it says which functions that leaves alone."""
    doc = gmail_api.__doc__ or ""
    for helper in ("_parse_source", "_job_urls", "classify_urls", "_extract_from_email",
                   "jobs_from_emails", "hydrate"):
        assert helper in doc


def test_a_wire_up_sketch_is_present_and_addressed_to_an_agent() -> None:
    """The sketch is the difference between a one-session job and a reverse-engineering job. It lives
    in a comment rather than in code so it cannot rot into something importable and half-working."""
    import inspect
    src = inspect.getsource(gmail_api)
    assert "# AGENT:" in src
    assert "users().messages().list" in src and 'format="raw"' in src
    assert "common.jobs_from_emails" in src
