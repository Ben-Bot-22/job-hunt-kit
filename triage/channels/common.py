"""Everything about turning EMAIL into `Job`s that is not about *how the email was fetched*.

This module is the half of the old `triage/ingest.py` that has nothing to do with Apple Mail. It
takes email dicts — `{subject, sender, date, mid, content, urls, is_reply}` — and produces jobs; the
transport that produced those dicts is somebody else's problem. `channels/mail.py` supplies them via
AppleScript; a Gmail API adapter would supply the same shape from `users.messages.get(format='raw')`
and reuse every function here verbatim. That is the point of the split: an adapter replaces the
transport and nothing else.

The two hard-won behaviours live here, not in the transport:

  * `_is_correspondence` is DEFAULT-SAFE — a message is a conversation unless it is provably
    automated. Getting it backwards archives a live thread. Do not re-derive it.
  * `_extract_from_email` fails by dropping *that email's* jobs and nothing else, so a failed email
    never reaches the archive list and is re-read on the next run.

The extraction call goes through `core/llm.py`, the single generation path — this module never builds
a model client of its own, so the provider is a line in `config/settings.yaml` rather than a fork.
"""
from __future__ import annotations

import email
import html as _html
import logging
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from email import policy
from functools import lru_cache

from .. import config
from core import llm
from core.fetch import _html_to_text, fetch_jd
from core.models import (EmailExtraction, ExtractedJob, Job, link_identity,
                         normalize_link as _normalize_link)

log = logging.getLogger("triage.channels.common")

_JOB_HINT = re.compile(
    r"\b(job|jobs|role|position|hiring|opportunit|contract|engineer|developer|full[\s-]?stack|"
    r"front[\s-]?end|back[\s-]?end|recruit|applicat|apply|career|remote|greenhouse|lever|ashby|"
    r"linkedin|dice|wellfound|workatastartup)\b", re.I)

# --- Alert vs. correspondence -------------------------------------------------------------------
# A job-board digest and a recruiter writing to Ben personally both match _JOB_HINT — they are full of
# the same words. But they must be treated very differently, which the 2026-07-20 run proved twice:
#
#   * ARCHIVING: the archive list is per-message, but Gmail archives per-THREAD. Archiving one message
#     of a live conversation pulls the whole thread — Ben's own replies and unread mail included — out
#     of the inbox. Three live threads were caught by hand that run, one of them his College Board
#     interview correspondence.
#   * RANKING: a role Ben is already interviewing for is not a fresh lead. College Board ranked fit 86
#     at #2 in Tier 1 while he was between interviews; acting on that list means cold-applying through
#     an agency to a company already mid-process with him.
#
# So correspondence is still EXTRACTED and RANKED (those emails carry real, link-less jobs — Item Cloud
# Blue at 78/76 exists only because triage read a recruiter's email), but it is quarantined from the
# archive list and rendered in its own section rather than mixed into the fresh picks.
#
# Detection is DEFAULT-SAFE: a message is correspondence unless it is provably automated. Getting this
# backwards archives a live conversation, so the failure mode is chosen deliberately.
_AUTOMATED_SENDER = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notification|jobalerts|job-alerts|alerts?@|mailer|"
    r"bounce|newsletter|@indeedemail\.com|@dice\.com|@ziprecruiter\.com|@glassdoor\.com|"
    r"@talent\.linkedin\.com|@e\.linkedin\.com|@linkedin\.com)", re.I)


def _is_correspondence(em: dict) -> bool:
    """True = a human wrote to Ben (or he replied); False = an automated job alert.

    Two independent signals, either of which means 'conversation':
      1. the message is a reply (`In-Reply-To`/`References` present), or
      2. the sender does not look automated.
    """
    if em.get("is_reply"):
        return True
    return not _AUTOMATED_SENDER.search(em.get("sender", "") or "")


