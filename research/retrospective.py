"""The first-party retrospective — the market report's half that needs no key and no network.

Four questions, answered in one pass over the user's own scored corpus, because the marginal cost of
the second, third and fourth is nearly zero once the records are in memory:

  * **Rate reality** — what share of postings state a rate at all, and the distribution of the ones
    that do. Measured over Ben's 1,144 records: **344 of 1,122 read job descriptions, 31%**. That
    number is the point of the section. It says the ground under a rate negotiation is two thirds
    air, and it is the kind of thing nobody derives by hand after a run.
  * **Gating stacks and keywords** — what the postings keep asking for, which is what feeds the
    bullet bank and answers *what should I learn*.
  * **Supply shape** — contract vs permanent, remote vs onsite, agency vs direct. This is where
    *the inbox is 71% permanent against a contract-first goal* comes from: a channel-supply
    mismatch, not a scoring bug, and invisible without the aggregate.
  * **Who's hiring** — top employers by volume, agencies separated from direct employers.

**Every free-text aggregate goes through `core/cluster.py`, never a plain `Counter`.** The scorer
writes its own prose every call, so one idea arrives under many spellings: counted flat, *permanent,
not contract* reports as 235 and ranks below nothing; clustered it is 672 and the largest finding in
the corpus. Company names fragment the same way (`NVIDIA` / `NVIDIA AI` / `NVIDIA Corporation`).
The exception is the three supply splits, and it is deliberate: `employment_type`, `cadence` and
`is_agency` are a closed vocabulary the `Analysis` schema names (`contract | contract-to-hire |
permanent | unknown`), the whole corpus uses five spellings of the first and five of the second, and
clustering a closed vocabulary would merge `contract` into `contract-to-hire` — the one distinction
the report exists to make.

**Company names cluster at 0.88, not the 0.82 the rest of the corpus uses.** A company name is a
proper noun, so the embedding measures string shape rather than meaning, and at 0.82 the real corpus
merges `OpenAI` with `OpenTrain AI`, `Twilio` with `Twill`, `Optum` with `Optym` and `Zoom` with
`ZoomInfo` — 23 multi-spelling clusters of which 6 are wrong. At 0.88 there are 11, every one of them
correct, and the merges worth having survive (`NVIDIA` at 0.9045, `NTT DATA` at 0.9298,
`Linda Werner & Associates, Inc` at 0.9899). A wrong merge here is not a broad heading, it is one
employer's hiring volume attributed to another.

**The seam is pure.** `build(records)` takes an iterable of corpus dicts and returns numbers; it
reads no file, makes no request and loads no model unless it has to build an embedder. Nothing here
renders anything — ticket 06 owns that — but every section carries its own `Sample`, so a renderer
cannot print a figure without having the sample size, the time window and the sentence saying this is
**one inbox, not the labour market** in its hand.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field as dc_field
from datetime import date
from pathlib import Path
from typing import Iterable

from core import rates
from core.cluster import Cluster, cluster_values
from core.index import iter_corpus_records
from core.models import composite_id, normalize_link

from .sources._baseline import percentiles

# What the retrospective is, in one clause, carried on every sample. User story 13: the corpus is the
# postings that reached one person's inbox through channels they chose, and generalising it to "the
# market" is the mistake that turns a channel-supply artefact into a market claim.
INBOX = "this user's inbox, not the labour market"

# See the module docstring — proper nouns need a tighter threshold than prose does.
COMPANY_SIMILARITY = 0.88

TOP_EMPLOYERS = 20
TOP_TERMS = 30

_RATE = re.compile(r"\$(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?/hr")
_RUN_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# --------------------------------------------------------------------------------------------------
# What a section carries with it
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    """The time span the records came from, and how many runs produced them.

    Both halves matter: six runs over fifteen days is a very different sample from six runs over six
    months, and the trend gate in ticket 07 reads exactly this.
    """
    runs: int
    first: str = ""
    last: str = ""
    days: int = 0

    def describe(self) -> str:
        if not self.first:
            return "window unknown"
        span = f"{self.first} → {self.last}" if self.last != self.first else self.first
        return f"{self.runs} run{'s' if self.runs != 1 else ''} · {span} ({self.days} days)"


@dataclass(frozen=True)
class Sample:
    """`n of total`, what `total` counts, and when — attached to the data rather than to a template.

    `RateBand` in `research/sources/_baseline.py` makes the same move for the external half and for
    the same reason: a caveat that lives in a render template is one a later template edit deletes.
    A section without a sample size is a number a reader has no way to weigh.
    """
    n: int
    total: int
    basis: str
    window: Window

    def describe(self) -> str:
        share = f" ({self.n / self.total:.0%})" if self.total and self.n != self.total else ""
        return f"n={self.n:,} of {self.total:,} {self.basis}{share} · {self.window.describe()} · {INBOX}"


# --------------------------------------------------------------------------------------------------
# The four questions
# --------------------------------------------------------------------------------------------------

@dataclass
class RateReality:
    """What share of a slice of the corpus states a rate, and the distribution of those that do.

    `stats` is hourly-equivalent throughout, because that is what `core/rates.py` returns — an annual
    figure is divided by 2,080 there, which asserts a 40-hour salaried year and is a claim the report
    should make out loud rather than silently.
    """
    scope: str                       # "all postings" | "contract" | "permanent"
    sample: Sample
    stats: dict[str, float | None]   # median / mean / p10 / p25 / p75 / p90
    unit: str = "hour"


@dataclass(frozen=True)
class Share:
    label: str
    n: int
    share: float


@dataclass
class Split:
    """One supply-shape cut over a closed-vocabulary field. Counted, not clustered — see the docstring."""
    question: str
    field: str
    sample: Sample
    shares: list[Share]


@dataclass
class TermSection:
    """A clustered free-text field, top-N by clustered total.

    `total_clusters` is here so the renderer can say *top 30 of 672* rather than presenting a
    truncation as the whole answer — a silent cap reads as full coverage.
    """
    question: str
    field: str
    sample: Sample
    clusters: list[Cluster]
    total_clusters: int


@dataclass
class Employer:
    name: str
    n: int
    is_agency: bool
    spellings: list[str] = dc_field(default_factory=list)


@dataclass
class EmployerSection:
    question: str
    sample: Sample
    employers: list[Employer]
    total_employers: int


@dataclass
class Retrospective:
    """Every number the first-party half of the report has. Pure data — no rendering, no I/O."""
    window: Window
    postings: int
    jd_read: int
    rates: list[RateReality] = dc_field(default_factory=list)
    terms: list[TermSection] = dc_field(default_factory=list)
    splits: list[Split] = dc_field(default_factory=list)
    employers: list[EmployerSection] = dc_field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# The pass
# --------------------------------------------------------------------------------------------------

def build(
    records: Iterable[dict],
    *,
    embedder=None,
    top_terms: int = TOP_TERMS,
    top_employers: int = TOP_EMPLOYERS,
    min_term_count: int = 1,
) -> Retrospective:
    """Corpus records -> the retrospective's numbers. Pure: no file, no request, no config.

    `embedder` is the `JobIndex`'s embedder where the caller has one, so a report run loads the
    model once rather than four times. Pass none and `core.cluster` builds its own — same weights,
    same cache, just not shared.
    """
    recs = _unique(records)
    window = _window(recs)
    read = [(r, jd) for r in recs if (jd := _jd(r))]

    def sample(n: int, total: int, basis: str) -> Sample:
        return Sample(n=n, total=total, basis=basis, window=window)

    return Retrospective(
        window=window,
        postings=len(recs),
        jd_read=len(read),
        rates=_rates(read, sample),
        terms=_terms(recs, sample, embedder, top_terms, min_term_count),
        splits=_splits(recs, sample),
        employers=_employers(recs, sample, embedder, top_employers),
    )


def from_corpus(corpus_dir: Path | str, **kwargs) -> Retrospective:
    """`build` over every `state-*.json` in a corpus directory. The report command's entry point."""
    return build(iter_corpus_records(Path(corpus_dir)), **kwargs)


