"""Fetch the full JD behind a job link — a domain-routed fallback chain (triage-plan §6).

Order per URL: known ATS public API -> LinkedIn guest endpoint -> generic (JSON-LD -> reader API) ->
email-snippet fallback. Every failure is recorded on the Job (`fetch_error`) so it can be surfaced in the
worklist's "couldn't-fetch" block for manual follow-up — nothing is silently dropped.

Runs from Ben's residential IP (local tool), which is what makes the free LinkedIn guest path work.
"""
from __future__ import annotations

import html as _h
import json
import logging
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import Job

log = logging.getLogger("core.fetch")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
_MIN_JD = 120  # chars — below this we don't trust it as a real JD

# Bot-wall interstitials come back HTTP 200 with real length, so length alone won't catch them — they'd
# be accepted as a "full" JD and fed to the analyzer as garbage. Detect the signatures (checked only in
# the head, so a real JD that merely mentions "captcha" won't false-positive) and treat as a fetch
# failure, so the job degrades and gets queued for browser (Tier-2) retrieval instead.
_BLOCK_MARKERS = ("just a moment", "verify you are human", "checking your browser",
                  "enable javascript and cookies to continue", "attention required",
                  "additional verification required", "cf-browser-verification", "px-captcha",
                  "you have been blocked", "access to this page has been denied")


def _is_block_page(text: str) -> bool:
    head = (text or "")[:600].lower()
    return any(m in head for m in _BLOCK_MARKERS)


def _get(url: str, *, headers: dict | None = None, timeout: float = 20.0) -> httpx.Response:
    r = httpx.get(url, headers={**_HEADERS, **(headers or {})}, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(l.strip() for l in text.splitlines())).strip()


# ---------------------------------------------------------------- ATS public APIs
# The two `*_content` functions take an already-decoded job object rather than a URL, because the same
# object arrives two ways: one at a time from the detail endpoint (below), and in bulk from the board
# LISTING endpoint that `triage/channels/boards.py` calls. Same fields, same escaping — parsing them
# in two places is two chances for the board channel and the JD fetch to disagree about what the JD is.
def greenhouse_content(data: dict) -> str:
    """The JD text inside one Greenhouse job object. `content` is HTML *escaped*, hence the unescape."""
    return _html_to_text(_h.unescape(data.get("content", "") or ""))


def lever_content(data: dict) -> str:
    """The JD text inside one Lever posting object — body plus the `lists` blocks, which is where Lever
    keeps requirements and benefits, so dropping them loses the half a rubric actually reads."""
    parts = [data.get("descriptionPlain") or _html_to_text(data.get("description", ""))]
    for lst in data.get("lists", []) or []:
        parts.append(lst.get("text", "") + "\n" + _html_to_text(lst.get("content", "")))
    return "\n\n".join(p for p in parts if p).strip()


def _greenhouse(url: str) -> str:
    # boards.greenhouse.io/{board}/jobs/{id}, job-boards.greenhouse.io/{board}/jobs/{id}, or ?gh_jid=
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#]+).*?/jobs/(\d+)", url) \
        or re.search(r"greenhouse\.io/([^/?#]+)", url)
    q = parse_qs(urlparse(url).query)
    board = m.group(1) if m else None
    jid = (m.group(2) if m and m.lastindex and m.lastindex >= 2 else None) or (q.get("gh_jid") or [None])[0]
    if not (board and jid):
        return ""
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}?content=true")
    return greenhouse_content(r.json())


def _lever(url: str) -> str:
    m = re.search(r"lever\.co/([^/?#]+)/([0-9a-f-]{16,})", url)
    if not m:
        return ""
    co, jid = m.group(1), m.group(2)
    r = _get(f"https://api.lever.co/v0/postings/{co}/{jid}?mode=json")
    return lever_content(r.json())


def _ashby(url: str) -> str:
    m = re.search(r"ashbyhq\.com/([^/?#]+)/([0-9a-f-]{16,})", url)
    if not m:
        return ""
    org, jid = m.group(1), m.group(2)
    r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true")
    for job in r.json().get("jobs", []):
        if job.get("id") == jid or jid in json.dumps(job):
            return job.get("descriptionPlain") or _html_to_text(job.get("descriptionHtml", ""))
    return ""


# ---------------------------------------------------------------- LinkedIn (guest endpoint)
def _linkedin(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    jid = (q.get("currentJobId") or [None])[0]
    if not jid:
        m = re.search(r"(?:jobs/view/|-)(\d{8,})", url)  # trailing numeric id
        jid = m.group(1) if m else None
    if not jid:
        return ""
    guest = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"
    for attempt in range(3):
        try:
            r = _get(guest, timeout=15.0)
            soup = BeautifulSoup(r.text, "lxml")
            node = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
            text = _html_to_text(str(node)) if node else _html_to_text(r.text)
            if len(text) >= _MIN_JD:
                return text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                time.sleep(2.5 * (attempt + 1))  # backoff on rate-limit
                continue
            raise
    raise httpx.HTTPStatusError("linkedin guest fetch exhausted", request=None, response=None)  # type: ignore


# ---------------------------------------------------------------- generic (JSON-LD -> reader API)
def _jsonld_jobposting(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]) + \
                (data.get("@graph", []) if isinstance(data, dict) else []):
            if isinstance(node, dict) and "JobPosting" in str(node.get("@type", "")):
                desc = node.get("description", "")
                if desc:
                    return _html_to_text(desc)
    return ""


def _jina_reader(url: str) -> str:
    r = _get(f"https://r.jina.ai/{url}", timeout=30.0)
    return r.text.strip()


def _generic(url: str) -> str:
    try:
        html = _get(url).text
        jd = _jsonld_jobposting(html)
        if len(jd) >= _MIN_JD:
            return jd
    except httpx.HTTPError:
        pass  # fall through to the reader API (handles bot-walls / JS-rendered pages sometimes)
    return _jina_reader(url)


# ---------------------------------------------------------------- router
def _route(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        return _greenhouse(url)
    if "lever.co" in host:
        return _lever(url)
    if "ashbyhq.com" in host:
        return _ashby(url)
    if "linkedin.com" in host:
        return _linkedin(url)
    return _generic(url)


def fetch_jd(job: Job) -> Job:
    """Populate job.fetched_jd + job.jd_source, or record job.fetch_error. Never raises."""
    if job.link:
        try:
            text = _route(job.link)
            if text and _is_block_page(text):
                job.fetch_error = "bot-block — needs browser (Tier-2)"
            elif text and len(text.strip()) >= _MIN_JD:
                job.fetched_jd = text.strip()
                job.jd_source = "full"
                return job
            else:
                job.fetch_error = "fetched but no usable JD text"
        except Exception as e:  # noqa: BLE001 — any fetch failure -> record + degrade, don't crash the run
            job.fetch_error = f"{type(e).__name__}: {str(e)[:180]}"
            log.info("fetch failed for %s — %s", job.link, job.fetch_error)
    # degrade gracefully
    if job.email_jd_text and len(job.email_jd_text.strip()) >= _MIN_JD:
        job.jd_source = "email_snippet"
    else:
        job.jd_source = "title_only"
    return job


def needs_manual_review(job: Job) -> bool:
    """A link that couldn't be turned into a full JD — surfaced in the worklist for Ben to open by hand."""
    return bool(job.link) and job.jd_source != "full"
