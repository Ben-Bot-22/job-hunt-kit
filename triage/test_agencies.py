"""The `agencies` channel: six staffing-firm scrapers in, in-window postings out.
Run:  .venv/bin/python -m pytest triage/ -q

Everything here is offline. `agencies.fetch` takes its source list AND the scraper registry as keyword
arguments for exactly that reason — the one thing this channel does that touches the world is call
`core.scrapers.AGENCIES[name]()`, and it is injected here, so these are real end-to-end assertions
about the channel rather than assertions about a mock of it. Pinning an HTML fixture would prove only
that a 2026-07 page still parses, which is not what this module is for: the scraping is `core/`'s and
its rot is undetectable in a test suite by construction.

The failure directions, in the order they cost something:

  * **A rotted scraper looking like a quiet market.** These six fail by returning ZERO, not by
    raising. On a monthly report that costs one table row; on a daily worklist it is invisible for as
    long as nobody looks. The warning and the per-source counts on the health line are the only
    detector that exists, so most of this file is about them.
  * **The warning firing on a quiet week.** The mirror image, and it kills the detector just as dead:
    a source with 80 postings and none inside a three-day window is not broken, and a `⚠` there
    trains you to ignore the one that matters.
  * **One source costing the run.** A hung host, a scraper raising on restructured markup, a name
    that no longer exists — each must cost that agency's postings and nothing else.
  * **These jobs being re-fetched.** They arrive with the full JD already attached, exactly like a
    board's; a channel that let them look `title_only` would buy 200 needless round trips a morning.
"""
from __future__ import annotations

from concurrent.futures import TimeoutError as _FutureTimeout
from datetime import date, timedelta

from core.models import Job
from core.scrapers.posting import posting

from . import channels
from .channels import agencies


def _day(ago: int) -> str:
    return (date.today() - timedelta(days=ago)).isoformat()


def _job(agency: str, title: str, *, ago: int | None = 1, source: str = "") -> Job:
    """A posting exactly as `core/scrapers/*.py` build one — through the shared `posting()` helper, so
    the JD header, the `full` jd_source and the `YYYY-MM-DD` posted date are the real ones."""
    slug = title.lower().replace(" ", "-")
    return posting(title=title, company=agency, link=f"https://{source or agency}.test/jobs/{slug}",
                   source=source or agency.lower(), employment_type="Contract", metro="Remote",
                   posted="" if ago is None else _day(ago),
                   description="A contract role building Python services against a Postgres database, "
                               "with a team that ships weekly and reviews every change.")


def _src(*jobs: Job):
    """A scraper is a zero-argument function returning jobs — the entire contract being faked."""
    return lambda: list(jobs)


def _boom():
    raise RuntimeError("listing page returned 403")


_REGISTRY = {
    "insightglobal": _src(_job("Insight Global", "Senior Python Engineer"),
                          _job("Insight Global", "React Developer", ago=2)),
    "teksystems": _src(_job("TEKsystems", "Full Stack Engineer")),
    "motion": _src(),                                  # ran, returned nothing — the rot signal
    "mondo": _src(_job("Mondo", "Platform Engineer", ago=40)),   # postings, none in a 3-day window
}
_NAMES = list(_REGISTRY)


# --- the postings themselves ----------------------------------------------------------------------

def test_the_enabled_sources_produce_postings_from_every_agency() -> None:
    """The channel's first-order promise: name agencies, get their reqs, with no key anywhere."""
    jobs = agencies.fetch(3, sources=_NAMES, agencies=_REGISTRY)
    assert [(j.company, j.title) for j in jobs] == [
        ("Insight Global", "Senior Python Engineer"),
        ("Insight Global", "React Developer"),
        ("TEKsystems", "Full Stack Engineer"),
    ]


def test_the_jd_arrives_with_the_posting_and_is_never_fetched_again() -> None:
    """The scrapers already fetched the detail page; `jd_source="full"` is what makes
    `__main__._fetch` leave the job alone — the same guard `boards` and `paste` rely on."""
    from .__main__ import _fetch
    job = agencies.fetch(3, sources=["teksystems"], agencies=_REGISTRY)[0]
    assert job.jd_source == "full"
    assert "Employment type: Contract." in job.jd_text
    assert _fetch(job).jd_text == job.jd_text          # no second round trip


def test_identity_is_the_ordinary_composite_so_seen_json_works() -> None:
    """The agency is the company and the scraper states the title, so an agency job is keyed like any
    other job the moment it is created — no model call, no link fallback."""
    from core.models import composite_id
    job = agencies.fetch(3, sources=["teksystems"], agencies=_REGISTRY)[0]
    assert job.id == composite_id("TEKsystems", "Full Stack Engineer")
    assert "://" not in job.id


# --- the freshness window -------------------------------------------------------------------------

