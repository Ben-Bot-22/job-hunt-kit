"""Offline tests for the extraction call site (`triage/channels/common.py`).
Run:  .venv/bin/python -m pytest triage/ -q

Stage 3 moved `_extract_from_email` onto `core/llm.py`; stage 4 moved it out of `ingest.py` into the
channel-shared module, where a Gmail adapter reuses it verbatim. Nothing here asserts what the model decides —
that is what `scripts/before_after.py` is for, and it is deliberately not a test. What is pinned is
everything *around* the call that the path change could have altered without changing an answer:

  * the prompt shape, because a system block flattened from a list to a string silently drops the
    `cache_control` marker and re-bills the extraction prompt on every email in the run;
  * the mapping from `ExtractedJob` to `Job`, because a field that stops being carried (the message
    id, the correspondence flag) doesn't fail — it archives a live human thread or loses a link;
  * the failure direction, because a refusal arrives as a raised `OutputParserException` where the
    native path returned `parsed_output=None`. Neither may cost more than that email's *metadata*;
  * and above all the RECONCILIATION, which is what stops the model deciding what exists. The link
    list is assembled deterministically and is authoritative: a posting the model does not describe
    is still a posting. Before that inversion no email in the whole corpus ever yielded more than 20
    jobs — a 55-job digest returned 20, silently, in a run that reported success.
"""
from __future__ import annotations

import pytest
from langchain_core.exceptions import OutputParserException

from core.llm import ConfigurationError
from core.models import EmailExtraction, ExtractedJob
from .channels import common as ingest


def _email(**kw) -> dict:
    em = {"subject": "Your job alert for full stack engineer", "sender": "jobalerts-noreply@linkedin.com",
          "date": "Mon, 20 Jul 2026", "content": "Senior Full Stack Engineer at Genesis10",
          "urls": ["https://www.linkedin.com/comm/jobs/view/senior-full-stack-4271234567?trk=eml"],
          "mid": "<abc@mail.gmail.com>", "is_reply": False}
    em.update(kw)
    return em


class _Fake:
    """Stands in for the runnable `core.llm.structured` returns. Records what it was invoked with."""

    def __init__(self, result=None, raises: Exception | None = None):
        self.result, self.raises, self.calls = result, raises, []

    def invoke(self, messages):
        self.calls.append(messages)
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def fake(monkeypatch):
    def install(f):
        monkeypatch.setattr(ingest, "_extract_model", lambda: f)
        return f
    return install


def _extraction(**kw) -> EmailExtraction:
    job = {"link": "https://www.linkedin.com/comm/jobs/view/senior-full-stack-4271234567?trk=eml",
           "company": " Genesis10 ", "title": " Senior Full Stack Developer ",
           "source_platform": "", "posted_hint": "3 days ago", "email_jd_text": " React and Node. "}
    job.update(kw)
    return EmailExtraction(jobs=[ExtractedJob(**job)])


# --- the mapping from what the model returns to what the pipeline stores ---------------------------

def test_extracted_record_keeps_its_shape(fake):
    """Every field the rest of the pipeline reads off a freshly extracted job, in one assertion.

    Stripping, link normalisation and the sender-derived platform fallback all happen at this seam;
    a link that stops being normalised is 1,144 corpus rows that dedup against nothing.
    """
    fake(_Fake(_extraction()))
    (job,) = ingest._extract_from_email(_email())
    assert job.link == "https://www.linkedin.com/jobs/view/4271234567"
    assert (job.company, job.title) == ("Genesis10", "Senior Full Stack Developer")
    assert job.source_platform == "linkedin"      # empty from the model -> derived from the sender
    assert (job.posted_hint, job.email_jd_text) == ("3 days ago", "React and Node.")
    assert job.email_mid == "<abc@mail.gmail.com>"
    assert job.email_sender == "jobalerts-noreply@linkedin.com"
    assert job.from_correspondence is False


def test_a_reply_is_marked_as_correspondence(fake):
    """The flag that keeps `archive_list_lines` from pulling a live thread out of the inbox."""
    fake(_Fake(_extraction()))
    (job,) = ingest._extract_from_email(_email(sender="recruiter@acme.com", is_reply=True))
    assert job.from_correspondence is True


