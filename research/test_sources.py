"""Tests for the market-data source registry.  Run:  .venv/bin/python -m pytest research/ -q

Offline. No network, no key, no HTML fixture — and the last one is deliberate. The nine `fetch()`
bodies scrape live pages; a pinned 2026-07 fixture would only prove the parser still parses last
year's page, which is the exact false confidence the rot warning exists to deny. What is testable is
everything *around* the fetch: the registry's shape, that one broken source cannot take the others
down, and that the key-gated three degrade to empty rather than to a traceback.

Prior art for the docstring assertions at the bottom: `triage/test_setup_skill.py`. A warning that
only lives in prose is a warning a later edit can delete without anything noticing.
"""
from __future__ import annotations

from pathlib import Path

from core.models import Job

from . import sources
from .sources import adzuna, himalayas, jsearch, remotive, theirstack
from core.scrapers.posting import posting

ROOT = Path(__file__).resolve().parent.parent

KEY_ENV = {"adzuna": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
           "jsearch": ("RAPIDAPI_KEY",),
           "theirstack": ("THEIRSTACK_KEY",)}


# --- the registry ------------------------------------------------------------------------------


def test_every_registered_source_is_classified_scraper_feed_or_key_gated():
    """The zero-key promise is a claim about this partition. A source added to `ALL` and to none of
    the three tuples is a source nobody has decided the key story for — which is how "works with no
    key" quietly becomes "works with no key, except that one". The split is also the honest
    description of the failure modes: a scraper rots silently, a feed 404s, a keyed source stays
    empty until someone signs up."""
    groups = (set(sources.AGENCIES), set(sources.KEYED), set(sources.FEEDS))
    assert set(sources.ALL) == set().union(*groups)
    assert sum(len(g) for g in groups) == len(set().union(*groups)), "a source is in two tiers"


def test_the_six_keyless_agency_scrapers_survived_the_move():
    """The reason the frozen pipeline was gutted rather than deleted: these are the only keyless
    source of *contract* supply found. Losing one in a later refactor loses that."""
    assert set(sources.AGENCIES) == {"insightglobal", "mondo", "teksystems", "kore1", "motion", "apex"}
    assert all(callable(sources.ALL[name]) for name in sources.AGENCIES)


def test_a_crashing_source_costs_that_source_and_nothing_else(monkeypatch):
    """One restructured listing page must not cost the whole pull. It is counted as 0, which is also
    how the caller finds out — see the rot warning."""
    monkeypatch.setitem(sources.ALL, "motion", lambda: (_ for _ in ()).throw(RuntimeError("403")))
    monkeypatch.setitem(sources.ALL, "mondo", lambda: [Job(link="https://example.test/1")])

    jobs, counts = sources.fetch_all(names=("motion", "mondo"))

    assert counts == {"motion": 0, "mondo": 1}
    assert len(jobs) == 1


def test_counts_come_back_per_source_because_they_are_the_rot_detector():
    """No test can see an agency scraper break; the count is what a caller compares against normal."""
    empty, counts = sources.fetch_all(names=())
    assert empty == [] and counts == {}


def test_an_unknown_source_name_is_logged_and_skipped_not_raised():
    assert sources.fetch_all(names=("nosuchsource",)) == ([], {})


# --- degrading to absent, never to silent ------------------------------------------------------


def test_each_key_gated_source_returns_nothing_when_its_key_is_unset(monkeypatch):
    """The standing zero-key rule, as behaviour. The failure direction is a stranger's first run
    dying in an auth error from a service they never signed up for."""
    for name, env_names in KEY_ENV.items():
        for env in env_names:
            monkeypatch.setenv(env, "")
        assert sources.ALL[name]() == [], name


def test_the_key_gated_three_make_no_request_before_checking_the_key(monkeypatch):
    """Guard the guard: if the check moved below the first call, the test above would still pass on
    a machine with no network and mean nothing."""
    def explode(*a, **kw):
        raise AssertionError("a request was made before the key check")

    for mod in (adzuna, jsearch, theirstack):
        monkeypatch.setattr(mod.requests, "get", explode, raising=False)
        monkeypatch.setattr(mod.requests, "post", explode, raising=False)
    for name, env_names in KEY_ENV.items():
        for env in env_names:
            monkeypatch.setenv(env, "")
        assert sources.ALL[name]() == [], name


# --- one Job, with the market facts in the text ------------------------------------------------