# --- rate reality -----------------------------------------------------------------------------------

def _rates(read: list[tuple[dict, str]], sample) -> list[RateReality]:
    """The share stating a rate, over every read posting and then over the two employment types.

    The denominator is postings whose **job description was actually read**, never all postings: a
    title-only row states no rate because nobody fetched one, and folding those into "67% state no
    rate" would blame employers for a fetch failure. The overall figure comes first because it is the
    one that describes the negotiation, and the contract cut second because it is the one Ben is in.
    """
    out = []
    for scope, subset in (
        ("all postings", read),
        ("contract", [p for p in read if _field(p[0], "employment_type").startswith("contract")]),
        ("permanent", [p for p in read if _field(p[0], "employment_type") == "permanent"]),
    ):
        hourly = [h for h in (_hourly(rates.extract(jd)) for _, jd in subset) if h is not None]
        out.append(RateReality(
            scope=scope,
            sample=sample(len(hourly), len(subset), f"{scope} with a job description read"),
            stats=percentiles(hourly),
        ))
    return out


def _hourly(extracted: str | None) -> float | None:
    """`$85-90/hr` -> 87.5, `$72/hr` -> 72.0.

    The midpoint of a stated range, because a distribution needs one number per posting and the
    alternative — counting both ends — double-weights every posting that quotes a range against
    every posting that quotes a figure.
    """
    m = _RATE.fullmatch(extracted or "")
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    return (lo + hi) / 2