def test_a_job_with_no_link_no_title_and_no_jd_is_dropped(fake):
    """Nothing to fetch, nothing to read, nothing to show — an empty row in the worklist.

    The email's own link is still recovered: dropping the model's empty row is not a reason to drop a
    URL that was found without the model's help.
    """
    fake(_Fake(_extraction(link="", title="", email_jd_text="", company="Acme")))
    jobs = ingest._extract_from_email(_email())
    assert [(j.company, j.title) for j in jobs] == [("", "")]
    assert jobs[0].link == "https://www.linkedin.com/jobs/view/4271234567"


def test_a_mega_digest_is_not_capped(fake):
    """The cap that used to be here is gone, and it is the single most important line in this file.

    A 60-job newsletter is 60 jobs. The old `_MAX_JOBS_PER_EMAIL = 30` never even fired — measured
    across every run in `data/corpus/`, no email ever yielded more than 20, because the *model* quit
    early and nothing compared its answer to the link list it was given. Capping here is how a digest
    of 55 became 20 jobs and a run that reported success.
    """
    urls = [f"https://greenhouse.io/j/{i}" for i in range(60)]
    fake(_Fake(EmailExtraction(jobs=[ExtractedJob(link=u, title=f"Role {i}")
                                     for i, u in enumerate(urls)])))
    assert len(ingest._extract_from_email(_email(urls=urls))) == 60


# --- the reconciliation: the link list is authoritative, the model only enriches --------------------

def test_links_the_model_left_out_are_recovered(fake):
    """The regression that motivated all of this. The model describes one job; the email had four.

    The three it skipped come back as bare jobs — link only — which is exactly what a `paste` job is
    and which `hydrate` then fetches and backfills. Losing them was silent; recovering them costs one
    fetch and one cheap prefilter call each.
    """
    urls = [f"https://www.linkedin.com/comm/jobs/view/44100000{i}/?trk=eml" for i in range(4)]
    fake(_Fake(EmailExtraction(jobs=[ExtractedJob(link=urls[0], company="Acme", title="Staff Eng")])))
    jobs = ingest._extract_from_email(_email(urls=urls))
    assert len(jobs) == 4
    assert (jobs[0].company, jobs[0].title) == ("Acme", "Staff Eng")
    assert [j.company for j in jobs[1:]] == ["", "", ""]      # bare, to be hydrated
    assert {j.link for j in jobs} == {f"https://www.linkedin.com/jobs/view/44100000{i}" for i in range(4)}


def test_a_recovered_job_carries_the_archive_and_correspondence_fields(fake):
    """A recovered job is a first-class job or the archive check breaks: `archive_list_lines` groups by
    `email_mid`, and a job missing it would let an email archive with postings still unresolved."""
    urls = ["https://boards.greenhouse.io/acme/jobs/1", "https://boards.greenhouse.io/acme/jobs/2"]
    fake(_Fake(EmailExtraction(jobs=[ExtractedJob(link=urls[0], title="Kept")])))
    recovered = ingest._extract_from_email(_email(urls=urls, sender="ben@example.com"))[1]
    assert recovered.email_mid == "<abc@mail.gmail.com>"
    assert recovered.from_correspondence is True          # a human sender — never auto-archived
    assert recovered.email_sender == "ben@example.com"


def test_the_model_claiming_a_link_under_a_tracking_variant_is_not_double_counted(fake):
    """The model echoes the tracking-wrapped URL it was given; the link list holds another variant of
    the same posting. They must reconcile as ONE job, or every LinkedIn digest doubles."""
    given = "https://www.linkedin.com/comm/jobs/view/4414700040/?trackingId=abc&refId=def"
    echoed = "https://www.linkedin.com/comm/jobs/view/4414700040/?trackingId=zzz&lipi=urn:li:page"
    fake(_Fake(EmailExtraction(jobs=[ExtractedJob(link=echoed, company="Home Depot", title="AI Eng")])))
    jobs = ingest._extract_from_email(_email(urls=[given]))
    assert len(jobs) == 1 and jobs[0].company == "Home Depot"


# --- the prompt, and the failure direction ---------------------------------------------------------

def test_sends_the_cached_system_block_and_both_halves_of_the_input(fake):
    """The system prompt must stay a *list* of blocks carrying `cache_control`.

    Flattened to a bare string it is re-billed on every email of the run. The user half must still
    carry the HTML-derived URL list beside the body — that list is the only reason LinkedIn and Dice
    links survive at all, and losing it would read as the model hallucinating fewer links.
    """
    f = fake(_Fake(_extraction()))
    ingest._extract_from_email(_email())
    (system_role, system), (human_role, user) = f.calls[0]
    assert (system_role, human_role) == ("system", "human")
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == ingest._EXTRACT_SYSTEM
    assert "SUBJECT: Your job alert for full stack engineer" in user
    assert "JOB URLS FOUND IN THIS EMAIL:\nhttps://www.linkedin.com/comm/jobs/view/" in user


