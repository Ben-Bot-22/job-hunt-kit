"""The market report: two halves in one document, and the sentence that keeps them apart.

The first half is a **retrospective over the user's own scored corpus** — no key, no network, no
terms of use, always available, highly relevant, and a small sample drawn through channels the user
chose. The second half is an **external baseline** from third parties — broad, generic, and subject
to somebody else's uptime and somebody else's terms. Conflating them is the trap this module exists
to avoid: a median drawn over one inbox is not a market rate, and a federal ceiling bill rate is not
a wage at all.

**The external half degrades to absent, never to silent.** A stranger with no network, or a run where
CALC+ has moved again, gets a report that *says* the external data is missing and names what is
missing. It never gets a shorter report it would read as complete. That is the difference between a
default feature and an "add a key to unlock" tier, and it is why `render` prints a labelled gap where
a normal renderer would print nothing.

**The honest limits are output, not documentation.** A confidently wrong rate range actively damages
the negotiation this report exists to support, so every one of them is rendered:

  * every section carries its sample size and its window, and the first-party ones say
    *this user's inbox, not the labour market* (`Sample.describe`);
  * a ceiling band prints the word CEILING against the figure **and** its full caveat under the
    group — `$135.82/hr` from CALC+ and `$65.38/hr` from BLS are the same occupation 2.08x apart,
    because one is a fully burdened upper bound and the other is a wage;
  * a predicted band prints PREDICTED against the figure. Adzuna's salaries are a model's point
    estimate (100% `salary_is_predicted` on a live 50-row sample), and ticket 01 chose to withhold
    them at the source rather than label them, because the label does not survive
    `core/rates.py`. This renderer is the second line of that defence: a band that arrives flagged
    predicted cannot be printed bare;
  * attribution is printed wherever third-party data appears, derived from the bands and the source
    counts actually rendered rather than from a list the caller passes in — an obligation a caller
    can forget is one that will be forgotten;
  * a clustered term prints its member spellings, because a cluster whose members are invisible is an
    unchallengeable number, and stage 2's clustering was paid for precisely to be inspectable.

**A third part renders whether or not there is a trend.** The month-over-month section is gated on
having enough comparable dated snapshots, and below the gate it prints the refusal and what it is
waiting for rather than disappearing — an absent section is indistinguishable from a report that
never had one. `research/snapshots.py` owns the gate and the reasoning; this module only prints it.

**Rendering is a pure function of the numbers** — no clock, no file, no request. `as_of` and the
snapshot history are passed in rather than read from `date.today()` and the disk, so the same numbers
render byte-identically forever; a report meant to be compared month over month cannot have its own
output move underneath the comparison. Ticket 08 owns the command that fills all three parts.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .retrospective import INBOX, RateReality, Retrospective, Split, TermSection
from .retrospective import EmployerSection, build as build_retrospective
from .snapshots import Snapshot, Trend, TrendRow, trend as assess_trend
from .sources import attribution_lines
from .sources._baseline import RateBand

# A cluster's spellings are the evidence for its count, so they are printed. All of them would be a
# hundred lines for the biggest red flag, so the list is cut — and the cut is *stated*, because a
# silent truncation reads as the whole answer.
MAX_SPELLINGS = 8

# What each baseline source is, in a heading, so nobody has to know what "calc" means.
_BASELINE_TITLES = {
    "calc": "GSA CALC+ — federal contract ceiling rates",
    "bls": "BLS OEWS — employee wages",
}


@dataclass(frozen=True)
class Baseline:
    """The external half's numbers, or as much of them as a run managed to get.

    Every field is allowed to be empty and an empty one renders as a named gap rather than as
    silence. `band_counts` and `supply_counts` are the per-source counts `fetch_baselines` and
    `fetch_all` hand back: they are what lets the report say *BLS returned nothing this run* instead
    of quietly printing one anchor where there should be two. A source that is absent from the dict
    was never asked; a source sitting at 0 was asked and had nothing.
    """
    bands: list[RateBand] = dc_field(default_factory=list)
    band_counts: dict[str, int] = dc_field(default_factory=dict)
    supply_counts: dict[str, int] = dc_field(default_factory=dict)
    notes: list[str] = dc_field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.bands and not any(self.supply_counts.values())


@dataclass(frozen=True)
class Report:
    """Everything the document is made of. `baseline is None` means the external half was not
    collected at all, which is a different statement from "collected and came back empty" — the first
    is a run that never reached the network, the second is a source that is down."""
    retrospective: Retrospective
    baseline: Baseline | None = None
    as_of: str = ""
    trend: Trend = dc_field(default_factory=lambda: assess_trend([]))


def build_report(records, baseline: Baseline | None = None, *, as_of: str = "",
                 snapshots: list[Snapshot] | None = None, **kwargs) -> Report:
    """Corpus records + whatever the external pull returned -> the report's numbers.

    The spec's seam, and it is deliberately thin: the first-party arithmetic lives in
    `retrospective.build` and the network lives outside this module entirely. `baseline=None` is the
    zero-key, zero-network default, and it produces a complete document.

    `snapshots` is the accumulated history `research/snapshots.py:load` reads off disk — passed in
    rather than read here, because this seam is pure. No snapshots is the ordinary first-run case and
    produces a trend section that *refuses out loud*, never one that is missing.
    """
    return Report(retrospective=build_retrospective(records, **kwargs), baseline=baseline,
                  as_of=as_of, trend=assess_trend(snapshots or []))


# --------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------

def render(report: Report) -> str:
    """The report's numbers -> markdown. Pure: no clock, no file, no request."""
    L: list[str] = []
    stamp = f" — {report.as_of}" if report.as_of else ""
    L.append(f"# Market report{stamp}")
    L.append("")
    L.append("Two halves, and they answer different questions. **Part 1** is a retrospective over "
             f"your own scored postings — {INBOX}. **Part 2** is an external baseline from "
             "third-party sources — broad, generic, and not about your channels at all. A figure "
             "from one half is never evidence for the other.")
    L += _retrospective(report.retrospective)
    L += _external(report.baseline)
    L += _trend(report.trend)
    return "\n".join(L).rstrip() + "\n"


