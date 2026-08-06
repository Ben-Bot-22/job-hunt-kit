"""The shared `Job` model and its companions — one definition, so two leaves can't drift into two.

Lives in `core/` because the daily pipeline, the research agent and the market report all carry the
same job around, and stage 5 · 01 deleted the frozen pipeline's rival definition so there is now
exactly one. Market sources fold what they know structurally (employment type, location, posted rate)
into the JD text rather than adding fields here — see `core/scrapers/posting.py` for why.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

Tier = Literal["PRIMARY", "SECONDARY", "OPPORTUNISTIC"]
Verdict = Literal["STRONG_FIT", "FIT", "LOW_FIT", "SKIP"]
JDSource = Literal["full", "email_snippet", "title_only"]

_PUNCT = re.compile(r"[^a-z0-9 ]")
_LEGAL = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|ltd|limited|co|plc|lp|llp)\b\.?")


def _norm(s: str) -> str:
    return " ".join(_PUNCT.sub(" ", (s or "").lower()).split())


def composite_id(company: str, title: str, metro: str = "") -> str:
    """Fallback identity when no real posting id exists: legal-suffix-stripped company | title | city."""
    company = " ".join(_LEGAL.sub(" ", _norm(company)).split())
    city = _norm(metro).split(",")[0].strip() if metro else ""
    return f"{company}|{_norm(title)}|{city}"


def normalize_link(url: str) -> str:
    """Strip LinkedIn's giant email-tracking query down to the clean, resolvable job URL.

    Lives here rather than in the mail channel because `Job.id` needs it and `core/` may not import
    a leaf. The behaviour is byte-for-byte what ingest did before the move: the `applied` cache's
    `url_key` and the `seen` blocklist are both built from it, so a "better" normalization here
    silently orphans keys written by every previous run.
    """
    if not url:
        return ""
    m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*?-)?(\d{6,})", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    m = re.search(r"indeed\.com/.*?[?&]jk=([0-9a-f]+)", url)  # strip Indeed's redirect/tracking cruft
    if m:
        return f"https://www.indeed.com/viewjob?jk={m.group(1)}"
    return url


# Query params that are provenance, not identity. Dropped when a URL *is* the identity, so the same
# posting arriving from a newsletter, a share link and the board itself is one job and not three.
# Deliberately a denylist and not "strip the whole query": on plenty of ATSs the query IS the posting
# (`viewjob?jk=`, `?gh_jid=`), and collapsing two real jobs into one identity is the exact failure
# this fallback exists to prevent — the recoverable direction is seeing a job twice.
_TRACKING_PARAMS = {"trk", "trkinfo", "refid", "trackingid", "originaltrackingid", "eblinkinfo",
                    "lipi", "licu", "midtoken", "midsig", "eid", "otptoken", "src", "source",
                    "ref", "referer", "referrer", "gh_src", "lever-source", "lever-origin",
                    "recommendedflavor", "position", "pagenum", "sessionid", "spa", "at", "ck"}


def _is_tracking(param: str) -> bool:
    p = param.strip().lower()
    return p in _TRACKING_PARAMS or p.startswith(("utm_", "_hs", "mc_"))


def link_identity(url: str) -> str:
    """A URL reduced to the thing that makes it *that posting* — used only as `Job.id`'s fallback.

    Canonicalizes the variants that arrive for one job: scheme and host case, `www.`, a trailing
    slash, a fragment, and tracking params (see `_TRACKING_PARAMS`). Surviving params are sorted, so
    argument order can't fork an identity either.
    """
    url = normalize_link((url or "").strip())
    if not url:
        return ""
    head, _, query = url.split("#")[0].partition("?")
    scheme, sep, rest = head.partition("://")
    if sep:
        host, slash, path = rest.partition("/")
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        head = f"{scheme.lower()}://{host}{slash}{path}"
    head = head.rstrip("/")
    kept = sorted(p for p in query.split("&") if p and not _is_tracking(p.split("=")[0]))
    return f"{head}?{'&'.join(kept)}" if kept else head


# ---- Sonnet extraction output (one email -> zero or more candidate jobs) ----
class ExtractedJob(BaseModel):
    link: str = Field(description="The job-posting URL. Empty string if the email has no link but does "
                                  "describe a specific role inline.")
    company: str = ""
    title: str = ""
    source_platform: str = Field(default="", description="e.g. linkedin, dice, greenhouse, recruiter-email")
    posted_hint: str = Field(default="", description="Any date/'x days ago' the email shows, verbatim.")
    email_jd_text: str = Field(default="", description="The job description text present INLINE in the "
                                                       "email itself, if any (the guaranteed fallback).")


class EmailExtraction(BaseModel):
    jobs: list[ExtractedJob] = Field(default_factory=list)


# ---- Opus analysis output (one JD -> one structured judgment) ----
class Analysis(BaseModel):
    tier: Tier
    fit_score: int = Field(ge=0, le=100)
    intensity: int = Field(ge=1, le=5)
    verdict: Verdict
    # A FIXED vocabulary, and that is the whole point of the field. The apply doc groups rejections by
    # it and renders a "held back" section off it, and you cannot group free text — `why` is one honest
    # sentence per job, which is exactly what makes it ungroupable. The empty string means "not held
    # back", so the default is the common case and a scorer that ignores the field changes nothing.
    # Vocabulary is `profile/rubric.md` §THREE TIERS OF "NO"; reasoning in
    # `docs/knowledge-base/decision-work-life-balance-priority.md` (2026-07-30).
    held_back_reason: str = Field(default="", description=
        "intensity | travel | rate | stack-gap | role-shape | years-bar | non-us | clearance | no-content | ''")
    why: str = Field(description="One line — the ranked-list reason.")
    role_summary: str = Field(description="What the job actually is, so you needn't reopen the JD.")
    meets_goals: str = Field(description="How it maps to remote/contract/rate/intensity/stack, and misses.")
    red_flags: list[str] = Field(default_factory=list)
    resume_keywords: list[str] = Field(default_factory=list)
    precedent: str = Field(
        default="",
        description="If a retrieved past decision informed this judgment: which one, and whether you "
                    "followed it or departed from it and why. Empty when none applied — this is how "
                    "you tell a grounded score from an invented one.")
    rate: str = ""
    cadence: str = Field(default="", description="remote | hybrid | onsite | unknown")
    employment_type: str = Field(default="", description="contract | contract-to-hire | permanent | unknown")
    is_agency: bool = False


# ---- pipeline carrier ----
@dataclass
class Job:
    link: str
    company: str = ""
    title: str = ""
    source_platform: str = ""
    posted_hint: str = ""
    email_jd_text: str = ""       # inline JD from the email (fallback)
    fetched_jd: str = ""          # full JD scraped from the link
    jd_source: JDSource = "title_only"
    fetch_error: str = ""         # populated when the link couldn't be fetched (surfaced for manual review)
    email_mid: str = ""           # Message-ID of the source email — the stable handle used to archive it
    email_sender: str = ""        # raw From: of that email (shown for correspondence, so Ben knows who)
    email_subject: str = ""       # Subject: of that email. Carried for ONE reason: the archive list is a
                                  # report of what was touched in someone's mailbox, and a bare
                                  # message-id is not something a human can recognise their own mail in.
    from_correspondence: bool = False  # a human wrote this, not a job alert — NEVER archive, don't mix
                                       # into fresh picks. See channels.common._is_correspondence.
    analysis: Optional[Analysis] = None
    final_tier: str = ""          # deterministic tier from rank.finalize_tier (overrides the model's guess)
    prefiltered: bool = False     # True => screened out cheaply; never reached the Opus analyzer
    # True => the analyzer RAISED and `analysis` is the stub standing in for a judgment we never got.
    #
    # This is the absence of a judgment, not a judgment, and the pipeline must be able to tell the two
    # apart: a scored job is recorded in `seen.json`, and a seen job never surfaces again. On 2026-07-29
    # a monthly spend cap tripped mid-run, 134 jobs were stubbed at `fit_score=0, verdict=SKIP` and
    # became permanently invisible; recovery meant deleting 274 keys from seen.json by hand.
    #
    # It lives on the Job and NOT on `Analysis` because `Analysis` is also the structured-output schema
    # sent to the scorer — a field there is a field the model fills in, and whether the call succeeded is
    # the one thing the model cannot know. For the same reason it is not inferred from `analysis.why`:
    # a string prefix is not a contract.
    #
    # A PREFILTERED job also carries `fit_score=0, verdict=SKIP` and must NOT set this: it was
    # legitimately judged by the cheap gate, and un-seeing it means re-fetching and re-screening it on
    # every run forever. Only `triage/analyze.py`'s except branch produces an errored job.
    analysis_errored: bool = False
    liveness: str = ""            # open | closed | unknown ("" = not checked) — see liveness.py
    liveness_detail: str = ""     # the evidence: the marker matched, HTTP code, or why it's unknown
    # Postings semantic dedup merged INTO this one, each {id, company, title, link, similarity,
    # overlap}. Carried on the survivor rather than dropped on the floor, because a collapse that
    # leaves no trace is a job that silently disappeared — see triage/dedup.py.
    duplicates: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        """company|title|city, falling back to the canonical link **only when that composite is empty**.

        The scoping is the migration story. A job that has a company or a title keeps the identity it
        has had all along, so the 1,071-key `seen` cache and the 33-row applied corpus stay valid by
        construction. Without the fallback a job with neither — a pasted URL — gets the id `"||"`, so
        every pasted job is the same job: dedup collapses them into one and nothing errors.
        """
        composite = composite_id(self.company, self.title)
        return composite if composite.strip("|") else (link_identity(self.link) or composite)

    @property
    def jd_text(self) -> str:
        """Best available JD text for analysis: scraped full JD, else the email's inline JD."""
        return self.fetched_jd or self.email_jd_text