def test_a_posting_becomes_the_shared_job_with_its_facts_in_the_jd_text():
    """The frozen pipeline's rival `Job` is deleted; `core.models.Job` is the one carrier. What a source knows
    structurally rides in the JD header, in a fixed order, so a regex can get it back."""
    job = posting(title="  Senior React Developer ", company="Acme", link="https://x.test/1",
                  source="motion", description="Build things. Pays $85.00 - $90.00 per hour.",
                  employment_type="CONTRACTOR", metro="Remote", cadence="remote",
                  rate="$85-90/hr", posted="2026-07-01")

    assert isinstance(job, Job)
    assert job.title == "Senior React Developer"
    assert job.source_platform == "motion"
    assert job.posted_hint == "2026-07-01"
    assert job.fetched_jd.startswith(
        "Employment type: CONTRACTOR. Location: Remote. Cadence: remote. Posted rate: $85-90/hr.")
    assert "Build things." in job.jd_text


def test_a_source_that_returned_no_description_is_not_recorded_as_a_full_jd():
    """`jd_source` is what the retrospective uses to say how much of its sample it actually read.
    Calling a listing row a full JD inflates that number with text nobody fetched."""
    listing_only = posting(title="Developer", company="KORE1", link="https://x.test/2",
                           source="kore1", metro="Irvine, CA")
    assert listing_only.jd_source == "title_only"
    assert listing_only.fetched_jd == "Location: Irvine, CA."

    with_text = posting(title="Developer", company="KORE1", link="https://x.test/3",
                        source="kore1", description="Five years of React.")
    assert with_text.jd_source == "full"


def test_the_rate_extractor_reads_a_posting_built_this_way():
    """The seam the whole stage rests on: source -> Job.jd_text -> core/rates.py."""
    from core.rates import extract
    job = posting(title="Dev", company="Acme", link="https://x.test/4", source="mondo",
                  description="Contract role. Compensation: $80–$110/hour.")
    assert extract(job.jd_text) == "$80-110/hr"


# --- a predicted salary is never laundered into a posted rate ----------------------------------


def test_adzunas_predicted_salary_never_reaches_the_rate_extractor():
    """The single most damaging thing this module could do. A live 50-row US sample came back 100%
    `salary_is_predicted: "1"` with min == max — a model's point estimate. Printing it with a label
    is not enough: the label does not survive `core/rates.py`, which would hand the report a
    machine-generated number indistinguishable from an employer's offer."""
    from core.rates import extract
    job = adzuna._to_job({"title": "Dev", "company": {"display_name": "Acme"},
                          "redirect_url": "https://x.test/5", "description": "Great role.",
                          "salary_min": 150000, "salary_max": 150000, "salary_is_predicted": "1"})
    assert "PREDICTED" in job.fetched_jd
    assert "150000" not in job.fetched_jd
    assert extract(job.jd_text) is None


def test_an_absent_predicted_flag_is_treated_as_predicted():
    """Unknown provenance is not evidence. The unfiltered `/search` results do not always carry the
    flag, and defaulting the other way would print exactly the numbers this guards against."""
    job = adzuna._to_job({"title": "Dev", "company": {"display_name": "Acme"},
                          "redirect_url": "https://x.test/6", "salary_min": 140000})
    assert "140000" not in job.fetched_jd


def test_a_genuinely_posted_adzuna_salary_is_kept():
    """The guard must not be a blanket refusal, or a real posted range would be thrown away too."""
    from core.rates import extract
    job = adzuna._to_job({"title": "Dev", "company": {"display_name": "Acme"},
                          "redirect_url": "https://x.test/7", "description": "Great role.",
                          "salary_min": 150000, "salary_max": 180000, "salary_is_predicted": "0"})
    assert extract(job.jd_text) == "$72-87/hr"


# --- Adzuna: the label comes from the query, and the JD comes from the detail page --------------
#
# Both fixtures below are verbatim from live Adzuna responses on 2026-07-22, abridged only where an
# ellipsis says so. Pinning invented strings here would prove nothing: the whole reason these two
# defects survived a month is that the code read plausibly and the wire did not match it.

# One ad's `/search` row and its `/details/{id}` page. Adzuna cuts the row at exactly 500 characters,
# mid-word; the pay sits ~4,200 characters further down under a `Compensation` heading.
_TEASER = ("Mindrift is looking for skilled Mobile App Developers (React Native, Flutter, Swift, or "
           "Kotlin) to help train and evaluate AI models. You will apply your judgment, and quality "
           "control to ensure …")