# --- part 1: the user's own corpus ------------------------------------------------------------------

def _retrospective(r: Retrospective) -> list[str]:
    L = ["", "## Part 1 — Your own inbox (first-party)", ""]
    L.append(f"_Measured over {INBOX}. {r.postings:,} postings, {r.jd_read:,} with a job description "
             f"actually read · {r.window.describe()}._")

    for section in r.rates:
        L += _rate_reality(section)
    for section in r.terms:
        L += _terms(section)
    if r.splits:
        L += ["", "### Supply shape — does the inbox contain what you are looking for?"]
        for section in r.splits:
            L += _split(section)
    for section in r.employers:
        L += _employers(section)
    return L


def _rate_reality(s: RateReality) -> list[str]:
    """The share stating a rate, then the distribution of the ones that do.

    The share comes first on purpose: a median over 33 postings is a different object from a median
    over 1,000, and printing the figure before the coverage invites reading the first as the market.
    """
    share = f" ({s.sample.n / s.sample.total:.0%})" if s.sample.total else ""
    L = ["", f"### Rate reality — {s.scope}", ""]
    L.append(f"**{s.sample.n:,} of {s.sample.total:,}{share}** state a rate.")
    L.append(f"_Sample: {s.sample.describe()}._")
    if s.sample.n:
        L.append("")
        L.append(f"| median | mean | p10 | p25 | p75 | p90 |")
        L.append("|---|---|---|---|---|---|")
        L.append("| " + " | ".join(_money(s.stats.get(k), s.unit)
                                   for k in ("median", "mean", "p10", "p25", "p75", "p90")) + " |")
    else:
        # Not an omission and not a zero: nobody in this slice quoted a number. A blank table would
        # read as "$0" to a skimming eye, and a missing section as an oversight.
        L.append("")
        L.append("_No posting in this slice stated a rate, so there is no distribution to show._")
    return L


def _terms(s: TermSection) -> list[str]:
    L = ["", f"### {s.question} — {s.field.replace('_', ' ')}", ""]
    L.append(f"_Sample: {s.sample.describe()}. Showing the top {len(s.clusters)} of "
             f"{s.total_clusters:,} clustered ideas._")
    L.append("")
    if not s.clusters:
        L.append("_Nothing to cluster — no posting in this window carried one._")
        return L
    for c in s.clusters:
        L.append(f"- **{c.label}** — {c.count:,}{_spellings(c)}")
    return L


def _spellings(cluster) -> str:
    """The member spellings behind a cluster's count, which is what makes the count challengeable.

    Stage 2 paid for the clustering to be inspectable — every member carries its similarity to the
    label it was filed under — and throwing that away at the last step turns a broad cluster into a
    number nobody can argue with. Only multi-spelling clusters say anything; a cluster of one is its
    own evidence.
    """
    members = cluster.members[1:] if len(cluster.members) > 1 else []
    if not members:
        return ""
    shown = members[:MAX_SPELLINGS]
    parts = [f"{m.value} {m.count:,}" for m in shown]
    more = len(members) - len(shown)
    tail = f" +{more} more spelling{'s' if more != 1 else ''}" if more else ""
    return f"  \n  _also: {'; '.join(parts)}{tail}_"


