"""The `paste` channel: URLs in, scored jobs out, with no mail, no key and no configuration.
Run:  .venv/bin/python -m pytest triage/ -q

Everything here is offline. `paste.fetch` takes its fetch and its backfill as keyword arguments for
exactly that reason — the two things it does that touch the world are the JD scrape and one small
model call, and both are injected here, so these are real end-to-end assertions about the channel
rather than assertions about a mock of it.

The failure directions, in the order they cost something:

  * **Two pasted URLs sharing one identity.** Before stage 4 · 01 every job with no company and no
    title got the id `"||"`, so a second pasted URL collapsed into the first and `seen`/`applied`
    dedup broke with nothing printed. That is the whole reason this channel could not ship first, and
    it is asserted here on both paths: backfilled, and backfill-failed.
  * **A failed backfill losing the job.** The user typed this URL on purpose. A model call that
    refuses, or a provider key that isn't set, must cost the job its *name* and not its existence —
    it still has a JD, it still has a distinct id, and it still gets scored.
  * **A pasted job reaching the archive list.** It has no `email_mid`, so it must be invisible to the
    archive side-channel; the day one leaks in, the archiver is handed a blank message-id.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.models import Job

from . import channels
from .channels import common, paste
from .channels.common import archive_list_lines

# Two real postings on two different boards — different hosts, different ATS, so nothing about their
# ids can come from a shared prefix.
_ACME = "https://boards.greenhouse.io/acme/jobs/4123456"
_BETA = "https://jobs.lever.co/beta/8f2c1d90-0000-4a11-9c33-abcdef123456"

_JDS = {
    _ACME: "Acme Robotics is hiring a Senior Full Stack Engineer. Remote, contract, React and Python.",
    _BETA: "Beta Labs — Staff Frontend Engineer. Remote in the US. TypeScript, Next.js, GraphQL.",
}

_EXTRACTED = {
    _ACME: ("Acme Robotics", "Senior Full Stack Engineer", "greenhouse"),
    _BETA: ("Beta Labs", "Staff Frontend Engineer", "lever"),
}


def _fake_fetch(job: Job) -> Job:
    """Stands in for `core.fetch.fetch_jd` — same contract: populate, or record, never raise."""
    jd = _JDS.get(job.link, "")
    if jd:
        job.fetched_jd, job.jd_source = jd, "full"
    else:
        job.fetch_error, job.jd_source = "fetched but no usable JD text", "title_only"
    return job


def _fake_backfill(job: Job) -> Job:
    """Stands in for the Sonnet call, reading the same JD text the real one would be handed."""
    company, title, platform = _EXTRACTED.get(job.link, ("", "", ""))
    if job.jd_text:
        job.company, job.title, job.source_platform = company, title, platform
    return job


# --- getting the URLs in --------------------------------------------------------------------------

def test_urls_from_the_command_line_are_ingested_and_scored() -> None:
    """The zero-configuration path: two URLs on argv become two jobs with their JDs attached."""
    jobs = paste.fetch(3, urls=[_ACME, _BETA], fetch_jd=_fake_fetch, backfill=_fake_backfill)
    assert [j.link for j in jobs] == [_ACME, _BETA]
    assert [j.jd_source for j in jobs] == ["full", "full"]
    assert [(j.company, j.title) for j in jobs] == [
        ("Acme Robotics", "Senior Full Stack Engineer"), ("Beta Labs", "Staff Frontend Engineer")]


def test_a_file_of_links_is_ingested(tmp_path) -> None:
    """One URL per line, with comments and blanks, because a links file is a thing people annotate."""
    f = tmp_path / "links.txt"
    f.write_text(f"# jobs I found myself\n\n{_ACME}\n  {_BETA}   # lever\n\n")
    assert paste.collect_urls(files=[f]) == [_ACME, _BETA]


def test_argv_and_files_combine_and_duplicates_collapse(tmp_path) -> None:
    """The same posting given twice — once on argv, once in the file — is fetched once, not twice."""
    f = tmp_path / "links.txt"
    f.write_text(f"{_ACME}\n{_BETA}\n")
    assert paste.collect_urls([_ACME], [f]) == [_ACME, _BETA]


def test_a_non_url_line_is_dropped_rather_than_fetched() -> None:
    """A pasted page title or a stray CSV column must not become a job with a nonsense link."""
    assert paste.collect_urls(["Senior Engineer at Acme", "ftp://x.test/1", _ACME]) == [_ACME]


def test_a_missing_links_file_does_not_kill_the_run(tmp_path) -> None:
    """paste is the channel a first-time user reaches for; a typo'd path costs them paste, not mail."""
    assert paste.read_links_file(tmp_path / "nope.txt") == []
    assert paste.collect_urls([_ACME], [tmp_path / "nope.txt"]) == [_ACME]


