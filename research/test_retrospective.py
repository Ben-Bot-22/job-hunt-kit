"""Tests for the first-party retrospective.  Run:  .venv/bin/python -m pytest research/ -q

Offline, no key, no network, no config — which is the property the whole first-party half exists to
have, so a test that needed any of them would be testing the wrong thing.

Split the way `core/test_cluster.py` is split, for the same reason. **The wiring half** uses a
deterministic bag-of-words embedder and covers the arithmetic: what the denominator of "states a
rate" is, that `unknown` is never dropped from a split, that a re-scored posting is counted once,
that every section carries its sample. **The judgment half** loads the real `bge-small` and skips
when the weights aren't cached, because "eight spellings of one red flag are one finding" and
"`OpenAI` and `OpenTrain AI` are two employers" are claims about a real embedding space, and a stub
written to agree with them proves only that the stub was written to agree.

Every string and every expected count below is verbatim from `data/corpus/state-*.json`, and the
aggregate figures are what the shipped code returns over that corpus today.
"""
from __future__ import annotations

import pytest

from core.index import DEFAULT_MODEL, model_is_cached
from core.test_retrieval import FakeEmbedder

from .retrospective import INBOX, build

# The eight commonest real spellings of the corpus's biggest finding, with their real counts. Counted
# flat this is a 235 that ranks below `linkedin`; counted as one idea it is 489 and is the headline.
PERMANENT = {
    "Permanent role, not contract": 235,
    "Permanent, not contract": 110,
    "Permanent full-time, not contract": 48,
    "Permanent role, not contract — ranks below equivalent contract": 41,
    "Likely permanent, not contract": 20,
    "Permanent role, not contract/CTH": 17,
    "Permanent role, not contract (ranks below equivalent contract)": 10,
    "Full-time permanent, not contract": 8,
}

# Real corpus spellings of two stacks, with their real counts. `Next.js` is the control: it is a
# React framework and reads adjacent, and it must stay its own finding.
NODE = {"Node.js": 218, "Node": 78, "NodeJS": 12}
REACT = {"React": 407, "React.js": 12, "ReactJS": 8}
NEXT = {"Next.js": 88}

# Real posted rate strings from corpus job descriptions, and what `core/rates.py` makes of them.
# $85-90/hr -> 87.5, $120,000-$150,000/yr -> (57.7+72.1)/2 = 64.9, $150k -> 72.1.
RATE_STRINGS = ["$85.00 – $90.00 per hour", "$120,000 - $150,000 per year", "$150k"]


def _rec(n: int = 0, *, jd: str = "a job description", jd_source: str = "full",
         run: str = "2026-07-20-094851", company: str = "", **analysis) -> dict:
    """One corpus-shaped record. Defaults are the common case: a fetched JD, scored, one run."""
    return {
        "link": f"https://example.test/jobs/{n}",
        "company": company or f"Company {n}",
        "title": "Senior Full Stack Developer",
        "source_platform": "linkedin",
        "fetched_jd": jd,
        "jd_source": jd_source,
        "_run": run,
        "analysis": {"employment_type": "contract", "cadence": "remote", "is_agency": False,
                     "red_flags": [], "resume_keywords": [], **analysis},
    }


def _many(counts: dict[str, int], field: str) -> list[dict]:
    """One record per *posting*. A red flag seen 235 times is 235 postings, and building it as one
    record repeated would silently collapse to one under the identity dedup."""
    recs: list[dict] = []
    for value, n in counts.items():
        recs += [_rec(len(recs) + i, **{field: [value]}) for i in range(n)]
    return recs


def _build(records, **kwargs):
    return build(records, embedder=FakeEmbedder(), **kwargs)


def _sections(r) -> list:
    """Every section, so a test can assert something of all of them at once."""
    return [*r.rates, *r.terms, *r.splits, *r.employers]


# --- rate reality --------------------------------------------------------------------------------

def test_the_share_stating_a_rate_is_measured_against_descriptions_actually_read():
    """The denominator is the load-bearing part. A title-only row states no rate because nobody
    fetched one; counting it as an employer who declined to post a rate turns a fetch failure into a
    market finding."""
    recs = [_rec(0, jd="Pay: $85.00 – $90.00 per hour"),
            _rec(1, jd="No pay information here"),
            _rec(2, jd="", jd_source="title_only"),
            _rec(3, jd="Senior Engineer", jd_source="email_snippet")]

    overall = _build(recs).rates[0]
    assert (overall.sample.n, overall.sample.total) == (1, 2)