def _split(s: Split) -> list[str]:
    shares = " · ".join(f"**{x.label}** {x.n:,} ({x.share:.0%})" for x in s.shares) or "_no postings_"
    return ["", f"- **{s.question}** — {shares}", f"  _Sample: {s.sample.describe()}._"]


def _employers(s: EmployerSection) -> list[str]:
    L = ["", f"### {s.question}", ""]
    L.append(f"_Sample: {s.sample.describe()}. Showing the top {len(s.employers)} of "
             f"{s.total_employers:,} employers._")
    L.append("")
    if not s.employers:
        L.append("_None in this window._")
        return L
    for e in s.employers:
        extra = f" _({', '.join(e.spellings[1:])})_" if len(e.spellings) > 1 else ""
        L.append(f"- **{e.name}** — {e.n:,}{extra}")
    return L


# --- part 2: third-party data, or a labelled gap ----------------------------------------------------

def _external(b: Baseline | None) -> list[str]:
    """The external half — and the whole reason this function never returns an empty list.

    A stranger with no network must read a report that *says* the external baseline is missing.
    Rendering nothing here would leave a shorter document that reads as complete, which is the exact
    silent degradation the spec forbids: the corpus-only half would be mistaken for a market report.
    """
    L = ["", "## Part 2 — External baseline (third-party)", ""]
    if b is None or b.is_empty():
        L += _external_gap(b)
        return L

    L.append("_Third-party market data. Broad and generic: it knows nothing about your channels, "
             "your stack or your seniority, and it is the anchor Part 1 is weighed against rather "
             "than a better version of it._")
    L += _bands(b)
    L += _supply(b)
    L += _attribution(b)
    return L


def _external_gap(b: Baseline | None) -> list[str]:
    """A named gap, listing what is missing and what it would have cost to have it."""
    L = ["**External market data is UNAVAILABLE for this run.** Everything above is your own inbox "
         "only, and nothing in this document is a labour-market figure."]
    L.append("")
    if b is None:
        L.append("_No external sources were collected. The rate baselines (GSA CALC+ contract "
                 "ceiling rates, BLS OEWS wages) need **no API key** — only a network connection — "
                 "so a run with a network gets them by default._")
    else:
        L.append("_Every external source was asked and none returned anything. Both rate baselines "
                 "are keyless, so this is a source being unreachable rather than a missing key._")
        L += _source_lines(b)
    for note in (b.notes if b else []):
        L.append(f"- {note}")
    L.append("")
    L.append("**Read Part 1 accordingly:** a median drawn over one inbox is an anchor for that inbox, "
             "not a market rate.")
    return L


def _bands(b: Baseline) -> list[str]:
    """One group per source, its caveat under the heading and the caveat's teeth on every figure.

    The group caveat alone is not enough: a reader skims to the number. So a ceiling band also carries
    the word CEILING on the row itself. Measured live on 2026-07-22, CALC+'s software-engineer median
    is $135.82/hr against BLS's $65.38/hr for the same work — 2.08x, all of it overhead, G&A, fringe
    and fee. That gap is what an unlabelled figure would put into a negotiation.
    """
    L: list[str] = []
    for source in _order(b.bands, b.band_counts):
        bands = [x for x in b.bands if x.source == source]
        L += ["", f"### {_BASELINE_TITLES.get(source, source)}", ""]
        if not bands:
            L.append(f"_`{source}` returned no data this run — this anchor is missing, not zero._")
            continue
        L.append(f"> {bands[0].caveat}")
        L.append("")
        for band in bands:
            L.append(f"- {band.headline()}{_band_flags(band)} · {band.period}"
                     f"{_percentiles(band)}")
    return L


def _band_flags(band: RateBand) -> str:
    """The caveat, compressed to the words that stop a misreading, attached to the figure itself."""
    flags = []
    if band.is_ceiling:
        flags.append("**CEILING — an upper bound on a bill rate, not a wage**")
    if band.is_predicted:
        flags.append("**PREDICTED — a model's estimate, not a posted figure**")
    return " — " + " · ".join(flags) if flags else ""


def _percentiles(band: RateBand) -> str:
    parts = [f"{name} {_money(getattr(band, name), band.unit)}"
             for name in ("p25", "p75", "p90") if getattr(band, name) is not None]
    return f" · {' · '.join(parts)}" if parts else ""


def _supply(b: Baseline) -> list[str]:
    """What the third-party job feeds returned, with the sentence that stops it being read as volume.

    None of these numbers is market volume and two of them are structurally incapable of being it:
    Adzuna is filtered to its *classified* ads (663 of 9,550 for `software engineer`) and Himalayas is
    capped at the newest 1,000 rows of a 95,456-job board. Printing a count without that is how a
    sampling knob becomes a market finding.
    """
    if not any(b.supply_counts.values()):
        return []
    L = ["", "### External supply — what each feed returned this run", ""]
    L.append("_These are **rows this run pulled**, not market volume: each feed is filtered, capped "
             "or both. A **keyless** source at zero is a broken source rather than an empty market; a "
             "**key-gated** one at zero is flagged below with the key it needs and where to get it._")
    L.append("")
    L += _source_lines(b, b.supply_counts)
    return L


