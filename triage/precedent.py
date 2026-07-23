"""Memory for the scorer: the most similar past decisions, retrieved and put in front of Opus.

`analyze.py` has always judged each job alone. The cost of that is visible in `profile/rubric.md`, which
hard-codes past calibration failures **by name** — *"Linda Werner, Project Coordinator III ->
LOW_FIT (was WRONGLY scored 82)"*, *"TMS LLC — hard-requires Next.js… strong AI overlap does NOT
rescue a mandatory-tech gap"*. That list is maintained by hand and grows with every mistake. This
module is the same memory, automatic.

**Precedent is evidence, never authority — and that is not a nicety, it is the thing that makes this
safe.** The corpus contains the very mis-scores the rubric was written to correct: Linda Werner's
`Project Coordinator III` sits in the index at **82 STRONG_FIT**, and it retrieves for exactly the
agency/contract queries this module runs. Injected naively, it would re-teach the error the rubric
exists to prevent, wearing the authority of "here is how you judged this before". So the block says
so in words: the goal profile is deterministic and read in full on every call; precedents are
probabilistic and retrieved; where they disagree, the rule wins.

Two consequences that shaped the format:

  * **The verdict and the reasoning ship with the number.** A bare score invites anchoring; a verdict
    plus the one-line why is what lets the model notice a precedent that contradicts the rubric.
  * **No JD text.** Precedents are for consistency of *reasoning*, not for copying scores, and three
    JDs would be ~4k tokens of un-cached prompt on every scored job.

Everything here fails soft. A missing index, a missing model, a corrupt file: `for_job` returns `""`
and the job is scored exactly as it is today. Day one for a stranger with no history is the same
code path as a broken index, and neither blocks the morning run.
"""
from __future__ import annotations

import logging
import threading

from langchain_core.documents import Document

from . import config
from core.index import INDEX_FILENAME, JobIndex, build_index
from core.models import Job, composite_id

log = logging.getLogger("triage.precedent")

_HEADER = "===== PAST DECISIONS ON SIMILAR JOBS (precedent — evidence, not authority) ====="
_FOOTER = "===== END PAST DECISIONS ====="

# Read on every scored job, so it is written once and worded to be unambiguous. The precedence rule
# is stated rather than implied: leaving the model to infer which of two conflicting inputs wins is
# how a mis-scored precedent quietly becomes the new calibration.
_PREAMBLE = (
    "Below are YOUR OWN earlier judgments on the jobs most similar to this one, chosen to be "
    "different from each other rather than three views of the same posting.\n"
    "HOW TO USE THEM:\n"
    "  * The GOAL PROFILE ABOVE OUTRANKS EVERY PRECEDENT. It is read in full on every call and is "
    "the rubric; these are retrieved and merely probable. Where a precedent conflicts with a rule, "
    "a hard gate or a calibration case in the goal profile, THE RULE WINS and the precedent is "
    "simply a past mistake — some of these ARE past mistakes, which is why those rules exist.\n"
    "  * Use them for consistency of REASONING, not to copy a score. Do not regress toward whatever "
    "you happened to say about a similar job before.\n"
    "  * They are the standing record of what disqualified similar roles — a mandatory-tech gap, a "
    "coordinator role shape behind engineering keywords, an undisclosed rate. If this job repeats a "
    "pattern that capped one of these, name that gate here too.\n"
    "  * If a precedent informed your judgment, cite it in the `precedent` field: which one, and "
    "whether you followed it or departed from it and why. Leave `precedent` empty if none applied."
)

_MAX_WHY = 300      # chars — one line of reasoning, not a paragraph
_MAX_QUERY_JD = 1500  # bge-small reads ~512 word pieces; more text is embedded weight, not signal

_lock = threading.Lock()
_index: JobIndex | None = None
_index_failed = False