def test_the_distribution_is_hourly_equivalent_over_the_midpoint_of_each_range():
    """A range contributes one number, not two: counting both ends double-weights every posting that
    quotes a band against every posting that quotes a figure."""
    stats = _build([_rec(i, jd=s) for i, s in enumerate(RATE_STRINGS)]).rates[0].stats
    assert stats["median"] == 72.0                      # $150k -> $72/hr, the middle of the three
    assert (stats["mean"], stats["p10"]) == (74.83, 66.4)


def test_contract_and_permanent_get_their_own_rate_distributions():
    """Ben is negotiating a contract rate, and a median drawn over an inbox that is 71% permanent is
    not one. Both are reported; neither is presented as the other."""
    recs = [_rec(0, jd="$100/hr", employment_type="contract"),
            _rec(1, jd="$50/hr", employment_type="contract"),
            _rec(2, jd="$200,000 per year", employment_type="permanent")]

    by_scope = {r.scope: r for r in _build(recs).rates}
    assert by_scope["contract"].stats["median"] == 75.0
    assert by_scope["permanent"].stats["median"] == 96.0     # $200k/yr over 2,080 hours
    assert by_scope["contract"].sample.total == 2


def test_a_posting_with_no_rate_anywhere_contributes_nothing_rather_than_a_zero():
    """A zero in the distribution would drag every percentile down and read as an employer offering
    nothing, which is the direction that damages a negotiation."""
    overall = _build([_rec(0, jd="Great culture, free snacks."), _rec(1, jd="$90/hr")]).rates[0]
    assert overall.sample.n == 1 and overall.stats["median"] == 90.0


# --- supply shape --------------------------------------------------------------------------------

def test_the_contract_versus_permanent_split_keeps_unknown_as_a_share():
    """Dropping `unknown` reports a cleaner inbox than the one that exists — 173 of Ben's 1,143
    postings are postings the scorer could not classify, and hiding them inflates both real shares."""
    recs = ([_rec(i, employment_type="permanent") for i in range(7)]
            + [_rec(7, employment_type="contract"), _rec(8, employment_type="unknown"),
               _rec(9, employment_type="")])

    split = next(s for s in _build(recs).splits if s.field == "employment_type")
    assert [(s.label, s.n) for s in split.shares] == [
        ("permanent", 7), ("unknown", 2), ("contract", 1)]
    assert split.sample.n == 10


def test_the_supply_splits_are_counted_not_clustered():
    """`employment_type` is a closed vocabulary the `Analysis` schema names, and clustering it would
    merge `contract` into `contract-to-hire` — the single distinction the report exists to make."""
    recs = [_rec(0, employment_type="contract"), _rec(1, employment_type="contract-to-hire")]
    split = next(s for s in _build(recs).splits if s.field == "employment_type")
    assert sorted(s.label for s in split.shares) == ["contract", "contract-to-hire"]


def test_agency_versus_direct_is_a_split_of_every_posting():
    recs = [_rec(0, is_agency=True), _rec(1, is_agency=True), _rec(2, is_agency=False)]
    split = next(s for s in _build(recs).splits if s.field == "is_agency")
    assert [(s.label, s.n, s.share) for s in split.shares] == [("agency", 2, 0.6667), ("direct", 1, 0.3333)]


# --- who's hiring --------------------------------------------------------------------------------

def test_an_employer_flagged_as_an_agency_on_any_posting_is_an_agency():
    """`is_agency` is a per-posting judgment about a per-employer fact. A staffing firm that reads as
    direct on one vague listing is still a staffing firm, and splitting its volume across both tables
    would understate it twice."""
    recs = [_rec(0, company="Apex Systems", is_agency=True),
            _rec(1, company="Apex Systems", is_agency=False)]

    agencies = next(e for e in _build(recs).employers if "agencies" in e.question)
    assert [(x.name, x.n) for x in agencies.employers] == [("Apex Systems", 2)]


def test_the_employer_tables_report_how_many_were_left_out():
    """A top-N with no total reads as the whole answer. `total_employers` is what lets the renderer
    say *top 2 of 3* instead of silently truncating."""
    recs = [_rec(i, company=c) for i, c in enumerate(["Alpha", "Beta", "Gamma"])]
    direct = next(e for e in _build(recs, top_employers=2).employers if "direct" in e.question)
    assert len(direct.employers) == 2 and direct.total_employers == 3


# --- samples, windows and identity ---------------------------------------------------------------

def test_every_section_carries_its_sample_size_and_time_window():
    """An acceptance criterion, asserted over every section at once so a section added later cannot
    ship without one."""
    r = _build([_rec(0, jd="$90/hr", red_flags=["No rate posted"], resume_keywords=["Python"]),
                _rec(1, jd="$200,000 per year", run="2026-07-06", employment_type="permanent",
                     is_agency=True)])

    assert r.window.runs == 2 and r.window.days == 15
    for section in _sections(r):
        described = section.sample.describe()
        assert section.sample.total > 0
        assert "2026-07-06 → 2026-07-20 (15 days)" in described
        assert INBOX in described