# --- gating stacks and keywords ---------------------------------------------------------------------

def _terms(recs: list[dict], sample, embedder, top: int, min_count: int) -> list[TermSection]:
    """The two free-text fields worth an aggregate, clustered.

    `resume_keywords` is the answer to *what should I learn* and is the bullet bank's source;
    `red_flags` is the answer to *what keeps disqualifying these*. Both are written fresh by the
    scorer on every call, which is exactly why neither may be counted flat.
    """
    out = []
    for field, question in (
        ("resume_keywords", "What the postings keep asking for"),
        ("red_flags", "What keeps disqualifying them"),
    ):
        clusters = cluster_values(
            _collect(recs, field), embedder=embedder, min_count=min_count)
        contributing = sum(1 for r in recs if _values(r, field))
        out.append(TermSection(
            question=question,
            field=field,
            sample=sample(contributing, len(recs), f"postings carrying a {field.replace('_', ' ')} list"),
            clusters=clusters[:top],
            total_clusters=len(clusters),
        ))
    return out


# --- supply shape -------------------------------------------------------------------------------------

def _splits(recs: list[dict], sample) -> list[Split]:
    """Contract vs perm, remote vs onsite, agency vs direct — counted over a closed vocabulary.

    `unknown` is a share like any other and is never dropped. It is the honest denominator: a cut
    that silently excludes the 172 postings whose employment type the scorer could not tell reports
    a cleaner market than the inbox actually contains.
    """
    out = []
    for field, question in (
        ("employment_type", "Contract vs permanent"),
        ("cadence", "Remote vs onsite"),
    ):
        counts = Counter(_field(r, field) or "unknown" for r in recs)
        out.append(Split(
            question=question, field=field,
            sample=sample(sum(counts.values()), len(recs), "postings"),
            shares=_shares(counts),
        ))

    agency = Counter("agency" if (r.get("analysis") or {}).get("is_agency") else "direct" for r in recs)
    out.append(Split(
        question="Agency vs direct", field="is_agency",
        sample=sample(sum(agency.values()), len(recs), "postings"),
        shares=_shares(agency),
    ))
    return out