def test_a_refusal_costs_the_metadata_and_not_the_jobs(fake):
    """The failure shape the migration introduced: an exception where there was a `None`.

    Unhandled it would abort the `ThreadPoolExecutor.map` and lose the whole run's ingestion. Handled,
    it used to drop the email's jobs entirely — but the links were found *without* the model, so the
    postings survive as bare jobs and only the company/title enrichment is lost.
    """
    fake(_Fake(raises=OutputParserException("did not validate")))
    jobs = ingest._extract_from_email(_email())
    assert [j.link for j in jobs] == ["https://www.linkedin.com/jobs/view/4271234567"]
    assert (jobs[0].company, jobs[0].title) == ("", "")


def test_a_misconfigured_provider_still_yields_the_links(fake):
    """A stranger with no key gets a warning per email and every link, not a traceback and not a
    silently empty run."""
    fake(_Fake(raises=ConfigurationError("ANTHROPIC_API_KEY is not set")))
    assert len(ingest._extract_from_email(_email())) == 1


def test_an_email_with_no_links_and_a_failed_extraction_yields_nothing(fake):
    """A recruiter email whose JD is inline has no URL to fall back on, so a refusal still costs it —
    and it correctly never reaches the archive list, so the next run re-reads it."""
    fake(_Fake(raises=OutputParserException("did not validate")))
    assert ingest._extract_from_email(_email(urls=[])) == []


def test_an_email_that_failed_extraction_is_never_archived(fake):
    """Recovering the links must not make the email archivable while its jobs are still unresolved.

    `archive_list_lines` gates on every extracted job's dedup key being resolved. A recovered job is
    a real job in that set, so an email archives only once the recovered postings have been scored —
    which is the same invariant as before, now reached without losing the postings.
    """
    fake(_Fake(raises=OutputParserException("did not validate")))
    jobs = ingest._extract_from_email(_email(sender="jobalerts-noreply@linkedin.com"))
    assert jobs, "the links must survive the refusal"
    lines, n = ingest.archive_list_lines(jobs, resolved_keys=set(), label="Processed", day="2026-07-22")
    assert (lines, n) == ([], 0)


# --- classify_urls: the three buckets, and the Indeed collapse -------------------------------------

def test_an_indeed_digest_keeps_every_job():
    """The bug that made Indeed a dead channel for a month.

    The old key was `url.split("?")[0]` — the URL with its query discarded — and Indeed puts the job
    id IN the query. An 18-job digest collapsed to one URL and 17 postings were dropped before
    anything could look at them. The corpus is the receipt: 11 Indeed records against LinkedIn's 613
    across 1,305 jobs, which is this, and not thin supply.
    """
    html = " ".join(f'<a href="https://www.indeed.com/rc/clk/dl?jk={i:016x}&from=ja">Job {i}</a>'
                    for i in range(18))
    jobs, _ = ingest.classify_urls(html)
    assert len(jobs) == 18


def test_duplicate_anchors_for_one_posting_still_collapse():
    """The other direction, which must not regress: a LinkedIn digest repeats each job as a title
    link, a logo link and an apply button, each with its own tracking params. That is one job."""
    base = "https://www.linkedin.com/comm/jobs/view/4414700040/"
    jobs, _ = ingest.classify_urls(" ".join([
        f'<a href="{base}?trackingId=aaa&refId=bbb">t</a>',
        f'<a href="{base}?trackingId=ccc&lipi=urn:li:page">i</a>',
        f'<a href="{base}?trk=eml-jobs&midToken=x">a</a>']))
    assert len(jobs) == 1


def test_entity_escaped_hrefs_are_unescaped():
    """Hrefs arrive HTML-escaped. Left alone, `&amp;` travelled into the URL handed to the fetcher —
    and made the same posting look like two different ones."""
    a = 'https://www.indeed.com/rc/clk/dl?jk=abc123&amp;from=ja'
    b = 'https://www.indeed.com/rc/clk/dl?jk=abc123&from=ja'
    jobs, _ = ingest.classify_urls(f"{a} {b}")
    assert len(jobs) == 1
    assert "&amp;" not in jobs[0]