# ---- serialization (Phase 1 writes state; Phase 3 reloads it to merge browser-fetched JDs) ----
_JOB_FIELDS = ["link", "company", "title", "source_platform", "posted_hint", "email_jd_text",
               "fetched_jd", "jd_source", "fetch_error", "email_mid", "email_sender", "email_subject",
               "final_tier", "liveness", "liveness_detail"]


def job_to_dict(j: "Job") -> dict:
    d = {k: getattr(j, k) for k in _JOB_FIELDS}
    d["prefiltered"] = j.prefiltered      # bool — kept out of _JOB_FIELDS' string coercion below
    d["analysis_errored"] = j.analysis_errored
    d["from_correspondence"] = j.from_correspondence
    d["duplicates"] = list(j.duplicates)
    d["analysis"] = j.analysis.model_dump() if j.analysis else None
    return d


def job_from_dict(d: dict) -> "Job":
    j = Job(link=d.get("link", ""))
    for k in _JOB_FIELDS:
        setattr(j, k, d.get(k, "") or "")
    j.prefiltered = bool(d.get("prefiltered", False))
    j.analysis_errored = bool(d.get("analysis_errored", False))
    j.from_correspondence = bool(d.get("from_correspondence", False))
    j.duplicates = list(d.get("duplicates") or [])
    a = d.get("analysis")
    j.analysis = Analysis(**a) if a else None
    return j


