"""Tests for the posted-rate extractor.  Run:  .venv/bin/python -m pytest core/ -q

Pure — no network, no key, no model. Every string below is either quoted verbatim from a
`data/corpus/state-*.json` job description or is the shape stage 5's sourcing research named, and
every expected value is what the extractor actually returns today rather than what it ought to.

**The failure direction is not symmetric, and it is the reason this file exists.** A rate this misses
costs one row of a distribution. A rate this *invents* — a funding round, an address, a reference
number read as pay — becomes an anchor in a rate negotiation, sourced to "a posting I saw". So the
false-positive cases below outnumber the true-positive ones, and the sanity window (`_ok`, $10–600/hr
hourly-equivalent) is the thing they hold in place: widen it and `"$300B+ under administration"` starts
paying somebody a salary.
"""
from __future__ import annotations

from .rates import extract

# --- a stated rate, in the spellings the corpus actually uses ---------------------------------------


def test_an_hourly_range_comes_back_hourly():
    """The straightforward case, and the one contract postings state most often."""
    assert extract("$85.00 – $90.00 per hour") == "$85-90/hr"


def test_an_annual_range_is_converted_to_the_same_hourly_unit():
    """Perm and contract have to land in one distribution or they cannot be compared at all.
    2080 hours: $120k/yr is $57.7/hr, $150k/yr is $72.1/hr."""
    assert extract("$120,000 - $150,000 per year") == "$58-72/hr"


def test_a_k_suffix_is_money_without_a_unit_word():
    assert extract("$150k") == "$72/hr"
    assert extract("Compensation Range: $195K - $275K") == "$94-132/hr"


def test_the_dollar_sign_on_the_second_number_is_optional():
    """Real postings write the range once and drop the sign: `$70 - 100/hr`. Requiring it would
    silently drop those rows, which reads as "this employer didn't state a rate"."""
    assert extract("$70 - 100/hr") == "$70-100/hr"


def test_en_dashes_slashes_and_stray_spaces_all_parse():
    """Three real corpus spellings of the same idea. Job boards are not careful typographers."""
    assert extract("Compensation $65-70/ hr") == "$65-70/hr"          # Korn Ferry, 2026-07
    assert extract("Compensation: $80–$110/hour") == "$80-110/hr"     # en dash, part-time W-2
    assert extract("The base salary range for this full-time position is $130,000 - $158,000"
                   ) == "$62-76/hr"


def test_the_rate_is_found_inside_a_full_job_description():
    """The point of the whole module: sources hand back blank or predicted `rate` fields, so the
    honest number is the one written in the prose."""
    jd = ("Genesis10 is seeking a Senior Full Stack Developer for a major financial institution. "
          "5+ month contract. Python, React, GCP. Pay: $65.00 - $70.00 per hour, W2 only.")
    assert extract(jd) == "$65-70/hr"


# --- money that is not pay, which is the expensive direction ----------------------------------------


def test_a_funding_round_is_not_a_salary():
    """`$35M` and `$300B` are the numbers a startup JD leads with. Both would clear any plausible
    magnitude check; only the sanity window stops them."""
    assert extract("We have raised over $35M from a16z, Google Ventures, Pear VC") is None
    assert extract("With $300B+ under administration and 700,000+ LPs on platform") is None


def test_a_bare_identifier_with_a_dollar_sign_is_not_pay():
    """Seven digits, no comma grouping, no unit — the lone-number last resort must decline it."""
    assert extract("Reference ID $1234567") is None


def test_a_rate_below_the_floor_is_declined_rather_than_reported():
    """$8/hr is not a US developer rate; it is a parse that went wrong. Reporting it would drag a
    median down with a number no employer wrote."""
    assert extract("$8/hr") is None


def test_a_posting_that_states_no_rate_returns_nothing():
    """68% of the corpus. `None` is the honest answer and the report counts it as such — the share of
    postings quoting nothing is itself one of the findings."""
    assert extract("Fully remote. Send your resume to jobs@example.com — no rate given.") is None
    assert extract("Equity: 0.1% - 0.5%. Unlimited PTO.") is None
    assert extract("") is None
    assert extract("Remote, contract, React + TypeScript. Rate DOE.") is None