def test_an_unknown_job_board_is_reported_and_not_silently_dropped():
    """Bucket 3. The allowlist is default-deny over an open set, so a host it has never heard of must
    leave a trace — otherwise a whole board is indistinguishable from an empty inbox."""
    jobs, unknown = ingest.classify_urls(
        'https://apply.workable.com/acme/j/ABC123/ https://jobs.smartrecruiters.com/Acme/74409')
    assert jobs == []
    assert len(unknown) == 2


def test_assets_and_site_nav_are_dropped_silently():
    """Bucket 2. 2,456 URLs in a 7-day window yielded 534 job links; if the other 78% reached bucket 3
    the report that makes bucket 3 useful would be unreadable."""
    _, unknown = ingest.classify_urls(" ".join([
        "https://static.licdn.com/aero-v1/sc/h/logo.png",
        "https://www.w3.org/1999/xhtml",
        "https://fonts.googleapis.com/css?family=Inter",
        "https://www.linkedin.com/comm/jobs/alerts/?midToken=x",
        "https://www.linkedin.com/job-alert-email-unsubscribe?x=1"]))
    assert unknown == []


def test_a_real_job_host_outranks_a_junk_path_substring():
    """Bucket 1 is checked first on purpose: a posting whose path happens to contain a junk word is a
    posting, not nav."""
    jobs, _ = ingest.classify_urls("https://boards.greenhouse.io/acme/jobs/4123456?t=/settings")
    assert len(jobs) == 1


# --- hydration: making a recovered link whole, exactly once -----------------------------------------

def test_hydrate_fills_company_and_title_only_for_bare_jobs():
    """The enriched jobs are left alone — the model already described them and re-fetching them would
    undo the whole point of asking it."""
    from core.models import Job
    described = Job(link="https://boards.greenhouse.io/acme/jobs/1", company="Acme", title="Staff Eng")
    bare = Job(link="https://boards.greenhouse.io/acme/jobs/2")
    touched = []

    def _fetch(j):
        touched.append(j.link)
        j.fetched_jd, j.jd_source = "React and Node. Acme is hiring.", "full"

    def _backfill(j, *, default_platform=""):
        j.company, j.title = "Acme", "Senior Engineer"
        return j

    ingest.hydrate([described, bare], fetch=_fetch, backfill=_backfill)
    assert touched == ["https://boards.greenhouse.io/acme/jobs/2"]
    assert (bare.company, bare.title) == ("Acme", "Senior Engineer")


def test_a_hydrated_job_is_recognised_by_its_link_on_the_next_run():
    """The bridge that stops a recovered job being re-fetched every morning, forever.

    A bare job's identity IS its link; after hydration it is `company|title`. So the run stores a
    `url:` key beside the composite id — the same form the applied cache uses and the skip check in
    `__main__` already tests — and tomorrow the gate recognises the job before anything is fetched.
    """
    from core.models import Job, normalize_link
    j = Job(link="https://www.linkedin.com/comm/jobs/view/4414700040/?trk=eml",
            company="Home Depot", title="Senior AI Engineer")
    seen = {j.id, f"url:{normalize_link(j.link)}"}
    tomorrow = Job(link="https://www.linkedin.com/comm/jobs/view/4414700040/?trackingId=zzz")
    assert tomorrow.id not in seen, "arriving bare, it cannot match the composite it was stored under"
    assert f"url:{normalize_link(tomorrow.link)}" in seen


def test_the_unclassified_report_names_only_job_shaped_hosts(caplog):
    """A report nobody reads is the same as no report. The raw bucket over one 7-day window held 565
    links on 66 hosts, led by a tyre shop, a health plan, a domain registrar and YouTube — so only the
    job-shaped residue is named, while the total is still printed so the filter stays checkable."""
    import logging
    emails = [{"unclassified": [
        "https://data.service.firestonecompleteautocare.com/promo/summer",
        "https://www.youtube.com/watch?v=abc",
        "https://apply.workable.com/acme/j/ABC123/",
        "https://acme.com/careers/senior-engineer"]}]
    with caplog.at_level(logging.WARNING, logger="triage.channels.common"):
        ingest._report_unclassified(emails)
    msg = caplog.text
    assert "4 unclassified" in msg and "2 of them JOB-SHAPED" in msg
    assert "apply.workable.com" in msg and "acme.com" in msg
    assert "firestone" not in msg and "youtube" not in msg
