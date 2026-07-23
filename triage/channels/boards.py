"""The `boards` channel — a watchlist of company job boards, not a sweep of the internet.

The user names the Greenhouse and Lever boards they care about; this asks each one what is new. Both
board APIs are keyless for reads, so this channel needs no key, no OAuth and no inbox, and it works on
any OS. There is nothing to scrape and therefore nothing to rot: a board that changes its HTML doesn't
touch us, and a board that goes away 404s and costs you that board only.

    channels:
      boards:
        enabled: true
        greenhouse: [anthropic, stripe]
        lever: [brex, matterport]

**What arrives here is better than what arrives by mail.** The listing endpoint states the company,
the title, the location and — where the employer publishes one — the pay range, so identity is
well-formed at the source and nothing has to be inferred from an email or guessed by a model. That is
why this channel must NOT copy `paste`'s shape: paste fetches and backfills because a bare URL has no
company and no title and would otherwise take `Job.id`'s link fallback; boards is handed both.

**One request per board, JD included.** Greenhouse's `?content=true` and Lever's `?mode=json` both
return the full description in the listing response, so a board of 400 postings costs one HTTP call
rather than 401. Those jobs enter the pipeline with `jd_source="full"`, which `__main__._fetch` then
leaves alone — the same guard `paste` relies on.

Parsing of the description itself is `core.fetch.greenhouse_content` / `lever_content`, the exact
functions the per-URL JD fetch uses. Same objects, same fields, one parser: if this channel and the
JD fetch ever disagreed about what a Greenhouse JD says, the disagreement would show up as a job
scored on different text depending on which door it came through.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .. import config
from core.fetch import _MIN_JD, _get, greenhouse_content, lever_content
from core.models import Job, normalize_link

log = logging.getLogger("triage.channels.boards")

_GREENHOUSE_LIST = ("https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
                    "?content=true&pay_transparency=true")
_LEVER_LIST = "https://api.lever.co/v0/postings/{token}?mode=json"

# Per-board cap, applied AFTER the freshness window and newest-first, in the spirit of mail's
# `_MAX_EMAILS`. A 500-posting enterprise board that republishes everything at once should cost one
# noisy run, not a run that never finishes.
_MAX_PER_BOARD = 200

# Lever states the interval as a slug. Rendered into words because this line goes into the JD text the
# analyzer reads, and "per-year-salary" invites it to guess.
_LEVER_INTERVAL = {"per-year-salary": "per year", "per-month-salary": "per month",
                   "per-week-salary": "per week", "per-day-wage": "per day",
                   "per-hour-wage": "per hour", "one-time": "one time"}


def _get_json(url: str):
    """The one network call this module makes. Injected in tests; `core.fetch._get` raises for status."""
    return _get(url, timeout=30.0).json()


# --- normalizing what the two APIs each call the same thing ---------------------------------------

def _company_from_token(token: str) -> str:
    """Lever's listing response has no company field at all — the board token *is* the company handle.

    Casing doesn't reach identity (`composite_id` lowercases and strips punctuation), so this only
    decides how the company reads in the worklist. Greenhouse states `company_name` and uses it.
    """
    return " ".join(w.capitalize() for w in token.replace("-", " ").replace("_", " ").split())


def _iso(value: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _epoch_ms(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _money(amount: float) -> str:
    return f"{amount:,.0f}"


def _greenhouse_pay(job: dict) -> str:
    """`pay_input_ranges` — present only with `?pay_transparency=true`, and only where the employer
    published a range. Amounts are in CENTS; the employer's own label ("Annual Salary:") carries the
    interval, so it is quoted rather than re-derived."""
    out = []
    for r in job.get("pay_input_ranges") or []:
        lo, hi = r.get("min_cents"), r.get("max_cents")
        if not (lo or hi):
            continue
        label = (r.get("title") or "Pay range").strip().rstrip(":")
        cur = (r.get("currency_type") or "").strip()
        out.append(f"{label}: {_money((lo or 0) / 100)}–{_money((hi or lo) / 100)} {cur}".strip())
    return " · ".join(out)


def _lever_pay(job: dict) -> str:
    """`salaryRange` — whole currency units, not cents, and an interval slug."""
    s = job.get("salaryRange") or {}
    lo, hi = s.get("min"), s.get("max")
    if not (lo or hi):
        return ""
    cur = (s.get("currency") or "").strip()
    slug = (s.get("interval") or "").strip()
    interval = _LEVER_INTERVAL.get(slug, slug)
    return " ".join(x for x in (f"Pay range: {_money(lo or 0)}–{_money(hi or lo)}", cur, interval) if x)


def _jd_text(*, title: str, company: str, location: str, pay: str, posted: str, body: str) -> str:
    """The board's own facts, stated above the description.

    The pay range is put HERE rather than on a new `Job` field on purpose: the analyzer's `rate` comes
    out of the JD text, so a range parked in a field nothing renders would be captured and then never
    read. Nothing in `prefilter.hard_skip` can trip on these lines — its year rule needs the word
    "experience" adjacent and its travel rule needs the word "travel".
    """
    head = [f"{title} — {company}" if company else title]
    if location:
        head.append(f"Location: {location}")
    if pay:
        head.append(f"Compensation (employer-stated): {pay}")
    if posted:
        head.append(f"Posted: {posted}")
    return "\n".join(h for h in head if h.strip()) + ("\n\n" + body if body else "")


def _make(*, link: str, company: str, title: str, platform: str, location: str, pay: str,
          posted: datetime | None, body: str) -> Job:
    hint = posted.date().isoformat() if posted else ""
    jd = _jd_text(title=title, company=company, location=location, pay=pay, posted=hint, body=body)
    job = Job(link=normalize_link(link.strip()), company=company, title=title,
              source_platform=platform, posted_hint=hint)
    # A board whose description came back empty or stubby is left as `title_only`, so the pipeline's
    # fetch pool goes and gets the JD from the posting URL the normal way. Claiming "full" on a
    # 40-character stub would send that stub to the analyzer as if it were the job.
    if len(jd.strip()) >= _MIN_JD and body.strip():
        job.fetched_jd, job.jd_source = jd, "full"
    else:
        job.email_jd_text = jd     # the guaranteed fallback slot; `jd_text` reads it when there's no scrape
    return job


# --- one board at a time --------------------------------------------------------------------------

def _greenhouse_board(token: str, since: datetime | None, get) -> list[Job]:
    data = get(_GREENHOUSE_LIST.format(token=quote(token, safe="")))
    rows = []
    for j in (data or {}).get("jobs") or []:
        if not isinstance(j, dict):
            continue
        # `first_published` is when the posting went live; `updated_at` moves on any edit, so it would
        # read a typo fix as a new job. Fall back to it only when the board doesn't state the first.
        posted = _iso(j.get("first_published")) or _iso(j.get("updated_at"))
        if since and posted and posted < since:
            continue
        rows.append((posted, j))
    return [_make(link=j.get("absolute_url", "") or "",
                  company=(j.get("company_name") or "").strip() or _company_from_token(token),
                  title=(j.get("title") or "").strip(),
                  platform="greenhouse",
                  location=((j.get("location") or {}).get("name") or "").strip(),
                  pay=_greenhouse_pay(j),
                  posted=posted,
                  body=greenhouse_content(j))
            for posted, j in _newest_first(rows)]


def _lever_board(token: str, since: datetime | None, get) -> list[Job]:
    data = get(_LEVER_LIST.format(token=quote(token, safe="")))
    rows = []
    for j in data or []:
        if not isinstance(j, dict):
            continue
        posted = _epoch_ms(j.get("createdAt"))
        if since and posted and posted < since:
            continue
        rows.append((posted, j))
    out = []
    for posted, j in _newest_first(rows):
        cats = j.get("categories") or {}
        location = (cats.get("location") or "").strip()
        workplace = (j.get("workplaceType") or "").strip()
        out.append(_make(link=j.get("hostedUrl") or j.get("applyUrl") or "",
                         company=_company_from_token(token),
                         title=(j.get("text") or "").strip(),
                         platform="lever",
                         location=" · ".join(x for x in (location, workplace) if x),
                         pay=_lever_pay(j),
                         posted=posted,
                         body=lever_content(j)))
    return out


def _newest_first(rows: list[tuple[datetime | None, dict]]) -> list[tuple[datetime | None, dict]]:
    """Newest first, undated last, then capped — so `_MAX_PER_BOARD` and `sample` cut the stale end.

    An undated posting is KEPT, not dropped. A board that states no dates would otherwise go
    permanently silent, and the cost of keeping it is one noisy first run: from the second run on the
    `seen` cache filters it, because a board job's id is the API's own company and title.
    """
    dated = sorted((r for r in rows if r[0]), key=lambda r: r[0], reverse=True)
    undated = [r for r in rows if not r[0]]
    return (dated + undated)[:_MAX_PER_BOARD]


_ATS = {"greenhouse": _greenhouse_board, "lever": _lever_board}


def fetch(days: int, sample: int | None = None, *,
          boards: dict[str, list[str]] | None = None, get=_get_json) -> list[Job]:
    """The channel contract: every posting on the watched boards inside the freshness window.

    `boards` and `get` are keyword-only injection points for the tests — the registry calls this with
    two positional arguments and gets the configured watchlist and a real HTTP call.

    Each BOARD is wrapped in its own `try/except`, inside the registry's per-CHANNEL one. A 404'd
    token, a board that starts returning HTML, or a rate limit costs you that company's postings and
    nothing else; losing the whole channel because one token was mistyped is the failure this repeats
    the pattern to avoid.
    """
    watchlist = boards if boards is not None else config.board_tokens()
    since = datetime.now(timezone.utc) - timedelta(days=days) if days and days > 0 else None
    jobs: list[Job] = []
    for ats, tokens in watchlist.items():
        board_fetch = _ATS.get(ats)
        if board_fetch is None:
            log.warning("boards: unknown ATS %r — known: %s", ats, ", ".join(_ATS))
            continue
        for token in tokens:
            try:
                got = board_fetch(token, since, get)
            except Exception as e:  # noqa: BLE001 — one bad board shouldn't cost the other boards
                log.warning("boards: %s/%s failed: %s: %s", ats, token, type(e).__name__, e)
                continue
            log.info("boards: %s/%s — %d posting(s) in the window", ats, token, len(got))
            jobs.extend(got)
    # A posting needs a link to apply to and a title to be identified by. The title matters more than
    # it looks: the company falls back to the board token, so a title-less posting would get the id
    # `<token>||` — and every title-less posting on that board would share it. That is stage 4 · 01's
    # `"||"` collision wearing a board's name, and a malformed board row is not worth reopening it for.
    jobs = [j for j in jobs if j.link and j.title]
    return jobs[:sample] if sample else jobs