def test_sample_caps_the_urls_so_a_small_test_stays_small() -> None:
    """`--sample N` means 'a small end-to-end run' on every channel, not just mail."""
    jobs = paste.fetch(3, 1, urls=[_ACME, _BETA], fetch_jd=_fake_fetch, backfill=_fake_backfill)
    assert [j.link for j in jobs] == [_ACME]


def test_set_urls_is_what_the_registry_reads() -> None:
    """`fetch(days, sample)` is the contract the registry calls — the URLs arrive out of band."""
    paste.set_urls([_ACME])
    try:
        jobs = paste.fetch(3, fetch_jd=_fake_fetch, backfill=_fake_backfill)
        assert [j.link for j in jobs] == [_ACME]
    finally:
        paste.set_urls([])
    assert paste.fetch(3, fetch_jd=_fake_fetch, backfill=_fake_backfill) == []


# --- identity -------------------------------------------------------------------------------------

def test_company_and_title_are_backfilled_from_the_fetched_jd() -> None:
    """The backfill is what gives a pasted job the two fields every downstream step reads — and it
    moves the job's identity off the link and onto the composite, which is how a pasted job can match
    the applied cache at all."""
    job, = paste.fetch(3, urls=[_ACME], fetch_jd=_fake_fetch, backfill=_fake_backfill)
    assert job.company == "Acme Robotics"
    assert job.title == "Senior Full Stack Engineer"
    assert job.source_platform == "greenhouse"
    assert job.id == "acme robotics|senior full stack engineer|"


def test_two_pasted_urls_are_two_jobs_across_runs() -> None:
    """The defect this channel could not ship without: both used to be `"||"`, so the second pasted
    job collapsed into the first in `ingest()` AND overwrote it in `seen.json` — silently, run after
    run. Pinned on the ids, on the collapse, and on the `seen` set the next run reads."""
    a, b = paste.fetch(3, urls=[_ACME, _BETA], fetch_jd=_fake_fetch, backfill=_fake_backfill)
    assert a.id != b.id
    assert "||" not in (a.id, b.id)
    candidates, _ = channels.ingest(3, channels={"paste": lambda d, s=None: [a, b]})
    assert len(candidates) == 2
    assert len({j.id for j in candidates}) == 2      # what `seen.update(j.id ...)` stores


def test_a_backfilled_job_lands_on_the_identity_mail_already_gave_it() -> None:
    """Pasting a URL for a job the inbox already delivered must be recognised as that job, not scored
    a second time — which only works if the backfilled composite is byte-identical to the one the mail
    extractor produced. Pinned to a real corpus row: a live backfill of Genesis10's stored JD returned
    exactly this company and title, and the id is a key in the 1,071-entry `seen.json`.

    The whole-corpus check skips on a fresh clone, where `data/` doesn't exist — the literal above is
    what carries the assertion there.
    """
    key = "genesis10|senior full stack developer remote|"
    assert Job(link=_ACME, company="Genesis10", title="Senior Full Stack Developer - Remote").id == key

    seen_path = Path(__file__).resolve().parent.parent / "data" / "corpus" / "seen.json"
    if not seen_path.exists():
        pytest.skip("no corpus in this checkout — the pinned literal above still holds")
    assert key in set(json.loads(seen_path.read_text()))


def test_a_failed_backfill_keeps_the_job_with_a_link_identity(monkeypatch) -> None:
    """No key, a refusal, a rate limit — the job keeps its JD and a distinct id and is still scored.
    It reads as `? — ?` in the worklist, which is a bad row and not a missing one. Losing the job
    instead would throw away a URL the user asked for by name."""
    class _Boom:
        def invoke(self, _messages):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(common, "_backfill_model", lambda: _Boom())
    a, b = paste.fetch(3, urls=[_ACME, _BETA], fetch_jd=_fake_fetch)
    assert (a.company, a.title) == ("", "")
    assert a.jd_source == "full" and a.jd_text == _JDS[_ACME]
    # The fallback is per-URL, so even the fully degraded path cannot collide two pasted jobs.
    assert a.id == "https://boards.greenhouse.io/acme/jobs/4123456"
    assert b.id == _BETA
    assert a.id != b.id