_FULL = ("Mindrift is looking for skilled\nMobile App Developers (React Native, Flutter, Swift, or "
         "Kotlin)\nto help train and evaluate AI models. You will apply your judgment, and quality "
         "control to ensure the project is active.\nCompensation\nOn this project, contributors can "
         "earn up to\n$60 per hour equivalent\n, depending on their level and pace of contribution.\n")

# What Adzuna serves instead of a detail page when it decides you are asking too fast. HTTP 200.
_CLOUDFRONT_403 = ("Title: The request could not be satisfied\n\nURL Source: "
                   "https://www.adzuna.com/details/5810471140\n\nWarning: Target URL returned error "
                   "403: Forbidden\n\nMarkdown Content:\n## 403 ERROR\n\nRequest blocked. We can't "
                   "connect to the server for this app or website at this time.\n\nGenerated by "
                   "cloudfront (CloudFront)\n")


def test_contract_and_permanent_are_fetched_as_two_separate_filtered_queries(monkeypatch):
    """The defect this replaces: an unfiltered `/search` row mostly has no `contract_type` at all, so
    every posting was emitted as "unspecified" and the contract-vs-perm cut — the most important one
    in the report — was never actually available from this source. A single query cannot recover it."""
    calls: list[dict] = []

    class _Resp:
        @staticmethod
        def raise_for_status(): pass
        @staticmethod
        def json(): return {"results": []}

    monkeypatch.setenv("ADZUNA_APP_ID", "id"), monkeypatch.setenv("ADZUNA_APP_KEY", "k")
    monkeypatch.setattr(adzuna.requests, "get", lambda url, **kw: (calls.append(kw["params"]), _Resp())[1])
    monkeypatch.setattr(adzuna, "THROTTLE", 0)

    adzuna.fetch()

    assert len(calls) == 2 * len(adzuna.TERMS)
    for p in calls:
        assert ("contract" in p) != ("permanent" in p), "a row's label must come from one filter"
    for flag in ("contract", "permanent"):
        assert {p["what"] for p in calls if flag in p} == set(adzuna.TERMS)


def test_the_query_that_returned_a_row_is_what_labels_its_employment_type():
    """Filtered rows do carry `contract_type`, but the fallback is the point: if Adzuna drops the field
    again the label degrades to the filter that found the row, not to "unspecified"."""
    labelled = adzuna._to_job({"title": "Dev", "redirect_url": "https://x.test/8",
                               "contract_type": "contract", "contract_time": "full_time"},
                              filtered_as="contract", full_description="Build things.")
    assert labelled.fetched_jd.startswith("Employment type: contract full_time.")

    unlabelled = adzuna._to_job({"title": "Dev", "redirect_url": "https://x.test/9"},
                                filtered_as="permanent", full_description="Build things.")
    assert unlabelled.fetched_jd.startswith("Employment type: permanent.")


def test_the_untruncated_description_is_what_the_rate_extractor_reads():
    """Box 4, and the measurement behind it: over 43 live contract postings a rate came out of 17
    teasers and 38 full JDs. Worse than the misses, one teaser yielded `$96/hr` where the ad said
    `$77-87/hr` — truncation does not only lose rates, it invents them."""
    from core.rates import extract
    assert extract(_TEASER) is None
    assert extract(_FULL) == "$60/hr"

    job = adzuna._to_job({"title": "Freelance Mobile App Developer", "redirect_url": "https://x.test/10",
                          "description": _TEASER}, filtered_as="contract", full_description=_FULL)
    assert extract(job.jd_text) == "$60/hr"
    assert job.jd_source == "full"


def test_a_row_left_on_the_teaser_is_not_recorded_as_a_full_jd():
    """`jd_source` is how the retrospective states its own coverage. A 500-character opener counted as
    a JD it read inflates that number with text nobody has. The text is still on the record."""
    job = adzuna._to_job({"title": "Dev", "redirect_url": "https://x.test/11", "description": _TEASER},
                         filtered_as="contract")
    assert job.jd_source == "title_only"
    assert "Mindrift" in job.jd_text


def test_an_error_page_wearing_a_200_is_never_stored_as_the_job_description():
    """The load-bearing guard. Adzuna answers a burst with a CloudFront 403 interstitial at HTTP 200,
    and `core.fetch` cannot tell it from a short JD — at four concurrent workers 12 of 25 detail pages
    came back that way. Without this check those become JD text, and a rate read out of an error page
    is a fabricated number in a negotiation."""
    assert not adzuna._is_same_ad(_TEASER, _CLOUDFRONT_403)
    assert not adzuna._is_same_ad(_TEASER, "")
    assert not adzuna._is_same_ad("", _FULL)          # no teaser is no evidence, not a free pass