def _shares(counts: Counter) -> list[Share]:
    total = sum(counts.values())
    return [Share(label, n, round(n / total, 4) if total else 0.0)
            for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


# --- who's hiring --------------------------------------------------------------------------------------

def _employers(recs: list[dict], sample, embedder, top: int) -> list[EmployerSection]:
    """Top employers by volume, clustered on the name and split agency from direct.

    An employer is called an agency when the scorer flagged **any** of its postings as one, not a
    majority: `is_agency` is a per-posting judgment on a per-employer fact, and a staffing firm that
    reads as direct on one vague listing is still a staffing firm.
    """
    named = [r for r in recs if _s(r.get("company"))]
    counts = Counter(_s(r.get("company")) for r in named)
    agency_spellings = {_s(r.get("company")) for r in named if (r.get("analysis") or {}).get("is_agency")}

    employers = []
    for cluster in cluster_values(counts, embedder=embedder, threshold=COMPANY_SIMILARITY):
        employers.append(Employer(
            name=cluster.label,
            n=cluster.count,
            is_agency=any(v in agency_spellings for v in cluster.values),
            spellings=cluster.values,
        ))

    out = []
    for question, is_agency in (("Who's hiring — direct", False), ("Who's hiring — agencies", True)):
        rows = [e for e in employers if e.is_agency is is_agency]
        n = sum(e.n for e in rows)
        out.append(EmployerSection(
            question=question,
            sample=sample(n, len(recs), "postings"),
            employers=rows[:top],
            total_employers=len(rows),
        ))
    return out


# --------------------------------------------------------------------------------------------------

def _unique(records: Iterable[dict]) -> list[dict]:
    """One row per posting, newest run wins.

    A job re-scored in a later run appears in both state files — 10 of Ben's 1,144 do — and counting
    it twice inflates whichever employer or rate it belongs to. The key is the same identity
    `core/models.py` gives the rest of the tool, so this cannot drift from what dedup considers one
    job.
    """
    seen: dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        key = normalize_link(_s(rec.get("link"))) or composite_id(_s(rec.get("company")), _s(rec.get("title")))
        seen[key] = rec
    return list(seen.values())


def _window(recs: list[dict]) -> Window:
    """The span of the runs the records came from, read off `_run` (`state-2026-07-20-094851`).

    Records with no `_run` — a hand-built fixture, or a caller passing raw jobs — contribute no date,
    and a set with no dates at all yields a window that *says* it is unknown rather than one that
    quietly claims today.
    """
    runs = {r["_run"] for r in recs if isinstance(r.get("_run"), str) and r["_run"]}
    dates = sorted({m.group(0) for m in (_RUN_DATE.match(run) for run in runs) if m})
    if not dates:
        return Window(runs=len(runs))
    first, last = dates[0], dates[-1]
    span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    return Window(runs=len(runs), first=first, last=last, days=span)


def _jd(rec: dict) -> str:
    """The posting's job description, or empty when nobody read one.

    Only a `full` fetch counts. An `email_snippet` is the two lines a job alert quoted and a
    `title_only` row is a title; treating either as a description would put "no rate stated" against
    postings whose text nobody has seen.

    Ticket 04's handover warned that `core/scrapers/posting.py` folds an `Attribution:` sentence
    into the JD text of every Himalayas, Remotive and Adzuna record, and that this pass must not read
    it as job content. It doesn't, and no stripping is needed for it: the only thing here that touches
    raw JD text is `core/rates.py`, which returns immediately on text with no `$`, and none of the
    three attribution lines contains one. The keyword and red-flag aggregates read the scorer's
    `analysis` lists, never the description. A market record carrying *only* a header is `title_only`
    by `posting()`'s own rule and is excluded above.
    """
    return _s(rec.get("fetched_jd")) if rec.get("jd_source") == "full" else ""


def _collect(recs: list[dict], field: str) -> Counter:
    counts: Counter = Counter()
    for rec in recs:
        counts.update(_values(rec, field))
    return counts


def _values(rec: dict, field: str) -> list[str]:
    raw = (rec.get("analysis") or {}).get(field)
    return [v.strip() for v in raw if isinstance(v, str) and v.strip()] if isinstance(raw, list) else []


def _field(rec: dict, name: str) -> str:
    return _s((rec.get("analysis") or {}).get(name)).lower()


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""