def test_a_posting_outside_the_window_is_not_returned() -> None:
    """Mondo's only posting is 40 days old. The scrapers return whatever the board shows; the window
    is this module's job, because a monthly report wants the whole board and a morning does not."""
    fresh = agencies.fetch(3, sources=_NAMES, agencies=_REGISTRY)
    assert "Platform Engineer" not in [j.title for j in fresh]
    everything = agencies.fetch(0, sources=_NAMES, agencies=_REGISTRY)
    assert "Platform Engineer" in [j.title for j in everything]


def test_an_undated_posting_is_kept_rather_than_dropped() -> None:
    """A source that stops stating dates would otherwise go permanently silent — the failure you
    cannot notice. Keeping it costs one noisy run; `seen.json` handles it from the second."""
    reg = {"apex": _src(_job("Apex Systems", "Data Engineer", ago=None))}
    jobs = agencies.fetch(3, sources=["apex"], agencies=reg)
    assert [j.title for j in jobs] == ["Data Engineer"]
    assert jobs[0].posted_hint == ""


def test_postings_come_back_newest_first() -> None:
    """The per-source cap cuts the tail, so the order decides what a capped source drops."""
    reg = {"a": _src(_job("A", "Older", ago=3), _job("A", "Newer", ago=1))}
    assert [j.title for j in agencies.fetch(7, sources=["a"], agencies=reg)] == ["Newer", "Older"]


def test_the_per_source_cap_bounds_one_republished_board() -> None:
    reg = {"a": _src(*[_job("A", f"Engineer {i}") for i in range(agencies._MAX_PER_SOURCE + 25)])}
    assert len(agencies.fetch(3, sources=["a"], agencies=reg)) == agencies._MAX_PER_SOURCE


def test_sample_caps_the_run_so_the_channel_can_be_smoke_tested() -> None:
    assert len(agencies.fetch(3, 1, sources=_NAMES, agencies=_REGISTRY)) == 1


def test_a_posting_with_no_link_or_no_title_is_dropped() -> None:
    """No link is nothing to apply to. No title is worse: the company is the agency name, so every
    title-less Motion posting would share the id `motion||` — stage 4 · 01's collision, again."""
    reg = {"a": _src(Job(link="", company="A", title="No link"), Job(link="https://a.test/1", company="A"))}
    assert agencies.fetch(0, sources=["a"], agencies=reg) == []


# --- the zero, which is the whole point -----------------------------------------------------------

def test_a_source_that_returns_zero_gets_a_warning_naming_it(caplog) -> None:
    """The documented silent-zero failure, said out loud. `motion` ran fine and returned nothing,
    which for this family of scrapers is a bug report rather than an empty market."""
    with caplog.at_level("WARNING", logger="triage.channels.agencies"):
        agencies.fetch(3, sources=_NAMES, agencies=_REGISTRY)
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("motion" in w and "ZERO" in w for w in warnings)


def test_a_quiet_window_is_not_warned_about(caplog) -> None:
    """The mirror failure, and it is the one that kills the detector: mondo returned a posting, it was
    simply older than the window. A `⚠` here trains you to ignore the `⚠` that means rot."""
    with caplog.at_level("WARNING", logger="triage.channels.agencies"):
        agencies.fetch(3, sources=["mondo"], agencies=_REGISTRY)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert agencies.counts_detail() == "mondo 0"        # a plain zero, no warning mark


def test_the_per_source_counts_reach_the_health_line() -> None:
    """`agencies 3` alone cannot tell you TEKsystems has been dead for a week. The breakdown is
    registered in `channels.DETAIL` and rendered in parentheses after the count.

    The numbers are what each source CONTRIBUTED; the `⚠` is on its RAW count being zero — which is
    why mondo, whose one posting fell outside the window, shows `0` without a mark and motion shows
    `0 ⚠`.
    """
    channels.ingest(3, channels={"agencies": lambda d, s=None: agencies.fetch(d, s, sources=_NAMES,
                                                                             agencies=_REGISTRY)},
                    enabled=lambda name: True)      # the shipped config has it off; see the last test
    assert channels.counts_line(channels.LAST_RUN) == (
        "agencies 3 (insightglobal 2, teksystems 1, motion 0 ⚠, mondo 0)")


def test_counts_are_replaced_each_run_and_not_accumulated() -> None:
    """`LAST_COUNTS` is a side channel like `channels.LAST_RUN`; a stale source lingering in it would
    put a dead agency's count on a run that never asked for that agency."""
    agencies.fetch(3, sources=_NAMES, agencies=_REGISTRY)
    agencies.fetch(3, sources=["teksystems"], agencies=_REGISTRY)
    assert agencies.counts_detail() == "teksystems 1"


# --- isolation ------------------------------------------------------------------------------------

def test_a_raising_source_costs_that_source_only(caplog) -> None:
    """The registry already isolates the CHANNEL; this isolates each SOURCE inside it. A scraper that
    raises on restructured markup must not cost the other three agencies their reqs."""
    reg = {**_REGISTRY, "apex": _boom}
    with caplog.at_level("WARNING", logger="triage.channels.agencies"):
        jobs = agencies.fetch(3, sources=[*_NAMES, "apex"], agencies=reg)
    assert [j.company for j in jobs] == ["Insight Global", "Insight Global", "TEKsystems"]
    assert any("apex" in r.getMessage() and "403" in r.getMessage() for r in caplog.records)
    assert agencies.counts_detail().endswith("apex 0 ⚠")