def test_the_same_ad_check_tolerates_adzunas_own_whitespace_disagreement():
    """Guard the guard, in the other direction. The API row and the detail page space the same ad
    differently (`info_outline X In` against `info_outline\\nXIn`), so a strict comparison would reject
    good pages and quietly leave every posting on its teaser."""
    row = ("info_outline X In accordance with Washington state law, we are highlighting our "
           "comprehensive benefits package, which is available to all eligible US based employees.")
    page = ("info_outline\nXIn accordance with Washington state law, we are highlighting our "
            "comprehensive benefits package, which is available to all eligible US based employees."
            "\nHealth insurance.")
    assert adzuna._is_same_ad(row, page)


# --- the two keyless feeds: rejected as channels, kept as market data ---------------------------
#
# Both rows below are verbatim from live responses on 2026-07-22, abridged only where an ellipsis
# says so. The numbers asserted are what the shipped code actually returned for them.

# Himalayas. Permanent-heavy by construction: over 1,000 live rows the developer slice was 87 Full
# Time to 6 Contractor, which is why this is a market source and not a contract-search channel.
_HIMALAYAS_ROW = {
    "title": "Senior Quality Systems Application Analyst",
    "companyName": "Simtra BioPharma Solutions",
    "employmentType": "Full Time",
    "minSalary": 120000, "maxSalary": 135000, "salaryPeriod": "annual", "currency": "USD",
    "locationRestrictions": ["United States"],
    "parentCategories": ["Developer"],
    "description": "<p><em>Simtra BioPharma Solutions</em> (Simtra) is a &amp; world-class CDMO.</p>",
    "pubDate": 1784666194,
    "applicationLink": "https://himalayas.app/companies/simtra-biopharma-solutions/jobs/"
                       "senior-quality-systems-application-analyst",
}

# Remotive. The reason this small feed is here at all: a contract row with an *hourly* string.
_REMOTIVE_ROW = {
    "id": 1919265,
    "url": "https://remotive.com/remote-jobs/software-development/"
           "senior-independent-software-developer-1919265",
    "title": "Senior Independent Software Developer",
    "company_name": "A.Team",
    "category": "Software Development",
    "job_type": "contract",
    "publication_date": "2026-07-16T10:10:51",
    "candidate_required_location": "Americas, Europe, Israel",
    "salary": "$90 - $150 /hour",
    "description": "<p><em>You must be located in the Americas, Europe, or Israel to apply.</em></p>",
}


def test_remotives_hourly_string_reaches_the_shared_rate_extractor():
    """The whole justification for a 41-row feed. Nothing else keyless in this registry returns an
    hourly *contract* rate as text — Adzuna's is an annualised model estimate, Himalayas was 39-of-39
    annual, CALC+ is a federal ceiling. A parser written here instead would be a second, divergent
    answer to a question `core/rates.py` already owns."""
    job = remotive._to_job(_REMOTIVE_ROW)
    assert job.fetched_jd.startswith("Employment type: contract. Location: Americas, Europe, Israel. "
                                     "Cadence: remote. Posted rate: $90-150/hr.")
    from core.rates import extract
    assert extract(job.jd_text) == "$90-150/hr"


def test_himalayas_annual_salary_is_normalised_through_the_same_extractor():
    """One extractor over both feeds, or the report has two medians for the same market."""
    job = himalayas._to_job(_HIMALAYAS_ROW)
    assert "Posted rate: $58-65/hr." in job.fetched_jd
    assert job.company == "Simtra BioPharma Solutions"
    assert job.posted_hint == "2026-07-21"
    assert job.jd_source == "full"
    assert "world-class CDMO" in job.jd_text and "<p>" not in job.jd_text


def test_a_himalayas_salary_in_a_currency_this_cannot_convert_is_dropped_not_converted():
    """The false-positive direction, and it is not hypothetical: the live sample carried MXN, INR,
    BRL, ZAR, SEK and CAD rows. 500,000 MXN a year lands *inside* the extractor's $10-600/hr sanity
    window as $240/hr, so an unconverted currency is a fabricated rate rather than a missing one.
    Same for `monthly`, which the extractor has no unit to read and infers as annual — 12x wrong."""
    foreign = dict(_HIMALAYAS_ROW, currency="MXN", minSalary=500000, maxSalary=500000)
    assert "Posted rate" not in himalayas._to_job(foreign).fetched_jd

    monthly = dict(_HIMALAYAS_ROW, salaryPeriod="monthly", minSalary=8000, maxSalary=9000)
    assert "Posted rate" not in himalayas._to_job(monthly).fetched_jd