def _source_lines(b: Baseline, counts: dict[str, int] | None = None) -> list[str]:
    """Per-source counts including the zeroes, because a zero is the only detector of a rotted
    scraper and a source omitted from the list is one nobody notices stopped working.

    A zero from a key-gated source with no key is not rot — it is unconfigured, so it renders as
    'skipped — set <VARS> in .env (…); see .env.example' rather than a bare 'nothing returned'. That
    is the warn-the-user path: the reader learns why it is empty and exactly how to fill it in."""
    from .sources import unconfigured_reason
    counts = b.band_counts if counts is None else counts
    lines = []
    for name, n in sorted(counts.items()):
        if n:
            lines.append(f"- `{name}` — {n:,}")
        elif (reason := unconfigured_reason(name)):
            lines.append(f"- `{name}` — {reason}")
        else:
            lines.append(f"- `{name}` — **nothing returned**")
    return lines


def _attribution(b: Baseline) -> list[str]:
    """Every attribution the rendered data incurred, derived from the data rather than passed in.

    A terms-of-use obligation that the caller has to remember is one that a later caller forgets, so
    this reads the bands actually rendered and the sources that actually returned rows. Nothing is
    credited that contributed nothing — crediting a source that returned zero reads as data the
    report does not have.
    """
    lines = []
    for band in b.bands:
        if band.attribution not in lines:
            lines.append(band.attribution)
    for line in attribution_lines(b.supply_counts):
        if line not in lines:
            lines.append(line)
    if not lines:
        return []
    return ["", "### Attribution", "",
            "_Required wherever this data appears — these are the terms under which it was used._",
            "", *[f"- {line}" for line in lines]]


# --- part 3: month over month, or the reason there isn't one ----------------------------------------

def _trend(t: Trend) -> list[str]:
    """The trend section, which renders whether or not there is a trend.

    Below the gate it prints the refusal and what the gate is waiting for. That is the whole point:
    an absent section teaches a reader nothing, and the thing being defended against is a 15-day,
    6-run line — or worse, one drawn across a rubric edit — being read as a market movement. See
    `research/snapshots.py` for why both thresholds are required and why the rubric boundary is hard.
    """
    L = ["", "## Part 3 — Month over month", ""]
    if not t.ok:
        L.append(f"**No trend is claimed.** {t.reason}")
        return L

    L.append(f"_Comparing {t.first} → {t.last}: {t.snapshots} snapshots over {t.days} days, all "
             "scored under the same rubric. Every figure below is first-party — "
             f"{INBOX} — so a movement here is a movement in your channels first._")
    if t.excluded:
        L.append("")
        L.append(f"_{t.excluded} earlier snapshot{'s are' if t.excluded != 1 else ' is'} excluded: "
                 "scored under a different rubric, and not comparable with these._")
    L += ["", "| metric | " + t.first + " | " + t.last + " | change |", "|---|---|---|---|"]
    for row in t.rows:
        L.append(f"| {row.label} | {_value(row.first, row.kind)} | {_value(row.last, row.kind)} "
                 f"| {_delta(row)} |")
    return L


def _value(value: float, kind: str) -> str:
    if kind == "share":
        return f"{value:.0%}"
    if kind == "hourly":
        return f"${value:,.2f}/hr"
    return f"{value:,.0f}"


def _delta(row: TrendRow) -> str:
    """The change, signed, in the units of the row — and points rather than percent for a share.

    A share moving from 60% to 71% is 11 *points*; calling it +18% would be true of a different
    quantity and is the arithmetic mistake that makes a modest movement read as a large one.
    """
    if row.kind == "share":
        points = (row.last - row.first) * 100
        return f"{points:+.0f} pts"
    if row.kind == "hourly":
        return f"{row.change:+,.2f}"
    return f"{row.change:+,.0f}"


# --------------------------------------------------------------------------------------------------

def _order(bands: list[RateBand], counts: dict[str, int]) -> list[str]:
    """Every source that was asked, in a stable order — the ones that answered and the ones that did
    not. Ordering by the counts dict first means a source that returned nothing still gets a heading
    saying so."""
    order = list(counts) or []
    for band in bands:
        if band.source not in order:
            order.append(band.source)
    return order


def _money(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}/hr" if unit == "hour" else f"${value:,.0f}/yr"
