"""What else is this company hiring for? — board listing, with an honest cold trail.

The governing rule (spec §Cold-trail handling): *follow the link you already have, as far as it goes.*
Some links lead to a board that answers questions; some lead to an aggregator and stop. The order is

    1. the company's ATS board — Greenhouse / Lever / Ashby, the same endpoints `core/fetch.py`
       already parses per-job, with the job id dropped, which returns the whole board;
    2. failing that, the obvious `/careers` and `/jobs` paths on the company's own domain, read
       through the same Jina reader `fetch.py` falls back to;
    3. failing that, **the result says so.**

Step 3 is the point of the module. A confidently wrong careers page sends Ben to another company's
listings; "couldn't check" costs him one manual lookup. So there is no domain-guessing here — see
`guess_company_domain` below, which is a documented stub on purpose.

Both entry points take an injectable `fetch(url) -> str` so the whole thing is assertable offline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.fetch import _get, _is_block_page

# Reader prefix, same service as `fetch._jina_reader`. Spelled out here rather than called, because
# that helper does its own HTTP and this module's whole testing seam is the injected `fetch`.
JINA_PREFIX = "https://r.jina.ai/"

_MIN_PAGE = 200  # chars — below this a "careers page" is a shell, a redirect notice or an error

# Hosts that host somebody else's board or aggregate postings — never the company's own domain, so
# never worth probing for /careers. Overlaps `triage.liveness._AGGREGATORS` (a different question:
# "is a 200 from here evidence the req is open?"); stage 2 merges both into `core/`.
_NOT_COMPANY_DOMAINS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "linkedin.com", "indeed.com", "dice.com",
    "ziprecruiter.com", "glassdoor.com", "monster.com", "workday.com", "myworkdayjobs.com",
    "remotevibecodingjobs.com", "wellfound.com", "angel.co", "builtin.com", "jobs.smartrecruiters.com",
)


@dataclass
class Posting:
    """One currently-open role on a board."""
    title: str
    location: str = ""
    url: str = ""


@dataclass
class BoardResult:
    """What the trail produced — including, deliberately, the case where it produced nothing.

    `ok` is False whenever the postings list is not evidence: a cold trail, a fetch failure, a
    bot-wall. Callers must not read an empty `postings` as "nothing open" — check `ok` first and
    surface `detail` verbatim (it is written in the "⚠ couldn't fetch" voice the worklist uses).
    """
    company: str
    ok: bool
    source: str = "none"          # greenhouse | lever | ashby | careers-page | none
    url: str = ""                 # where the postings actually came from — never invented
    postings: list[Posting] = field(default_factory=list)
    text: str = ""                # raw page text, when the source was a careers page
    detail: str = ""              # honest failure message when ok is False
    attempts: list[str] = field(default_factory=list)   # every URL tried, in order


def default_fetch(url: str) -> str:
    """The real network. Raises on any failure — callers treat a raise as "that door was shut"."""
    return _get(url, timeout=30.0).text


# ---------------------------------------------------------------- board endpoints
def _slugs(company: str) -> list[str]:
    """Board slug candidates for a company *name*. Never used to build a careers URL — a board slug
    is only ever accepted when the endpoint answers, so a wrong guess dies at the 404."""
    base = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|group|technologies|labs)\b", " ",
                  company.lower())
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    joined, hyphened = "".join(words), "-".join(words)
    return [joined] if joined == hyphened else [joined, hyphened]


def _name_from_domain(domain: str) -> str:
    """`jobs.acme.com` -> `acme`. The label a board slug is usually built from."""
    labels = [l for l in domain.split(".") if l != "www"]
    return labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")


def board_url(platform: str, slug: str) -> str:
    """The whole-board endpoint — the per-job URLs in `fetch.py` with the job id dropped."""
    if platform == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    if platform == "lever":
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"
    if platform == "ashby":
        # Already the whole board — `fetch._ashby` fetches this and filters to one job.
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    raise ValueError(f"unknown ATS platform: {platform}")


def _parse_board(platform: str, body: str) -> list[Posting]:
    data = json.loads(body)
    if platform == "greenhouse":
        return [Posting(j.get("title", ""), (j.get("location") or {}).get("name", ""),
                        j.get("absolute_url", ""))
                for j in data.get("jobs", [])]
    if platform == "lever":
        return [Posting(j.get("text", ""), (j.get("categories") or {}).get("location", ""),
                        j.get("hostedUrl", ""))
                for j in data]
    if platform == "ashby":
        return [Posting(j.get("title", ""), j.get("location", ""), j.get("jobUrl", ""))
                for j in data.get("jobs", [])]
    raise ValueError(f"unknown ATS platform: {platform}")


def ats_from_url(url: str) -> tuple[str, str] | None:
    """(platform, slug) when the link you already have *is* a board link — the cheap, certain case."""
    for platform, pattern in (
        ("greenhouse", r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#]+)"),
        ("lever", r"lever\.co/([^/?#]+)"),
        ("ashby", r"ashbyhq\.com/([^/?#]+)"),
    ):
        m = re.search(pattern, url)
        if m and m.group(1) not in ("v1", "embed"):
            return platform, m.group(1)
    return None


# ---------------------------------------------------------------- the cold trail
def company_domain(name_or_url: str) -> str:
    """The company's own domain, when the input already carries one. Empty when it doesn't —
    see `guess_company_domain`; we do not go looking."""
    if not name_or_url.startswith(("http://", "https://")):
        return ""
    host = urlparse(name_or_url).netloc.lower()
    return "" if any(d in host for d in _NOT_COMPANY_DOMAINS) else host


def guess_company_domain(company: str) -> str:
    """STUB — careers-page discovery by domain-guessing is deliberately not implemented.

    Trying `<company>.com/careers` is exactly the confidently-wrong-URL failure this module exists to
    avoid: acme.com may be a squatter, a namesake, or a different Acme, and its careers page would be
    reported as this company's openings. The honest answer is an open question in the brief, which a
    driving agent with web search can answer (spec §The brief, path 2).

    Returns "" always. An implementation would need a search tool, not a URL template.
    """
    return ""


def read_page(url: str, *, fetch=default_fetch) -> str:
    """Read a page as text through the Jina reader — `fetch.py`'s generic fallback path.

    Returns "" for anything that isn't real content: a raise, a bot-wall, or a stub page.
    """
    try:
        text = (fetch(f"{JINA_PREFIX}{url}") or "").strip()
    except Exception:  # noqa: BLE001 — any failure means that door was shut; the caller reports it
        return ""
    if _is_block_page(text) or len(text) < _MIN_PAGE:
        return ""
    return text


def careers_page(domain: str, *, fetch=default_fetch) -> BoardResult:
    """Try the two obvious paths on a company's own domain: `/careers`, then `/jobs`.

    Not a search and not a guess — the domain must have come from a link we already had.
    """
    result = BoardResult(company=domain, ok=False)
    if not domain:
        result.detail = "⚠ no company domain in the link — couldn't try a careers page"
        return result
    for path in ("careers", "jobs"):
        url = f"https://{domain}/{path}"
        result.attempts.append(url)
        text = read_page(url, fetch=fetch)
        if text:
            return BoardResult(company=domain, ok=True, source="careers-page", url=url, text=text,
                               attempts=result.attempts)
    result.detail = f"⚠ couldn't read {domain}/careers or {domain}/jobs"
    return result


def list_company_jobs(name_or_url: str, *, fetch=default_fetch) -> BoardResult:
    """Everything currently open at a company — board first, careers page second, honest third.

    `name_or_url` is a company name or any link you already have for them. `ok=False` means *we
    couldn't look*, never *nothing is open* — those two are different answers and the caller is
    entitled to tell them apart, so a board that answers with an empty list is `ok=True`.
    """
    attempts: list[str] = []
    domain = company_domain(name_or_url)
    is_url = name_or_url.startswith(("http://", "https://"))
    known = ats_from_url(name_or_url) if is_url else None

    if known:
        # The link itself names the board — one certain lookup, no probing.
        company, candidates = known[1], [known]
    else:
        # A bare name, or a link to the company's own site: probe the three boards for a slug built
        # from what we have. Not a guess — a slug that isn't theirs 404s, and only an endpoint that
        # answers is ever reported.
        company = _name_from_domain(domain) if domain else name_or_url
        # An aggregator link names no company, so there is no slug to probe and nothing to guess
        # from — the trail is already cold. (Ticket 04's agent resolves the employer name upstream.)
        candidates = [] if (is_url and not domain) else \
            [(p, s) for s in _slugs(company) for p in ("greenhouse", "lever", "ashby")]

    for platform, slug in candidates:
        url = board_url(platform, slug)
        attempts.append(url)
        try:
            postings = _parse_board(platform, fetch(url))
        except Exception:  # noqa: BLE001 — 404 / not-JSON / network: this board isn't theirs
            continue
        # It parsed, so this board *is* theirs. Zero postings is then a real answer — a company
        # with nothing open — and reporting it as a failed lookup would be its own dishonesty.
        return BoardResult(company=company, ok=True, source=platform, url=url,
                           postings=postings, attempts=attempts)

    # Cold trail: the company's own domain, if the link we were given carried one.
    fallback = careers_page(domain, fetch=fetch)
    fallback.company = company
    fallback.attempts = attempts + fallback.attempts
    if fallback.ok:
        return fallback

    fallback.detail = (f"⚠ couldn't find open roles for {company} — no Greenhouse/Lever/Ashby board "
                       f"answered, and {fallback.detail.removeprefix('⚠ ')}")
    return fallback