def test_the_dev_cut_is_made_here_because_the_apis_own_filters_do_nothing():
    """Measured live: `category=`, `search=` and a `parentCategory` guess all return HTTP 200 with
    the same unfiltered rows, and Remotive's `limit=5` and `limit=100` returned the same 41. A
    source that trusted those parameters would report a sales-heavy board as the developer market."""
    assert himalayas._is_dev(_HIMALAYAS_ROW)
    assert not himalayas._is_dev(dict(_HIMALAYAS_ROW, parentCategories=["Sales"]))
    assert not himalayas._is_dev(dict(_HIMALAYAS_ROW, parentCategories=[]))


def test_either_feed_being_unreachable_is_an_empty_list_not_an_exception(monkeypatch):
    """The external half degrades to a labelled gap, never to a shorter report. `fetch_all` would
    catch a raise anyway — this is the layer below, so the log line names the feed rather than the
    registry, and a Himalayas failure on page 30 keeps the first 29 pages."""
    def dead(*a, **kw):
        raise OSError("connection reset")

    monkeypatch.setattr(himalayas.requests, "get", dead)
    monkeypatch.setattr(remotive.requests, "get", dead)
    assert himalayas.fetch() == []
    assert remotive.fetch() == []


def test_neither_feed_is_wired_as_a_job_input_channel():
    """The decision this directory exists to make physical: `triage/channels/` is where my jobs come
    from, `research/sources/` is where market data comes from. Himalayas is 87-to-6 permanent, and
    Remotive's own API terms forbid republishing its rows as listings. Read as text rather than
    imported, because `core/test_layering.py` forbids one leaf importing another — including here."""
    channels = ROOT / "triage" / "channels"
    registry = "\n".join(p.read_text(encoding="utf-8") for p in sorted(channels.glob("*.py")))
    assert "mail" in registry, "guard the guard — an empty read would pass this test vacuously"
    for name in sources.FEEDS:
        assert name not in registry.lower(), f"{name} has been wired as a job-input channel"


# --- attribution is an obligation, so it is enforced rather than documented ---------------------


def test_every_attribution_bearing_source_stamps_its_line_onto_every_record():
    """A ToS obligation, asserted rather than trusted. In a render template it is one template edit
    from gone; on the record it has to be stripped on purpose."""
    for mod, row in ((himalayas, _HIMALAYAS_ROW), (remotive, _REMOTIVE_ROW)):
        assert mod.ATTRIBUTION in mod._to_job(row).jd_text
    assert adzuna.ATTRIBUTION in adzuna._to_job({"title": "Dev", "redirect_url": "https://x.test/12"},
                                                filtered_as="contract").jd_text
    assert set(sources.ATTRIBUTION) <= set(sources.ALL)
    assert all(line.strip() for line in sources.ATTRIBUTION.values())


def test_a_job_that_lost_its_attribution_line_is_dropped_rather_than_published(monkeypatch):
    """The enforcement point. Losing the row is the cheap direction — an un-attributed listing is the
    breach that gets a stranger's API access terminated, and Remotive says so in its own payload."""
    good = remotive._to_job(_REMOTIVE_ROW)
    bare = Job(link="https://remotive.com/remote-jobs/x", fetched_jd="No credit here.")
    monkeypatch.setitem(sources.ALL, "remotive", lambda: [good, bare])

    jobs, counts = sources.fetch_all(names=("remotive",))

    assert counts == {"remotive": 1}
    assert jobs == [good]


def test_a_report_credits_only_the_sources_that_actually_returned_rows():
    """Crediting a source that returned nothing reads as data the report does not have — which is the
    same silent-degradation failure the labelled-gap rule exists for, wearing a footnote."""
    lines = sources.attribution_lines({"himalayas": 40, "remotive": 0, "mondo": 12})
    assert lines == [himalayas.ATTRIBUTION]
    assert sources.attribution_lines({}) == []


# --- the rot warning is where the next person will see it --------------------------------------


def test_the_agency_scrapers_are_flagged_rot_prone_in_the_registry_itself():
    """Not in a doc beside the code. Someone reaching for a seventh scraper reads this file, and the
    thing they most need to know is that the six already here fail silently and by returning zero."""
    doc = sources.__doc__ or ""
    assert "ROT-PRONE" in doc
    assert all(name in doc for name in sources.AGENCIES)
    assert "count" in doc.lower()   # the detector, named