def test_every_source_failing_is_an_empty_list_and_not_an_exception() -> None:
    """Raising would reach the registry as `agencies CRASHED`, which reads as "you are missing jobs".
    Six boards that all happen to be down is an `agencies 0` — with six warnings above it."""
    assert agencies.fetch(3, sources=["a", "b"], agencies={"a": _boom, "b": _boom}) == []


def test_a_source_that_hangs_is_abandoned_rather_than_stalling_the_run(caplog, monkeypatch) -> None:
    """A thread cannot be interrupted mid-request, so a source still running at the deadline is
    abandoned and the channel moves on — the scraper finishes into the void. That is the right trade
    against a run that never starts. The deadline is SHARED across the sources rather than per-source,
    so four hung agencies cost 300s once and not 300s each.

    Exercised by making the *wait* fail rather than by actually sleeping 300 seconds.
    """
    class _Hung:
        def result(self, timeout=None):
            raise _FutureTimeout()

    real_submit = agencies.ThreadPoolExecutor.submit
    monkeypatch.setattr(agencies.ThreadPoolExecutor, "submit",
                        lambda self, fn, *a, **k: (_Hung() if a[0] is _REGISTRY["teksystems"]
                                                   else real_submit(self, fn, *a, **k)))
    with caplog.at_level("WARNING", logger="triage.channels.agencies"):
        jobs = agencies.fetch(3, sources=["insightglobal", "teksystems"], agencies=_REGISTRY)
    assert [j.company for j in jobs] == ["Insight Global", "Insight Global"]
    assert any("teksystems" in r.getMessage() and "abandoned" in r.getMessage()
               for r in caplog.records)


def test_an_unknown_source_name_is_skipped_rather_than_crashing_the_channel(caplog) -> None:
    """A retired or misspelled scraper name costs its own postings. The settings schema validates the
    KEY, not the list contents — a name is data, and this is where data is checked."""
    with caplog.at_level("WARNING", logger="triage.channels.agencies"):
        jobs = agencies.fetch(3, sources=["teksystems", "no-such-agency"], agencies=_REGISTRY)
    assert [j.company for j in jobs] == ["TEKsystems"]
    assert any("no-such-agency" in r.getMessage() for r in caplog.records)


# --- the defaults and the registry ----------------------------------------------------------------

def test_the_default_source_list_is_the_four_measured_healthy() -> None:
    """apex and kore1 returned 3 and 2 postings on 2026-07-22 with no error — the silent-zero failure
    this family has. They stay registered as market supply and are one config line from coming back;
    what would bring them back is a double-digit count that survives a spot-check."""
    from core.scrapers import AGENCIES
    assert agencies.DEFAULT_SOURCES == ("insightglobal", "teksystems", "motion", "mondo")
    assert set(agencies.DEFAULT_SOURCES) < set(AGENCIES)
    assert {"apex", "kore1"} == set(AGENCIES) - set(agencies.DEFAULT_SOURCES)


def test_an_unconfigured_source_list_falls_back_to_the_healthy_four(monkeypatch) -> None:
    """Empty here means "you named nothing", not "read nothing" — the sources are the tool's, not the
    user's. Failure direction: a channel enabled in config that reads no agencies at all."""
    monkeypatch.setattr(agencies.config, "agency_sources", lambda: [])
    called: list[str] = []
    reg = {name: (lambda n=name: called.append(n) or []) for name in agencies.DEFAULT_SOURCES}
    agencies.fetch(3, agencies=reg)
    assert sorted(called) == sorted(agencies.DEFAULT_SOURCES)


def test_agencies_is_registered_below_boards_and_above_paste() -> None:
    """Registry order decides which copy of a duplicate posting survives. Several agencies resell the
    same client req, so a posting on both a company's own board and a staffing firm's must survive as
    the employer's copy — that one names the client; the agency's says "a leading financial firm"."""
    assert list(channels.ALL) == ["mail", "boards", "agencies", "paste", "gmail"]
    assert channels.ALL["agencies"] is agencies.fetch
    assert channels.DETAIL["agencies"] is agencies.counts_detail


def test_the_keyless_demo_keeps_the_scrape_off() -> None:
    """The fast try-it path stays fast: `config/example/` is the seconds-long keyless demo (and the
    fixture), and agencies is a ~131s six-site scrape — neither keyless-fast nor part of that story.
    So the DEMO ships it off, even though the real `config/settings.yaml` ships it on for contract
    supply. This pins the demo invariant, not the live config, which the owner may set either way."""
    from core.settings import load, REPO_ROOT
    example = load(REPO_ROOT / "config" / "example" / "settings.yaml")
    assert example["channels"]["agencies"]["enabled"] is False
