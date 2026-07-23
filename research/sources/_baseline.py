"""A rate band, and the reason it is not a `Job`.

The nine sources beside this file answer *what is being advertised* and emit `core.models.Job`. CALC+
and BLS answer a different question — *what does this kind of work pay* — and hand back a distribution
over thousands of contracts or a whole occupational survey. Squeezing that into `fetch() -> list[Job]`
would mean inventing a fake posting per percentile, so the band sources get their own seam and their
own registry entry, exactly as ticket 01's handover predicted.

**The caveat is a field, not a footnote, and it is validated.** A federal ceiling rate is the maximum a
contractor may bill the government: it carries the vendor's overhead, G&A, fringe and fee, and it is an
upper bound rather than a wage. Printed as "what the job pays" it would inflate a rate expectation by a
factor a negotiation cannot survive — which is the single most damaging thing this whole module could
do. So `RateBand` refuses to exist without a caveat, a ceiling band refuses to exist unless its caveat
says the word, and `describe()` is the only way to get a figure out with prose attached. A renderer can
still reach in and print `median` bare; what it cannot do is claim nobody told it. `is_predicted` is
the same rule for the other way a figure lies — a model's estimate printed as an employer's offer.

Attribution is validated the same way and for a duller reason: it is a terms-of-use obligation on
third-party data, and an obligation that lives in a template is one a later template edit deletes.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateBand:
    """One occupation's pay distribution from one external source, with its own health warning.

    `unit` is `"hour"` or `"year"` and is never converted here. CALC+ is hourly and BLS publishes both;
    an annual figure divided by 2,080 quietly asserts a 40-hour salaried year, which is a claim about
    the job rather than about the data. The report can divide if it wants to say so out loud.
    """

    source: str          # "calc" | "bls"
    occupation: str      # what was asked for, in the source's own vocabulary
    scope: str           # "National", or an MSA name — the drivable-metro question
    unit: str            # "hour" | "year"
    n: int               # sample size; 0 means the source answered and had nothing
    period: str          # when the underlying data is from, in the source's words
    caveat: str          # mandatory — see the module docstring
    attribution: str     # mandatory — a terms-of-use obligation, not a courtesy
    is_ceiling: bool = False
    # A model's estimate rather than an employer's figure. Adzuna's salaries are the case: a live
    # 50-row US sample came back 100% `salary_is_predicted` with min == max, i.e. a point estimate
    # dressed as a range. Ticket 01 chose to withhold those at the source rather than label them,
    # because the label does not survive `core/rates.py` — this flag is the second line of that
    # defence, for any band that does reach a renderer.
    is_predicted: bool = False
    median: float | None = None
    mean: float | None = None
    p10: float | None = None
    p25: float | None = None
    p75: float | None = None
    p90: float | None = None
    query: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.caveat.strip():
            raise ValueError(f"{self.source}/{self.occupation}: a rate band may not ship without a caveat")
        if not self.attribution.strip():
            raise ValueError(f"{self.source}/{self.occupation}: a rate band may not ship without attribution")
        if self.is_ceiling and "ceiling" not in self.caveat.lower():
            raise ValueError(
                f"{self.source}/{self.occupation}: a ceiling band's caveat must say so — got {self.caveat!r}")
        if self.is_predicted and "predict" not in self.caveat.lower():
            raise ValueError(
                f"{self.source}/{self.occupation}: a predicted band's caveat must say so — "
                f"got {self.caveat!r}")

    def describe(self) -> str:
        """The figure and the warning in one string, so the two cannot be separated by a template."""
        return f"{self.headline()} — {self.caveat}"

    def headline(self) -> str:
        """`$135.54/hr median of 3,934`, or an honest blank.

        `n=0` means the source publishes a distribution without the sample behind it (BLS does), not
        that it found nothing — a band with no data has no median at all and says so instead.
        """
        if self.median is None:
            return f"{self.occupation} ({self.scope}): no data"
        unit = "/hr" if self.unit == "hour" else "/yr"
        of_n = f" of {self.n:,}" if self.n else ""
        return f"{self.occupation} ({self.scope}): ${self.median:,.2f}{unit} median{of_n}"


def percentiles(values: list[float]) -> dict[str, float | None]:
    """`{median, mean, p10, p25, p75, p90}` computed here rather than read off the source.

    CALC+'s own `histogram_percentiles` aggregation is Elasticsearch's t-digest approximation, and it
    is not stable: the same query a second apart returned medians of 135.54, 135.57, 135.61, 135.66 and
    135.71. A report whose whole purpose is month-over-month comparison cannot have its baseline wobble
    by a fifth of a point for no reason, so the rows are pulled and the quantiles taken exactly.
    """
    if not values:
        return {"median": None, "mean": None, "p10": None, "p25": None, "p75": None, "p90": None}
    ordered = sorted(values)
    out: dict[str, float | None] = {
        "median": round(statistics.median(ordered), 2),
        "mean": round(statistics.fmean(ordered), 2),
    }
    if len(ordered) >= 2:
        cuts = statistics.quantiles(ordered, n=100, method="inclusive")
        for name, pct in (("p10", 10), ("p25", 25), ("p75", 75), ("p90", 90)):
            out[name] = round(cuts[pct - 1], 2)
    else:
        out.update({"p10": None, "p25": None, "p75": None, "p90": None})
    return out
