"""Dated snapshots of the report's numbers, and the refusal to draw a trend across them yet.

Two jobs, and the second is the point of the first.

**Accumulate.** Every run writes `data/reports/market-numbers-<date>.json` — one file per date, side
by side, so a year of running this tool leaves a year of comparable numbers rather than one file that
has been overwritten fifty times. Nothing here recomputes history: the retrospective costs ~11 s over
1,143 records, almost all of it clustering, and re-deriving last month from a corpus that has since
been pruned would not even be possible.

**Refuse.** A month-over-month trend is the cheapest section in this report to compute and the
easiest one to get wrong, so it is gated and it says so until the gate opens:

  * **Not enough snapshots, and not enough time.** The corpus as it stands spans 15 days over 6 runs.
    Two points 15 days apart is not a trend, it is a pair of numbers with a line drawn between them.
    `MIN_SNAPSHOTS` and `MIN_DAYS` are both required, because either alone is gameable — three
    snapshots in one week, or two snapshots six months apart, are each a trend claim resting on one
    observation.
  * **Never across a rubric boundary.** The numbers in a snapshot are aggregates over a *scored*
    corpus, and the scorer is a prompt. The 598-job corpus behind `profile/notes/market-insights.md`
    was scored by the frozen pipeline's own scorer, deleted in stage 5 · 01 — a different rubric with
    a different schema — and both it and today's analyzer emit `STRONG_FIT`, so the two join
    without complaint and the resulting
    line measures a prompt edit while reading as a market movement. That is the failure this gate
    exists for, and it is not hypothetical: the rubric is the file in this repo edited most.

So each snapshot records the fingerprint of the rubric that was live when it was written, and only
snapshots sharing the newest fingerprint are ever compared. A rubric edit restarts the count, out
loud — the refusal names how many snapshots were set aside and why. That is deliberately strict: a
trend that quietly survives a rubric change is worse than no trend, because it will be believed.

The fingerprint is *whitespace-insensitive*, so reflowing a paragraph does not cost a trend, and it
describes the rubric **at report time** rather than at scoring time — a rubric edited mid-window
means the next snapshot is the first one wholly under the new one. Nothing can reconstruct which
prompt scored which row after the fact; recording the honest approximation and saying which it is
beats recording nothing.

Everything except `write`/`load` is pure. The two that touch disk take their directory as a
parameter, so the whole module is assertable offline against a `tmp_path`.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from pathlib import Path

from .retrospective import Retrospective

REPO_ROOT = Path(__file__).resolve().parent.parent

# `data/reports/` is where the numbers file lives (`triage/config.py` already names it, and `research`
# may not import a sibling leaf). The prefix is what makes `load` ignore everything else in there.
REPORTS_DIR = REPO_ROOT / "data" / "reports"
PREFIX = "market-numbers-"

# The gate. Both are required: three snapshots inside one week is a trend claim resting on one week,
# and two snapshots six months apart is a trend claim resting on two observations.
MIN_SNAPSHOTS = 3
MIN_DAYS = 60

# On-disk shape. A file written by a newer version is skipped rather than half-read — a snapshot
# whose fields have moved would silently contribute wrong numbers to the one section that is supposed
# to be more careful than the rest.
VERSION = 1

# The metrics the trend section draws, in the order it draws them. A key missing from either endpoint
# is skipped rather than treated as zero: a metric that did not exist last quarter has not fallen.
TREND_METRICS: tuple[tuple[str, str, str], ...] = (
    ("postings", "Postings scored", "count"),
    ("jd_read", "Job descriptions read", "count"),
    ("rate_share_all_postings", "Share stating a rate", "share"),
    ("rate_median_all_postings", "Median stated rate", "hourly"),
    ("rate_share_contract", "Share stating a rate — contract", "share"),
    ("rate_median_contract", "Median stated rate — contract", "hourly"),
    ("rate_median_permanent", "Median stated rate — permanent", "hourly"),
    ("share_employment_type_contract", "Contract share of the inbox", "share"),
    ("share_employment_type_permanent", "Permanent share of the inbox", "share"),
    ("share_cadence_remote", "Remote share of the inbox", "share"),
    ("share_is_agency_agency", "Agency share of the inbox", "share"),
)

TOP_TERMS = 20

_SLUG = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")


# --------------------------------------------------------------------------------------------------
# What a snapshot is
# --------------------------------------------------------------------------------------------------

def fingerprint(rubric_text: str) -> str:
    """A rubric's identity, for the purpose of deciding whether two months are comparable.

    Whitespace-insensitive on purpose: rewrapping a paragraph changes no scoring behaviour, and a
    fingerprint that reset the trend on a reflow would train whoever maintains the rubric to leave it
    alone — which is the opposite of what that file is for. Any change to the words resets it.

    Empty text has no fingerprint at all, and `trend` treats "unknown" as incomparable with
    everything including another unknown. A snapshot that cannot say what scored it is exactly the
    kind of row this gate exists to keep out of a line.
    """
    text = _WS.sub(" ", rubric_text or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


@dataclass(frozen=True)
class Snapshot:
    """One run's numbers, dated, and stamped with the rubric that produced them.

    `metrics` is a flat `name -> number` map rather than the section objects it was derived from,
    because this file has to stay readable by a version of the report that has not been written yet.
    A snapshot from six months ago should still yield the metrics it happens to share with today's,
    and lose only the ones that were renamed — which is what `TREND_METRICS`' skip-if-absent rule
    gives, and what a pickled object graph would not.

    `terms` is recorded and not yet trended. "What the postings started asking for this month" is the
    trend worth having, and it needs the same snapshot history everything else here needs; recording
    it now costs ~2 KB a month and is the difference between having that section in the autumn and
    starting the clock then.
    """
    as_of: str                                          # the date the report was run, ISO
    rubric: str                                         # `fingerprint` of profile/rubric.md, or ""
    postings: int = 0
    jd_read: int = 0
    runs: int = 0
    first_run: str = ""
    last_run: str = ""
    window_days: int = 0
    metrics: dict[str, float] = dc_field(default_factory=dict)
    terms: dict[str, dict[str, int]] = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": VERSION, "as_of": self.as_of, "rubric": self.rubric,
            "postings": self.postings, "jd_read": self.jd_read, "runs": self.runs,
            "first_run": self.first_run, "last_run": self.last_run,
            "window_days": self.window_days, "metrics": self.metrics, "terms": self.terms,
        }


def snapshot(r: Retrospective, *, as_of: str, rubric: str) -> Snapshot:
    """A retrospective -> the dated row that goes on disk.

    `rubric` is a fingerprint, not the rubric text — the numbers file accumulates in a directory a
    user may well share when asking for help, and their scoring prompt is theirs.
    """
    return Snapshot(
        as_of=as_of, rubric=rubric,
        postings=r.postings, jd_read=r.jd_read,
        runs=r.window.runs, first_run=r.window.first, last_run=r.window.last,
        window_days=r.window.days,
        metrics=_metrics(r), terms=_terms(r),
    )


def _metrics(r: Retrospective) -> dict[str, float]:
    """Every headline number, flattened to comparable keys.

    Generic over the sections rather than a hand-listed set, so a scope or a split label added later
    starts accumulating immediately and only needs a line in `TREND_METRICS` to become visible. The
    share is stored alongside the count for the splits because the count moves with inbox volume and
    the share is the thing "71% permanent" is a claim about.
    """
    m: dict[str, float] = {"postings": float(r.postings), "jd_read": float(r.jd_read)}
    for section in r.rates:
        key = _slug(section.scope)
        m[f"rate_n_{key}"] = float(section.sample.n)
        m[f"rate_total_{key}"] = float(section.sample.total)
        if section.sample.total:
            m[f"rate_share_{key}"] = round(section.sample.n / section.sample.total, 4)
        for stat, value in section.stats.items():
            if value is not None:
                m[f"rate_{stat}_{key}"] = round(float(value), 2)
    for split in r.splits:
        for share in split.shares:
            m[f"share_{split.field}_{_slug(share.label)}"] = share.share
            m[f"count_{split.field}_{_slug(share.label)}"] = float(share.n)
    for section in r.employers:
        m[f"employers_{_slug(section.question)}"] = float(section.total_employers)
    return m


def _terms(r: Retrospective) -> dict[str, dict[str, int]]:
    """The top clustered ideas per free-text field, by their clustered totals — never a flat count.

    Storing the cluster *label* means a later comparison is between ideas rather than between
    spellings, which is the whole reason stage 2's clustering is upstream of this file.
    """
    return {s.field: {c.label: c.count for c in s.clusters[:TOP_TERMS]} for s in r.terms}


# --------------------------------------------------------------------------------------------------
# Disk — one file per date, never one file overwritten
# --------------------------------------------------------------------------------------------------

def write(snap: Snapshot, directory: Path | str = REPORTS_DIR) -> Path:
    """Write one dated snapshot beside its predecessors and return the path.

    The date is in the filename, so a run in August cannot touch July's numbers — that is what
    "accumulates rather than overwrites" means here. Re-running the report on the same day does
    rewrite that day's file, which is right: it is the same day's numbers, computed again.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{PREFIX}{snap.as_of}.json"
    path.write_text(json.dumps(snap.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(directory: Path | str = REPORTS_DIR) -> list[Snapshot]:
    """Every readable snapshot in a directory, oldest first.

    A file that is truncated, hand-edited into invalid JSON, or written by a future version is
    **skipped, not raised**. A corrupt row in the history is not a reason to fail the whole report,
    and the trend section's own gate is what stops the remaining rows being over-read: fewer readable
    snapshots means the gate is more likely to refuse, which is the safe direction.
    """
    out = []
    for path in sorted(Path(directory).glob(f"{PREFIX}*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — unreadable is a skipped row, never a failed report
            continue
        if not isinstance(data, dict) or data.get("version") != VERSION:
            continue
        if not isinstance(data.get("as_of"), str) or not data["as_of"]:
            continue
        out.append(Snapshot(
            as_of=data["as_of"], rubric=str(data.get("rubric") or ""),
            postings=int(data.get("postings") or 0), jd_read=int(data.get("jd_read") or 0),
            runs=int(data.get("runs") or 0), first_run=str(data.get("first_run") or ""),
            last_run=str(data.get("last_run") or ""), window_days=int(data.get("window_days") or 0),
            metrics={k: float(v) for k, v in (data.get("metrics") or {}).items()
                     if isinstance(v, (int, float))},
            terms={k: dict(v) for k, v in (data.get("terms") or {}).items() if isinstance(v, dict)},
        ))
    return sorted(out, key=lambda s: s.as_of)


# --------------------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TrendRow:
    label: str
    kind: str            # count | share | hourly — how the renderer formats it
    first: float
    last: float

    @property
    def change(self) -> float:
        return self.last - self.first


@dataclass(frozen=True)
class Trend:
    """Either a month-over-month comparison, or the reason there isn't one — never neither.

    `ok is False` always carries a `reason` written to be printed. The section is rendered in both
    cases: a gate that hid itself would be indistinguishable from a report that has no trend section,
    and a reader would not learn that a trend is coming or what it is waiting for.
    """
    ok: bool
    reason: str = ""
    snapshots: int = 0            # comparable snapshots (same rubric as the newest known one)
    days: int = 0                 # elapsed days they span, inclusive
    first: str = ""
    last: str = ""
    excluded: int = 0             # snapshots set aside at a rubric boundary
    rubrics: int = 0              # distinct known rubrics across the whole history
    rows: list[TrendRow] = dc_field(default_factory=list)


def trend(snaps: list[Snapshot]) -> Trend:
    """Snapshots -> a trend, or a refusal that says exactly what is missing.

    The comparable set is the snapshots sharing the **newest known rubric**, and it is never widened
    to make the gate open. Snapshots under an older rubric are set aside and counted, so a user who
    edited their rubric last week reads "3 snapshots set aside" rather than watching their trend
    silently restart.
    """
    snaps = sorted([s for s in snaps if s.as_of], key=lambda s: s.as_of)
    known = [s for s in snaps if s.rubric]
    rubrics = len({s.rubric for s in known})

    if not known:
        missing = (f" ({len(snaps)} snapshot{'s' if len(snaps) != 1 else ''} carry no rubric "
                   f"fingerprint and cannot be compared)" if snaps else "")
        return Trend(ok=False, excluded=len(snaps),
                     reason=f"No comparable dated snapshots yet{missing}. "
                            f"{_requirement()} Each report run writes one.")

    current = known[-1].rubric
    comparable = [s for s in known if s.rubric == current]
    excluded = len(snaps) - len(comparable)
    days = _span(comparable)
    base = dict(snapshots=len(comparable), days=days, excluded=excluded, rubrics=rubrics,
                first=comparable[0].as_of, last=comparable[-1].as_of)

    if len(comparable) < MIN_SNAPSHOTS or days < MIN_DAYS:
        return Trend(ok=False, reason=_short(comparable, days, excluded, rubrics), **base)
    return Trend(ok=True, rows=_rows(comparable[0], comparable[-1]), **base)


def _short(comparable: list[Snapshot], days: int, excluded: int, rubrics: int) -> str:
    n = len(comparable)
    have = (f"{n} comparable snapshot{'s' if n != 1 else ''} spanning {days} day"
            f"{'s' if days != 1 else ''} ({comparable[0].as_of} → {comparable[-1].as_of})")
    reason = f"Not enough history for a month-over-month claim: {have}. {_requirement()}"
    if excluded:
        reason += (f" A further {excluded} snapshot{'s were' if excluded != 1 else ' was'} set aside: "
                   f"{'they were' if excluded != 1 else 'it was'} scored under a different rubric "
                   f"({rubrics} rubrics in this history), and a line drawn across a rubric change "
                   "measures the change to your scoring prompt while reading as a change in the "
                   "market.")
    return reason


def _requirement() -> str:
    return (f"A trend renders once there are at least {MIN_SNAPSHOTS} snapshots, scored under the "
            f"same rubric, spanning at least {MIN_DAYS} days.")


def _rows(first: Snapshot, last: Snapshot) -> list[TrendRow]:
    """The curated metrics present in **both** endpoints. A metric absent from one is skipped, not
    zeroed — a section that did not exist last quarter has not fallen to zero this one."""
    return [TrendRow(label=label, kind=kind, first=first.metrics[key], last=last.metrics[key])
            for key, label, kind in TREND_METRICS
            if key in first.metrics and key in last.metrics]


def _span(snaps: list[Snapshot]) -> int:
    """Inclusive elapsed days, or 0 if a date does not parse — an unreadable date must not be able to
    manufacture a long window and open the gate."""
    try:
        return (date.fromisoformat(snaps[-1].as_of) - date.fromisoformat(snaps[0].as_of)).days + 1
    except ValueError:
        return 0


def _slug(value: str) -> str:
    return _SLUG.sub("_", value.strip().lower()).strip("_")