def test_a_window_with_no_dated_runs_says_so_rather_than_claiming_today():
    """A caller passing raw jobs rather than corpus records gets an honest blank. Inventing today's
    date here would stamp a five-month-old export as this morning's market."""
    r = _build([{"link": "https://example.test/1", "company": "Alpha", "analysis": {}}])
    assert r.window.describe() == "window unknown"


def test_a_posting_rescored_in_a_later_run_is_counted_once():
    """Ben's corpus holds one such pair. Counted twice it inflates that employer's volume and puts
    its rate into the distribution twice."""
    recs = [_rec(0, run="2026-07-13-102938"), _rec(0, run="2026-07-20-094851")]
    assert _build(recs).postings == 1


def test_two_postings_with_no_link_at_all_stay_two_postings():
    """Ten corpus records have an empty link. Collapsing them onto one blank key would delete nine
    real jobs from every count in the report."""
    recs = [{"link": "", "company": "Alpha", "title": "Engineer", "analysis": {}},
            {"link": "", "company": "Beta", "title": "Engineer", "analysis": {}}]
    assert _build(recs).postings == 2


def test_output_is_a_pure_function_of_the_input_records():
    """No file, no clock, no config, no order dependence. The report is meant to be compared month
    over month, so a second run over the same records that differed at all would make every
    comparison meaningless."""
    recs = [_rec(0, jd="$90/hr", company="Alpha", red_flags=["No rate posted"]),
            _rec(1, jd="$120/hr", company="Beta", is_agency=True, resume_keywords=["Python"]),
            _rec(2, company="Alpha", employment_type="permanent")]

    assert _build(recs) == _build(recs)
    assert _build(recs) == _build(list(reversed(recs)))


# --- the judgment: does it actually group ideas --------------------------------------------------

needs_model = pytest.mark.skipif(
    not model_is_cached(), reason=f"{DEFAULT_MODEL} weights are not cached")


@needs_model
def test_the_eight_real_spellings_of_one_red_flag_aggregate_as_one_idea():
    """The most load-bearing test in the stage: it is the difference between a report and a
    misleading report. Eight real spellings, real counts, one posting each — a `Counter` reports the
    top one at 235 and ranks it below `No rate posted`; clustered it is 489 and is the headline
    finding of the whole corpus."""
    flags = next(t for t in build(_many(PERMANENT, "red_flags")).terms if t.field == "red_flags")
    top = flags.clusters[0]
    assert top.label == "Permanent role, not contract"
    assert top.count == sum(PERMANENT.values()) == 489
    assert max(m.count for m in top.members) == 235      # what a flat count would have printed


@needs_model
def test_three_genuinely_different_red_flags_stay_three_findings():
    """The other direction, and it would be just as misleading: a rate complaint, an on-call
    complaint and a stack mismatch merged into one bucket nobody can act on."""
    recs = [_rec(i, red_flags=[f]) for i, f in enumerate(
        ["No rate posted", "On-call rotations required", "Angular front-end, not React"])]

    flags = next(t for t in build(recs).terms if t.field == "red_flags")
    assert len(flags.clusters) == 3


@needs_model
def test_one_employers_spellings_are_one_employer_and_two_employers_are_not():
    """Company names cluster at 0.88 rather than the corpus-wide 0.82, and this is the measurement
    that fixes it there. At 0.82 the real corpus merges `OpenAI` with `OpenTrain AI` (0.8404),
    `Twilio` with `Twill` and `Optum` with `Optym` — six wrong merges out of 23. A wrong merge here
    is not a broad heading, it is one employer's hiring volume credited to another."""
    recs = [_rec(i, company=c) for i, c in enumerate(
        ["NVIDIA", "NVIDIA", "NVIDIA AI", "NVIDIA Corporation", "OpenAI", "OpenTrain AI"])]

    direct = next(e for e in build(recs).employers if "direct" in e.question)
    by_name = {x.name: x for x in direct.employers}
    assert by_name["NVIDIA"].n == 4
    assert sorted(by_name) == ["NVIDIA", "OpenAI", "OpenTrain AI"]


@needs_model
def test_the_keyword_ranking_groups_the_spellings_the_bullet_bank_would_split():
    """This section feeds the bullet bank, so `Node` and `Node.js` counted apart is a keyword that
    reads as half as important as it is. Real corpus spellings."""
    keywords = next(t for t in build(_many({**NODE, **REACT, **NEXT}, "resume_keywords")).terms
                    if t.field == "resume_keywords")
    assert {c.label: c.count for c in keywords.clusters} == {"React": 427, "Node.js": 308, "Next.js": 88}