_URL = re.compile(r'https?://[^\s"\'<>)]+')
_JOB_HOSTS = ("linkedin.com/comm/jobs/view", "linkedin.com/jobs/view", "greenhouse.io", "lever.co",
              "ashbyhq.com", "indeed.com/viewjob", "indeed.com/rc/clk", "indeed.com/pagead/clk",
              "dice.com/job", "elinks.dice.com/a/sc", "elinks.dice.com/s/c", "workatastartup.com",
              "wellfound.com", "myworkdayjobs.com", "remotevibecodingjobs.com", "ai-jobs.net", "startup.jobs")

_MAX_CONTENT = 16000       # per-email readable chars sent to the extractor (big digests list 60+ jobs;
                           # 6000 only showed the first ~20 — raised so mega-newsletters aren't cut short)
_MAX_URLS = 200            # per-email job URLs kept. A single RemoteVibeCoding digest carries 57.

# --- The three buckets --------------------------------------------------------------------------
# An email is mostly not job links: measured over 82 emails in a 7-day window, 2,456 URLs yielded 534
# job links. Something has to cut the other 78%, so the `_JOB_HOSTS` allowlist earns its keep — but an
# allowlist is default-deny over an OPEN set (new ATS hosts appear constantly), and dropping an
# unrecognized host *silently* is how a whole channel can die unnoticed. So every URL lands in one of
# three buckets and only the middle one disappears without trace:
#
#   1. a known job host        -> a job
#   2. provably not a job      -> dropped silently (an image, a font, an unsubscribe link, site nav)
#   3. anything else           -> UNCLASSIFIED: not fetched, but counted and reported per run
#
# Bucket 3 is the point. A posting on Workable or SmartRecruiters is still not picked up, but it shows
# up in the run summary as an unclassified host and becomes a one-line fix, instead of never having
# existed. Same rot-detector reasoning as the per-source counts in core/scrapers/__init__.py.
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|webp|bmp|css|js|woff2?|ttf|eot|ico|mp4|pdf)(\?|#|$)", re.I)
_JUNK_HOST = re.compile(
    r"(licdn\.com|w3\.org|schema\.org|googleapis\.com|gstatic\.com|typekit\.net|scene7\.com|"
    r"cloudfront\.net|list-manage\.com|awstrack\.me|govdelivery\.com|knak\.io|itunes\.apple\.com|"
    r"play\.google\.com|\bc\.gle\b|sentry\.io|doubleclick\.net)", re.I)
_JUNK_PATH = re.compile(
    r"(unsubscribe|emailunsub|mypreferences|email[-_]?prefs|/help/|/support\b|/settings\b|privacy|"
    r"/terms|/feed/|/mynetwork|/messaging|/notifications|/premium/|/emimp/|home-feed|"
    r"jobs/alerts|jobs/search)", re.I)


def classify_urls(text: str) -> tuple[list[str], list[str]]:
    """(job URLs, unclassified URLs). Deduped on `link_identity`, which is the whole fix for Indeed.

    The old key here was `u.split("?")[0]` — the URL with its query thrown away. Indeed puts the job
    id IN the query (`/rc/clk/dl?jk=...`), so an 18-job Indeed digest collapsed to ONE url and 17
    postings were discarded before anything could look at them; the corpus shows 11 Indeed records
    against LinkedIn's 613 across 1,305 jobs, which is that bug and not thin supply.

    `core.models.link_identity` already solved this properly — it drops a *denylist* of tracking
    params rather than the whole query, precisely because on many ATSs the query IS the posting. This
    now uses it instead of rolling a cruder one, so the two places that decide "same posting?" agree.
    """
    jobs, unknown, seen = [], [], set()
    for u in _URL.findall(text):
        u = _html.unescape(u.rstrip('.,)>"\''))     # hrefs arrive HTML-escaped: `&amp;` -> `&`
        key = link_identity(u)
        if not key or key in seen:
            continue
        if any(h in u for h in _JOB_HOSTS):         # bucket 1 — checked FIRST, so a real job host
            seen.add(key)                           # is never lost to a junk-path substring
            jobs.append(u)
        elif _ASSET.search(u) or _JUNK_HOST.search(u) or _JUNK_PATH.search(u):
            continue                                # bucket 2 — provably not a posting
        else:
            seen.add(key)                           # bucket 3 — reported, never silently dropped
            unknown.append(u)
    return jobs[:_MAX_URLS], unknown[:_MAX_URLS]


def _job_urls(text: str) -> list[str]:
    """Bucket 1 only. Kept as a name because `gmail_api.py` documents it as part of the adapter seam."""
    return classify_urls(text)[0]


def _parse_source(raw: str) -> tuple[str, list[str], bool, list[str]]:
    """Decoded readable text, the job URLs, whether this is a REPLY, and the unclassified URLs.

    `In-Reply-To` / `References` are the definitive "this is part of a conversation" signal — they are
    what distinguishes a recruiter writing back from a job-alert digest. See `_is_correspondence`.

    Takes a raw RFC822 string, which is exactly what both transports have: Apple Mail's `source` and
    the Gmail API's `format='raw'` payload.
    """
    try:
        msg = email.message_from_string(raw, policy=policy.default)
    except Exception:  # noqa: BLE001
        j, u = classify_urls(raw)
        return raw[:_MAX_CONTENT], j, False, u
    is_reply = bool(msg.get("In-Reply-To") or msg.get("References"))
    text_parts, html_parts = [], []
    for part in msg.walk():
        ct = part.get_content_type()
        try:
            body = part.get_content() if ct in ("text/plain", "text/html") else None
        except Exception:  # noqa: BLE001 — undecodable part; skip
            body = None
        if body and ct == "text/plain":
            text_parts.append(body)
        elif body and ct == "text/html":
            html_parts.append(body)
    html = "\n".join(html_parts)
    text = ("\n".join(text_parts) or _html_to_text(html)).strip()
    j, u = classify_urls(html + "\n" + text)
    return text[:_MAX_CONTENT], j, is_reply, u


_EXTRACT_SYSTEM = (
    "You extract job openings from an email. An email may describe zero, one, or many jobs (alert digests "
    "list several). For EACH distinct opening capture: the best apply/posting URL, company, title, source "
    "platform, any posted date shown verbatim, and any JOB-DESCRIPTION text present INLINE in the email "
    "body (recruiter emails often paste the whole JD — capture it; it's the fallback if the link can't be "
    "scraped). You are given the readable body AND a list of the job URLs found in the email's HTML — use "
    "those exact URLs as the links, associating each job with its URL (they are usually in the same order "
    "as the jobs in the body). Keep tracking-wrapped URLs as-is (they still resolve). Return EVERY job "
    "the email lists — a digest of 55 jobs must return 55, and truncating the list loses real postings. "
    "If the email is not about any job, return an empty list. Do not invent URLs or details."
)


# 8000 truncated a 30-job digest mid-JSON -> the whole email was lost; give headroom.
_EXTRACT_MAX_TOKENS = 20000


@lru_cache(maxsize=1)
def _extract_model():
    """The extractor's runnable, built once per process — what `config.client()` used to give it.

    `core.llm.structured` builds a fresh chat model per call and this runs once per email across a
    six-worker pool, so without the cache a 250-email run constructs 250 clients where the native
    path handed out one. Built lazily, inside `_extract_from_email`'s try, so a missing key surfaces
    as the same per-email warning rather than at import.
    """
    return llm.structured(EmailExtraction, config.model("extract"), max_tokens=_EXTRACT_MAX_TOKENS)


def _extract_from_email(em: dict) -> list[Job]:
    """Every job link in the email becomes a Job. The model ENRICHES; it does not decide what exists.

    This inversion is the fix for the largest leak the tool had. The URL list below was assembled
    deterministically and then handed to the model as *advice* — and only what the model wrote back
    became a job, with nothing ever comparing the two. Measured on the 2026-07-20 corpus, no email
    ever yielded more than 20 jobs, against a configured cap of 30 that therefore never fired: the
    RemoteVibeCoding digest titled "55 New Remote Vibe Coding Jobs Today" carried 57 job links and
    returned 20, twice, with no warning. ~37 postings a day went missing in a run that reported
    success.

    So the deterministic half is now authoritative and the model's job is company/title/inline-JD. A
    link the model didn't mention still becomes a job — a bare one, exactly like a `paste` job, which
    `_hydrate` then fetches and backfills. The failure direction flips from "a posting is invisible
    forever" to "one extra HTTP fetch and one cheap prefilter call", which is the trade this codebase
    makes everywhere else (see the dedup and prefilter blocks in config/settings.yaml).
    """
    found = [u for u in (em.get("urls") or []) if u]
    urls = "\n".join(found) or "(none found)"
    user = (f"SUBJECT: {em['subject']}\nFROM: {em['sender']}\nDATE: {em['date']}\n\n"
            f"BODY:\n{em['content']}\n\nJOB URLS FOUND IN THIS EMAIL:\n{urls}")
    extracted: list[ExtractedJob] = []
    try:
        # The system block stays a *list* carrying its `cache_control` marker. LangChain passes the
        # blocks through rather than flattening them, and a flattened string would silently drop the
        # cache hint on a prompt re-sent for every email in the run.
        parsed = _extract_model().invoke([
            ("system", [{"type": "text", "text": _EXTRACT_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}]),
            ("human", user),
        ])
        if parsed is not None:   # the wrapper *raises* where `messages.parse` gave None
            extracted = parsed.jobs
    except Exception as e:  # noqa: BLE001
        # Also catches `OutputParserException` (a refusal or unparseable output, which the native
        # path delivered as `parsed_output=None`) and `core.llm.ConfigurationError` (a missing or
        # wrong provider key). This used to drop the email's jobs entirely — the deliberately harsh
        # direction, on the reasoning that an email with no extracted jobs never reaches the archive
        # list and so is re-read next run. That reasoning survives the inversion, but it no longer
        # requires losing anything: the links were found without the model, so recovery below still
        # yields every posting, and the email still archives only once those jobs resolve.
        log.warning("extraction failed for %r: %s — recovering %d link(s) without it",
                    em["subject"][:60], e, len(found))

    def _mk(**kw) -> Job:
        return Job(email_mid=em.get("mid", ""), from_correspondence=_is_correspondence(em),
                   email_sender=em.get("sender", ""), **kw)

    jobs, claimed = [], set()
    for e in extracted:
        if not (e.link or e.email_jd_text or e.title):
            continue
        link = _normalize_link(e.link.strip())
        if link:
            claimed.add(link_identity(link))
        jobs.append(_mk(link=link, company=e.company.strip(), title=e.title.strip(),
                        source_platform=e.source_platform.strip() or _sender_platform(em["sender"]),
                        posted_hint=e.posted_hint.strip(), email_jd_text=e.email_jd_text.strip()))

    # THE RECONCILIATION. Anything the model didn't account for is still a real posting.
    missed = [u for u in found if link_identity(u) not in claimed]
    if missed:
        log.warning("extractor returned %d job(s) for %r, but the email carries %d job link(s) — "
                    "recovering the %d it left out", len(jobs), em["subject"][:60], len(found), len(missed))
        for u in missed:
            jobs.append(_mk(link=_normalize_link(u), source_platform=_sender_platform(em["sender"])))
    return jobs


# --- Backfilling company and title ----------------------------------------------------------------
# Shared with the `paste` channel, which is where this started: a job that arrives as a bare URL has no
# metadata at all, so the two fields every downstream step reads — company for tiering and the
# applied-cache match, title for ranking and the worklist — have to come out of the JD. It reuses
# `ExtractedJob`, the same model the mail extractor fills, so there is one definition of what "a job
# pulled out of text" is; only `company`, `title` and `source_platform` are read.
#
# It lives here rather than in `paste.py` because the mail channel now produces bare jobs too — the
# links the extractor left out. A channel may not import another channel's private helper, and the
# shared half of channel logic is exactly what this module is.
_BACKFILL_SYSTEM = (
    "You are given the text of ONE job posting. Return the hiring company's name and the job title "
    "EXACTLY as the posting states them — copy the title verbatim, do not shorten it, expand it, "
    "re-word it, or add or drop qualifiers. Also return the source platform (e.g. greenhouse, lever, "
    "linkedin, ashby, company-site) if it is evident. Leave a field as an empty string if the posting "
    "does not state it: never guess a company from the URL and never invent a title. Leave `link`, "
    "`posted_hint` and `email_jd_text` empty."
)

_BACKFILL_MAX_TOKENS = 500
_BACKFILL_JD_CHARS = 6000   # enough for the header and the first requirements block; the title and the
                            # company are always near the top, and this is a per-URL cost


@lru_cache(maxsize=1)
def _backfill_model():
    """Built once per process and lazily, the shape `prefilter` and the mail extractor both use — so a
    missing key surfaces as a per-URL warning at call time rather than at import."""
    return llm.structured(ExtractedJob, config.model("extract"), max_tokens=_BACKFILL_MAX_TOKENS)


def backfill(job: Job, *, default_platform: str = "paste") -> Job:
    """Fill company/title/source_platform from the fetched JD, in place, only where they are missing.

    Fails by leaving the job alone. That is the direction that costs least: a job with neither company
    nor title still has a distinct `Job.id` (the canonical link), still carries its JD, and is still
    scored — it just reads as `? — ?` in the worklist. Refusing to yield the job instead would lose a
    URL that was found fair and square.
    """
    text = job.jd_text.strip()
    if not text or (job.company and job.title):
        return job
    try:
        # The system block stays a *list* carrying `cache_control`: a run over a links file re-sends
        # this prompt once per URL, and a flattened string silently drops the cache hint.
        e = _backfill_model().invoke([
            ("system", [{"type": "text", "text": _BACKFILL_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}]),
            ("human", f"POSTING URL: {job.link}\n\nPOSTING TEXT:\n{text[:_BACKFILL_JD_CHARS]}"),
        ])
        if e is None:      # belt and braces: the wrapper *raises* where `messages.parse` gave None
            return job
        job.company = job.company or (e.company or "").strip()
        job.title = job.title or (e.title or "").strip()
        job.source_platform = job.source_platform or (e.source_platform or "").strip() or default_platform
    except Exception as ex:  # noqa: BLE001 — also OutputParserException / ConfigurationError
        log.warning("could not backfill company/title for %s: %s", job.link, ex)
    return job


def hydrate(jobs: list[Job], *, fetch=fetch_jd, backfill=backfill) -> list[Job]:
    """Fetch + backfill the RECOVERED jobs — the bare links the extractor never described.

    A bare job has no company and no title, so the two fields every downstream step reads have to come
    out of the JD, and `Job.id` is `company|title` falling back to the canonical link only while that
    composite is empty (`core/models.py`). That is the trap `paste.py` documents: a job checked
    against `seen`/`applied` under its link identity and stored under its composite identity is fresh
    again every morning.

    So the ordering is load-bearing in BOTH directions, and this sits in the one window that satisfies
    both — `__main__` calls it *after* the seen/applied gate (`store.py`: all three caches are checked
    before any fetch, and hydrating first would re-fetch every recovered link forever) and *before*
    dedup and scoring (so the job is whole by the time anything judges it). The bridge that makes the
    first half work is `store.save_seen` recording a `url:` key beside the composite id, so tomorrow
    this job is recognised by its link, which is all a bare job has.

    `__main__._fetch` skips a job that already carries a full JD, so nothing is fetched twice.
    """
    todo = [j for j in jobs if j.link and not (j.company and j.title)]
    if not todo:
        return jobs
    log.info("hydrating %d recovered link(s) the extractor did not describe", len(todo))

    def one(j: Job) -> None:
        fetch(j)
        backfill(j, default_platform=j.source_platform or "email")

    with ThreadPoolExecutor(max_workers=config.max_workers()) as ex:
        list(ex.map(one, todo))
    return jobs


def _sender_platform(sender: str) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return (m.group(1).split(".")[0].lower() if m else "")


def _email_source(em: dict) -> str:
    """Classify an email by where the jobs come from — used to spread a --sample across source types.
    Forwarded Dice alerts arrive from Ben's own address, so we also sniff the body for 'dice'."""
    s = (em.get("sender") or "").lower()
    body = (em.get("content") or "")[:600].lower()
    if "linkedin" in s:
        return "linkedin"
    if "indeed" in s:
        return "indeed"
    if "dice" in s or "dice" in body:            # includes Proton-forwarded Dice IntelliSearch alerts
        return "dice"
    if "remotevibecoding" in s or "remotevibecoding" in body:
        return "rvc"
    return _sender_platform(s) or "other"


def _sample_emails(emails: list[dict], n: int) -> list[dict]:
    """Pick ~n representative WHOLE emails, spread across source types (walled sources first so a small
    sample still exercises Tier-2 browser retrieval). Round-robin one per source, then seconds, etc.
    Deterministic given the same inbox (emails arrive date-ordered)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for em in emails:
        buckets[_email_source(em)].append(em)
    order = ["indeed", "dice", "linkedin", "rvc"] + [s for s in buckets if s not in
                                                     ("indeed", "dice", "linkedin", "rvc")]
    picked, idx = [], defaultdict(int)
    while len(picked) < n:
        progressed = False
        for src in order:
            if len(picked) >= n:
                break
            b = buckets.get(src, [])
            if idx[src] < len(b):
                picked.append(b[idx[src]])
                idx[src] += 1
                progressed = True
        if not progressed:                       # ran out of emails before hitting n
            break
    log.info("sample: %d emails across sources %s", len(picked),
             ", ".join(f"{_email_source(e)}" for e in picked))
    return picked


def jobs_from_emails(emails: list[dict], days: int, sample: int | None = None) -> list[Job]:
    """The gate → sample → parallel-extract loop, shared by every mail-shaped channel.

    Returns every extracted job PRE-dedup: the collapse is the registry's job (`channels.ingest`),
    because two channels can supply the same posting and only a cross-channel pass can see that.
    `days` is carried for the log line only — the transport already applied the window.
    """
    kept = [e for e in emails if _JOB_HINT.search(f"{e['subject']} {e['content']}")]
    log.info("read %d emails (%dd); %d plausibly job-related, %d gated out",
             len(emails), days, len(kept), len(emails) - len(kept))
    if sample:
        kept = _sample_emails(kept, sample)
    with ThreadPoolExecutor(max_workers=6) as ex:
        batches = list(ex.map(_extract_from_email, kept))
    jobs = [job for batch in batches for job in batch]
    _report_unclassified(kept)
    n_links = sum(len(e.get("urls") or []) for e in kept)
    log.info("mail: %d job link(s) across %d email(s) -> %d job(s)", n_links, len(kept), len(jobs))
    return jobs


# Bucket 3 is only worth reporting if the report gets read, and the raw bucket does not: measured over
# one 7-day window it held 565 links on 66 hosts, the top four being a tyre shop, a health plan, a
# domain registrar and YouTube. So the line reports the JOB-SHAPED residue only — a host that either
# names itself like an ATS or serves a path that names itself like a posting. Everything else is
# counted and not named, because the count is what tells you the filter is still roughly right.
_ATS_HOST = re.compile(r"^(jobs?|careers?|apply|boards?|hire|hiring|recruit\w*|talent|work)[.-]|"
                       r"(workable|smartrecruiters|icims|jazzhr|bamboohr|recruitee|teamtailor|"
                       r"jobvite|breezy|rippling|pinpointhq|taleo|successfactors|paylocity|"
                       r"applytojob|workforcenow|myworkdayjobs|ashby|greenhouse|lever)", re.I)
_JOB_PATH = re.compile(r"/(jobs?|careers?|apply|positions?|vacanc|openings?|postings?|req)\b", re.I)


def _report_unclassified(emails: list[dict]) -> None:
    """Bucket 3, counted by host — the only visible trace an un-allowlisted job board leaves.

    This is the line to read when a channel goes quiet. `apply.workable.com x4` here means four real
    postings were seen and not fetched, and the fix is one entry in `_JOB_HOSTS`. Without it, an ATS
    the tool has never heard of is indistinguishable from an inbox that had nothing in it — which is
    exactly how Indeed sat at 11 records against LinkedIn's 613 for a month without anyone noticing.
    """
    hosts, total = Counter(), 0
    for em in emails:
        for u in em.get("unclassified") or []:
            total += 1
            m = re.match(r"https?://([^/?#]+)", u)
            if m and (_ATS_HOST.search(m.group(1)) or _JOB_PATH.search(u[len(m.group(0)):])):
                hosts[m.group(1).lower()] += 1
    if not total:
        return
    if not hosts:
        log.info("%d unclassified link(s), none job-shaped", total)
        return
    named = ", ".join(f"{h} x{n}" for h, n in hosts.most_common(12))
    log.warning("%d unclassified link(s), %d of them JOB-SHAPED on %d host(s) — seen and not fetched. "
                "Add the real job boards to _JOB_HOSTS: %s", total, sum(hosts.values()), len(hosts), named)


# NOTE: the tool does NOT move Gmail mail itself. Apple Mail's AppleScript `move` can't reliably archive
# a Gmail message (it dual-labels — adds the target label but leaves INBOX; confirmed live + widely
# documented). Instead it writes an archive list (below) and a Claude session moves them via the Gmail
# connector (add label, remove INBOX). See docs/operating/triage-operating.md → "Archiving".


def archive_list_lines(all_extracted: list[Job], resolved_keys: set[str], label: str, day: str) -> tuple[list[str], int]:
    """Lines for data/runs/archive-<date>.txt: emails whose EVERY extracted job is resolved.

    Works off the FULL pre-dedup extraction and a set of resolved DEDUP KEYS (not ids). A job that was a
    duplicate of another (same dedup key) is resolved once its twin is analyzed — so an email whose only
    jobs are duplicates of jobs seen in other emails still archives (no loose ends), while nothing is
    ever missed (each unique job is still analyzed once). Grouping by email_mid keeps it --limit-safe: an
    email with any un-resolved job is not 'done'. Pure/testable — no I/O.

    A job from a non-mail channel has no `email_mid` and is skipped by the first line of the loop, which
    is why paste- and board-sourced jobs need no special handling here."""
    by_mid: dict[str, list[Job]] = {}
    skipped_corr = 0
    for j in all_extracted:
        if not j.email_mid:
            continue
        # NEVER archive a human conversation. Gmail archives per-THREAD while this list is per-message,
        # so one line here can pull an entire live thread — replies, unread mail and all — out of the
        # inbox. On 2026-07-20 that would have hit Ben's College Board interview correspondence.
        if j.from_correspondence:
            skipped_corr += 1
            continue
        by_mid.setdefault(j.email_mid, []).append(j)
    if skipped_corr:
        log.info("archive: held back %d job(s) from human correspondence — never auto-archived",
                 skipped_corr)
    done = {mid: group for mid, group in by_mid.items()
            if all(_dedup_key(j) in resolved_keys for j in group)}
    if not done:
        return [], 0
    lines = [f"# ARCHIVE LIST — move these {len(done)} emails out of INBOX into '{label}'.",
             f"# A Claude session archives them: for each, search rfc822msgid:<id>, add '{label}', remove INBOX.",
             f"# Format: <message-id> TAB label TAB context.  Generated {day}."]
    for mid, group in done.items():
        g = group[0]
        lines.append(f"{mid}\t{label}\t{len(group)} job(s): {g.company or '?'} — {g.title or '?'}")
    return lines, len(done)


def _dedup_key(job: Job) -> str:
    """Identity used to collapse the same job seen twice — in two emails, or on two channels: the URL
    (query stripped), else composite id. Shared by the registry's dedup and the archive check so a
    dropped duplicate maps back to its twin."""
    return (job.link.split("?")[0].rstrip("/") if job.link else "") or job.id