def index() -> JobIndex | None:
    """The process-wide index, opened once from disk. `None` if there isn't a usable one.

    Read-only and lazy: scoring never *builds* the index (that is `refresh()`, at the end of a run),
    because embedding 1,000 documents in the middle of a scoring pass would put a 40-second stall in
    front of the first job and index a run against itself.
    """
    global _index, _index_failed
    if _index is not None or _index_failed:
        return _index
    with _lock:
        if _index is None and not _index_failed:
            path = config.CORPUS_DIR / INDEX_FILENAME
            if not path.exists():
                _index_failed = True
                log.info("no index at %s — scoring without precedent (built at the end of a run)", path)
            else:
                try:
                    _index = JobIndex(path)
                except Exception as e:  # noqa: BLE001 — memory is an enhancement, never a blocker
                    _index_failed = True
                    log.warning("could not open the index (%s) — scoring without precedent", e)
    return _index


def refresh() -> int:
    """Fold this run's decisions into the index so tomorrow can retrieve them. Returns docs added.

    Called after the state file is written, never before scoring: today's judgments become
    precedent for tomorrow, and a job is never its own precedent. Incremental — a morning that
    added one run embeds that run only.
    """
    idx = build_index(config.CORPUS_DIR, index_path=config.CORPUS_DIR / INDEX_FILENAME)
    return len(idx)


def find(job: Job, *, idx: JobIndex | None = None, k: int | None = None) -> list[Document]:
    """The `k` most similar *and mutually different* past decisions on jobs other than this one."""
    idx = idx if idx is not None else index()
    if idx is None:
        return []
    own = composite_id(job.company, job.title)
    return idx.retrieve(
        query(job),
        k=k if k is not None else config.precedent_k(),
        filter=lambda d: _is_precedent(d) and d.metadata.get("id") != own,
    )


def query(job: Job) -> str:
    """What the job is asked as. Title and company first — they carry the role shape MMR sorts on."""
    return f"{job.title} — {job.company}\n{job.jd_text[:_MAX_QUERY_JD]}".strip()


def block(docs: list[Document]) -> str:
    """The precedents as prompt text. Empty list -> empty string, so the caller can just concatenate."""
    if not docs:
        return ""
    lines = [_HEADER, _PREAMBLE, ""]
    for i, d in enumerate(docs, 1):
        m = d.metadata
        traits = [t for t in (m.get("employment_type"), m.get("cadence"), m.get("rate")) if t]
        if m.get("is_agency"):
            traits.insert(0, "agency")
        head = (f"{i}. {m.get('title') or '(untitled)'} @ {m.get('company') or '(unknown)'} — "
                f"{m.get('verdict') or 'unknown'} {m.get('fit_score', 0)}/100 · "
                f"{m.get('tier') or 'unknown'}")
        if traits:
            head += " · " + " · ".join(traits)
        lines.append(head)
        why = (m.get("rationale") or "").strip()
        if why:
            lines.append(f"   why: {why[:_MAX_WHY]}")
    lines.append(_FOOTER)
    return "\n".join(lines)


def for_job(job: Job) -> str:
    """`find` + `block`, and it never raises. A broken memory scores the job as today, silently."""
    if not config.precedent_enabled():
        return ""
    try:
        return block(find(job))
    except Exception as e:  # noqa: BLE001 — see the module docstring: fails soft, always
        log.warning("precedent retrieval failed for %s @ %s: %s", job.title, job.company, e)
        return ""


def _is_precedent(doc: Document) -> bool:
    """Only a real Opus judgment counts. A prefilter kill and a failed call are not precedent.

    A prefiltered record carries an `analysis` too — verdict SKIP, `why` = the rule that fired — but
    it is a regex verdict. Offering it back as "how you judged this" teaches the scorer that it made
    a judgment it never made. The `why`-prefix check is the same test one layer down, and it is what
    covers documents indexed before `prefiltered` was carried in metadata.
    """
    m = doc.metadata
    if m.get("kind") != "job" or not m.get("scored") or m.get("prefiltered"):
        return False
    return not (m.get("rationale") or "").startswith(("prefilter:", "analysis_error:"))
