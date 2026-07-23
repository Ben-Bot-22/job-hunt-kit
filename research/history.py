"""Have I dealt with these people before? — the pre-apply check against your own record.

Three sources, all local, all read-only (spec §The tools):

    profile/skiplist.md       ids Ben hand-recorded as applied or rejected, with the reason
    data/corpus/applied.json  the applied-jobs sheet, synced by `/sync-applied`
    data/corpus/state-*.json  the scored corpus — every job the daily pipeline has judged

And one finding none of those three answers on its own: **the same job description already in the
corpus under a different company name**, which is one client req being shopped by three agencies.
Genesis10 posting a req for an unnamed "Major Financial Institution" is the worked example in the
spec; the corpus has ~30 such pairs today. It is the finding that is hardest to spot by hand, because
nothing about the two postings matches except the prose.

The failure direction that costs something: **a missed hit**. It means cold-applying somewhere Ben is
already in process — the College Board near-miss `triage/test_correspondence.py` was written for. A
spurious hit costs him one line to read in a brief. So company matching and JD matching are both
tuned to over-report rather than under-report, and every finding carries what it was matched on.

The second thing this module refuses to do is blur *no history* into *couldn't read the record*. A
cold clone has an empty corpus and the honest answer is "nothing recorded"; a corrupt state file is a
different answer entirely. Both arrive as `sources`, and `ok` is False only for the second.

Paths are parameters so the whole thing is assertable offline against fixture files. `research/` is a
leaf and may not import another leaf, so the path constants below are deliberately a small duplicate
of `triage/config.py`. That duplicate stands until the corpus paths themselves move to `core/`, which
is a stage-5 question — collapsing only the id normalizer onto `core.models` would halve the copy
while leaving the same seam, so both halves wait together.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from core.settings import PROFILE_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "corpus"
# Resolved by `core/settings.py` rather than spelled out here, so `JOBSDB_CONFIG_HOME` moves this file
# with the rest of the profile. Two spellings of the same path is how the demo run reads one skiplist
# and the research agent reads another.
SKIPLIST = PROFILE_DIR / "skiplist.md"

# JD similarity: word 5-grams, compared by overlap coefficient (|A∩B| / smaller set) rather than
# Jaccard, so a long agency posting still matches the shorter direct one it was copied from. 0.25 is
# well clear of the noise floor — unrelated JDs in the corpus share ~0 five-grams even when both are
# full-stack boilerplate — and low enough to catch a req with a rewritten intro.
_SHINGLE = 5
_SAME_JD = 0.25

# Same legal-suffix list as `core.models._LEGAL`, so a company key computed here means what it
# means there.
_LEGAL = re.compile(r"\b(inc|llc|l\.l\.c|corp|corporation|ltd|limited|co|plc|lp|llp)\b\.?")
_PUNCT = re.compile(r"[^a-z0-9 ]")


# ---------------------------------------------------------------- findings
@dataclass
class Applied:
    """A row from the applied-jobs sheet. `date` and `note` are what Ben wrote; both go in the brief."""
    company: str
    title: str = ""
    date: str = ""
    url: str = ""
    confidence: str = ""
    note: str = ""
    matched_on: str = "company"   # company | url


@dataclass
class Skipped:
    """A skiplist line: the id, plus the `#` note, which is where the reason lives."""
    job_id: str
    company: str = ""
    title: str = ""
    reason: str = ""


@dataclass
class Scored:
    """A job this company posted that the pipeline has already judged."""
    company: str
    title: str = ""
    link: str = ""
    verdict: str = ""
    fit_score: int | None = None
    first_seen: str = ""          # run date, from the state filename
    last_seen: str = ""


@dataclass
class SameJD:
    """The same posting in the corpus under a *different* company name — the agency-shopping finding.

    `overlap` is the 5-gram overlap coefficient (1.0 = one text contains the other's every phrase).
    `probe_title` names which of this company's postings it matched, so the pair is checkable by hand.
    """
    company: str
    title: str = ""
    link: str = ""
    seen: str = ""
    overlap: float = 0.0
    probe_title: str = ""


@dataclass
class Source:
    """Where a source stood when we looked. `state` is read | absent | unreadable.

    `absent` is a fresh clone with nothing recorded yet — a real "no history". `unreadable` is a file
    that exists and didn't parse, which is not evidence of anything and must not read as a clean slate.
    """
    name: str
    state: str
    detail: str = ""


@dataclass
class History:
    """What the record has on this company. Empty lists mean nothing found — check `ok` first.

    `ok` is False when any source was unreadable: the answer is then incomplete, and a caller that
    prints "no history" off it is telling Ben something the module never established.
    """
    company: str
    applied: list[Applied] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    scored: list[Scored] = field(default_factory=list)
    same_jd: list[SameJD] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(s.state == "unreadable" for s in self.sources)

    @property
    def found(self) -> bool:
        return bool(self.applied or self.skipped or self.scored or self.same_jd)

    @property
    def detail(self) -> str:
        """One line in the worklist's "⚠ couldn't" voice, or the plain no-history statement."""
        bad = [s for s in self.sources if s.state == "unreadable"]
        if bad:
            return "⚠ couldn't read " + "; ".join(f"{s.name} ({s.detail})" for s in bad)
        if self.found:
            return ""
        absent = [s.name for s in self.sources if s.state == "absent"]
        if absent:
            return (f"no history with {self.company} — nothing recorded yet in "
                    f"{', '.join(absent)}")
        return f"no history with {self.company} — checked applied record, skiplist and scored corpus"


# ---------------------------------------------------------------- identity
def _norm(s: str) -> str:
    return " ".join(_PUNCT.sub(" ", (s or "").lower()).split())


def company_key(company: str) -> str:
    """`The College Board, Inc.` -> `thecollegeboard`. Squashed, so punctuation and spacing drift
    ("Genesis10" / "Genesis 10") can't hide a hit."""
    return "".join(_LEGAL.sub(" ", _norm(company)).split())


def same_company(a: str, b: str) -> bool:
    """Whole-name equality, or one name inside the other — `College Board` matches `The College Board`.

    The containment arm needs 5 characters so short keys can't collide; it over-matches by design
    (`Insight` inside `InsightGlobal`), because a spurious brief line is cheaper than a missed one.
    """
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long = sorted((ka, kb), key=len)
    return len(short) >= 5 and short in long


def _shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(words[i:i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# ---------------------------------------------------------------- the three sources
def _read_json(path: Path, source: str) -> tuple[object | None, Source]:
    if not path.exists():
        return None, Source(source, "absent", f"{path.name} not written yet")
    try:
        return json.loads(path.read_text()), Source(source, "read")
    except (OSError, ValueError) as e:
        return None, Source(source, "unreadable", str(e)[:120])


def applied_hits(company: str, *, corpus_dir: Path = CORPUS_DIR) -> tuple[list[Applied], Source]:
    """Rows from the applied sheet. Also matches on the apply URL's host, because the sheet's company
    column is often blank while the link still names who it went to."""
    data, source = _read_json(corpus_dir / "applied.json", "applied record")
    if source.state == "read" and not isinstance(data, list):
        # Parsed, but not the list of records this file is supposed to hold — that is a broken cache,
        # not an empty one, and reporting it as "read" would turn it into a clean slate.
        return [], Source("applied record", "unreadable", "applied.json is not a list of records")
    if not isinstance(data, list):
        return [], source
    key, hits = company_key(company), []
    for row in data:
        if not isinstance(row, dict):
            continue
        rec_company = str(row.get("company") or "")
        matched = "company" if same_company(company, rec_company) else ""
        if not matched and key and len(key) >= 5:
            host = urlparse(str(row.get("url") or "")).netloc.lower()
            if key in re.sub(r"[^a-z0-9]", "", host):
                matched = "url"
        if matched:
            hits.append(Applied(company=rec_company or company, title=str(row.get("title") or ""),
                                date=str(row.get("apply_date") or ""), url=str(row.get("url") or ""),
                                confidence=str(row.get("confidence") or ""),
                                note=str(row.get("note") or ""), matched_on=matched))
    return hits, source


def skiplist_hits(company: str, *, skiplist: Path = SKIPLIST) -> tuple[list[Skipped], Source]:
    """Lines Ben recorded by hand: `company|title|city   # rejected — 2026-07-20, reason`.

    The note after `#` is the whole point — a skiplist hit without its reason tells him he said no
    once but not why, which is exactly when he re-approaches anyway.
    """
    if not skiplist.exists():
        return [], Source("skiplist", "absent", f"{skiplist.name} not present")
    try:
        lines = skiplist.read_text().splitlines()
    except OSError as e:
        return [], Source("skiplist", "unreadable", str(e)[:120])
    hits, in_comment = [], False
    for line in lines:
        # The shipped file keeps two worked examples inside an HTML comment. They are ids in every
        # respect except being true, so a reader that takes them literally reports `acme` as rejected.
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        job_id, _, note = line.partition("#")
        job_id = job_id.strip()
        if "|" not in job_id:               # prose, heading or comment — not an id line
            continue
        parts = job_id.split("|")
        if same_company(company, parts[0]):
            hits.append(Skipped(job_id=job_id, company=parts[0],
                                title=parts[1] if len(parts) > 1 else "", reason=note.strip()))
    return hits, Source("skiplist", "read")


def _corpus_jobs(corpus_dir: Path) -> tuple[list[tuple[str, dict]], list[Source]]:
    """Every scored job in the corpus as (run date, job). One unreadable state file is reported as
    unreadable and the rest are still read — a partial answer beats no answer, as long as it says so."""
    files = sorted(corpus_dir.glob("state-*.json"))
    if not files:
        return [], [Source("scored corpus", "absent", "no state-*.json in the corpus yet")]
    jobs, sources, read_any = [], [], False
    for path in files:
        # state-2026-07-20-094851.json -> 2026-07-20
        date = "-".join(path.stem.split("-")[1:4])
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            sources.append(Source(f"scored corpus ({path.name})", "unreadable", str(e)[:120]))
            continue
        read_any = True
        for job in data.get("jobs", []) if isinstance(data, dict) else []:
            if isinstance(job, dict):
                jobs.append((date, job))
    if read_any:
        sources.insert(0, Source("scored corpus", "read", f"{len(files)} state file(s)"))
    return jobs, sources


def check_my_history(company: str, *, jd: str = "", corpus_dir: Path = CORPUS_DIR,
                     skiplist: Path = SKIPLIST) -> History:
    """Everything the local record holds on `company`, plus the same-JD-different-name finding.

    `jd` is the job description you're actually looking at, when you have one. Without it the probes
    are this company's own postings already in the corpus, which is the Genesis10 case; with it, a
    brand-new req can be matched against the corpus before it has ever been scored.
    """
    result = History(company=company)

    applied, applied_source = applied_hits(company, corpus_dir=corpus_dir)
    skipped, skip_source = skiplist_hits(company, skiplist=skiplist)
    jobs, corpus_sources = _corpus_jobs(corpus_dir)
    result.applied, result.skipped = applied, skipped
    result.sources = [applied_source, skip_source, *corpus_sources]

    # --- this company's own postings, collapsed across runs
    by_id: dict[str, Scored] = {}
    probes: list[tuple[str, set[str]]] = [("(the JD you gave me)", _shingles(jd))] if jd else []
    for date, job in jobs:
        if not same_company(company, str(job.get("company") or "")):
            continue
        title = str(job.get("title") or "")
        hit = by_id.get(title.lower())
        if hit is None:
            analysis = job.get("analysis") or {}
            hit = by_id[title.lower()] = Scored(
                company=str(job.get("company") or company), title=title,
                link=str(job.get("link") or ""), verdict=str(analysis.get("verdict") or ""),
                fit_score=analysis.get("fit_score"), first_seen=date, last_seen=date)
        hit.first_seen, hit.last_seen = min(hit.first_seen, date), max(hit.last_seen, date)
        text = str(job.get("fetched_jd") or job.get("email_jd_text") or "")
        if text and not jd:
            probes.append((title, _shingles(text)))
    result.scored = sorted(by_id.values(), key=lambda s: s.last_seen, reverse=True)

    # --- the same req under someone else's name
    best: dict[str, SameJD] = {}
    for date, job in jobs:
        other = str(job.get("company") or "")
        if not other or same_company(company, other):
            continue
        text = str(job.get("fetched_jd") or job.get("email_jd_text") or "")
        if not text:
            continue
        shingles = _shingles(text)
        for probe_title, probe in probes:
            score = _overlap(probe, shingles)
            if score < _SAME_JD:
                continue
            key = company_key(other)
            if key not in best or score > best[key].overlap:
                best[key] = SameJD(company=other, title=str(job.get("title") or ""),
                                   link=str(job.get("link") or ""), seen=date,
                                   overlap=round(score, 2), probe_title=probe_title)
    result.same_jd = sorted(best.values(), key=lambda s: s.overlap, reverse=True)
    return result