# Hosts the browser cannot rescue, so queueing them only spends a round-trip and inflates the
# couldn't-fetch count with things that were never fetchable (2026-07-27).
#
# `elinks.dice.com` is a TRACKING WRAPPER around Dice marketing mail, not a posting link. This was first
# read as staleness — "7 expired to error pages", 2026-07-23 — and that was wrong: on 2026-07-27 one of
# them resolved perfectly cleanly to Dice's own LinkedIn *company page*. They come from "your profile was
# viewed" and job-alert blasts. Across two runs, 40 of them yielded zero JDs. They stay in `_JOB_HOSTS`
# (the link is still a signal that an email is job-related) but they never reach the browser queue.
_BROWSER_UNFETCHABLE = ("elinks.dice.com", "my.greenhouse.io/dashboard")


def needs_browser_fetch(j: "Job") -> bool:
    """A promising job whose full JD we couldn't scrape — worth pulling through the browser (Tier 2).
    Only non-SKIP items (no point rendering a hard-filtered one) that have a link but no full JD,
    and only where the browser can actually reach a JD — see `_BROWSER_UNFETCHABLE`."""
    if not j.link or any(h in j.link for h in _BROWSER_UNFETCHABLE):
        return False
    return j.jd_source != "full" and j.analysis is not None and j.analysis.verdict != "SKIP"