def test_a_job_that_could_not_be_fetched_is_still_a_job(monkeypatch) -> None:
    """A dead or walled link is `needs_manual_review` territory — the worklist's couldn't-fetch block
    — not a URL that vanishes. With no JD there is nothing to backfill from, so no model call is made
    and the identity stays the link."""
    calls = []
    monkeypatch.setattr(common, "_backfill_model", lambda: calls.append(1))
    job, = paste.fetch(3, urls=["https://x.test/gone"], fetch_jd=_fake_fetch)
    assert job.fetch_error and job.jd_source == "title_only"
    assert job.id == "https://x.test/gone"
    assert calls == []


# --- through the pipeline -------------------------------------------------------------------------

def test_paste_is_registered_and_mail_still_wins_a_duplicate() -> None:
    """`ALL` is the built set plus the `gmail` stub, which 05 added at the end. Registry order is
    load-bearing: mail is first, so the copy that survives the collapse is the one carrying the
    `email_mid` its email needs in order to archive, and paste is last of the *built* channels, so a
    model-backfilled company/title never wins against a board's employer-stated one."""
    from .channels import agencies, boards, gmail_api, mail
    assert channels.ALL == {"mail": mail.fetch, "boards": boards.fetch,
                            "agencies": agencies.fetch, "paste": paste.fetch,
                            "gmail": gmail_api.fetch}
    assert list(channels.ALL) == ["mail", "boards", "agencies", "paste", "gmail"]


def test_a_pasted_job_is_skipped_by_the_archive_side_channel() -> None:
    """No `email_mid`, so nothing to archive and no blank id handed to the archiver. Mixed in with a
    real mail job, so the assertion is 'the mail one archives and the pasted one doesn't'."""
    pasted, = paste.fetch(3, urls=[_ACME], fetch_jd=_fake_fetch, backfill=_fake_backfill)
    mailed = Job(link="https://x.test/1", company="Zeta", title="Engineer", email_mid="<m1@mail>")
    lines, n = archive_list_lines([pasted, mailed], {"https://x.test/1"}, "jobs-triage", "2026-07-22")
    assert n == 1
    assert "<m1@mail>" in lines[-1]
    assert _ACME not in "\n".join(lines)


def test_the_pipeline_does_not_fetch_a_pasted_jd_a_second_time(monkeypatch) -> None:
    """The channel fetches its own JDs because it needs them before the job has an identity. Without
    the guard in `__main__._fetch` the pipeline's pool would scrape every pasted URL again — a second
    round trip per URL, and a second hit on a host that rate-limits."""
    from . import __main__ as entry
    calls = []
    monkeypatch.setattr(entry, "fetch_jd", lambda j: calls.append(j.link) or j)

    pasted, = paste.fetch(3, urls=[_ACME], fetch_jd=_fake_fetch, backfill=_fake_backfill)
    entry._fetch(pasted)
    assert calls == []
    entry._fetch(Job(link="https://x.test/1"))       # a mail job still gets fetched
    assert calls == ["https://x.test/1"]


def test_paste_costs_nothing_when_no_urls_were_given() -> None:
    """Leaving the channel on has to be free — it is on by default and most runs paste nothing."""
    calls = []

    def spy(job):
        calls.append(job)
        return job

    paste.set_urls([])
    assert paste.fetch(3, fetch_jd=spy, backfill=spy) == []
    assert calls == []


def test_paste_jobs_flow_through_the_registry_with_mail() -> None:
    """The whole point: a pasted URL and a mail job arrive in one candidate list, deduped together,
    and the counts line tells you which channel supplied what."""
    from functools import partial
    mailed = Job(link="https://x.test/1", company="Zeta", title="Engineer", email_mid="<m1@mail>")
    registry = {"mail": lambda d, s=None: [mailed],
                "paste": partial(paste.fetch, urls=[_ACME, _BETA],
                                 fetch_jd=_fake_fetch, backfill=_fake_backfill)}
    candidates, all_extracted = channels.ingest(3, channels=registry, enabled=lambda _: True)
    assert len(candidates) == 3 and len(all_extracted) == 3
    assert channels.counts_line(channels.LAST_RUN) == "mail 1 · paste 2"
