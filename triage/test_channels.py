"""The channel registry, exercised through `ingest()` with fake channels.
Run:  .venv/bin/python -m pytest triage/ -q

`ingest(days, sample, *, channels, enabled)` is the whole seam: fan-out, per-channel isolation,
cross-channel dedup and the counts the run summary prints. Injecting the registry means these can be
real end-to-end assertions with no mail, no network and no model — the only thing not covered is the
`osascript` transport itself, which is untestable offline and unchanged by this stage.

The failure directions, in the order they cost something:

  * A channel that raises taking the run with it. Mail is Ben's only supply today; the moment
    `boards` lands, a rotted scraper must cost him that scraper and nothing else — the whole reason
    each channel gets its own `try/except` rather than one around the loop.
  * "Off" and "ran, found nothing" printing the same. A channel that was never enabled looks exactly
    like a channel with an empty window, and the difference is a week of silently missing jobs.
  * A posting arriving on two channels being scored twice — one wasted Opus call each morning, and a
    worklist that reads as if the market is bigger than it is.
"""
from __future__ import annotations

import pytest

from . import channels
from core.models import Job
from core.settings import CHANNEL_NAMES


def _job(link: str = "", company: str = "", title: str = "") -> Job:
    return Job(link=link, company=company, title=title)


def _channel(*jobs: Job):
    """A channel is a function returning jobs — that is the entire contract being faked here."""
    return lambda days, sample=None: list(jobs)


def _boom(days, sample=None):
    raise RuntimeError("board API returned 503")


def test_one_crashing_channel_does_not_kill_the_run() -> None:
    """The others' jobs still arrive, and the crash is on the record rather than in a traceback."""
    good = _job("https://boards.greenhouse.io/acme/jobs/1", "Acme", "Engineer")
    candidates, all_extracted = channels.ingest(
        3, channels={"broken": _boom, "mail": _channel(good)}, enabled=lambda _: True)
    assert [j.link for j in candidates] == [good.link]
    assert all_extracted == [good]
    assert [(r.name, r.status) for r in channels.LAST_RUN] == [("broken", "crashed"), ("mail", "ok")]
    assert "503" in dict((r.name, r.error) for r in channels.LAST_RUN)["broken"]


def test_a_crash_is_visible_in_the_summary_line() -> None:
    """A crashed channel must not render as a zero — that is how a dead channel hides for a week."""
    channels.ingest(3, channels={"boards": _boom})
    line = channels.counts_line(channels.LAST_RUN)
    assert line.startswith("boards CRASHED (RuntimeError: board API returned 503")


def test_counts_distinguish_disabled_from_returned_nothing() -> None:
    """Three outcomes, three renderings: 2 jobs, ran-and-found-nothing, and switched off."""
    registry = {"mail": _channel(_job("https://x.test/1", "A", "One"), _job("https://x.test/2", "B", "Two")),
                "boards": _channel(),
                "paste": _channel(_job("https://x.test/3", "C", "Three"))}
    channels.ingest(3, channels=registry, enabled=lambda name: name != "paste")
    assert channels.counts_line(channels.LAST_RUN) == "mail 2 · boards 0 · paste off"
    assert [(r.name, r.status, len(r.jobs)) for r in channels.LAST_RUN] == [
        ("mail", "ok", 2), ("boards", "ok", 0), ("paste", "disabled", 0)]


def test_a_disabled_channel_is_never_called() -> None:
    """`enabled: false` has to mean not-run, not run-and-discard: channels cost money and quota."""
    calls = []

    def spy(days, sample=None):
        calls.append(days)
        return []

    channels.ingest(3, channels={"mail": spy}, enabled=lambda name: False)
    assert calls == []


def test_the_same_job_from_two_channels_appears_once() -> None:
    """Cross-channel collapse, on the dedup key — the same posting on a board and in an alert email.

    Query strings differ between the two (an email link carries tracking), which is exactly why the
    key strips them. The FIRST channel in registry order wins, so `all_extracted` keeps both copies
    for the archive check while only one reaches the analyzer.
    """
    from_board = _job("https://boards.greenhouse.io/acme/jobs/1", "Acme", "Senior Engineer")
    from_mail = _job("https://boards.greenhouse.io/acme/jobs/1?utm_source=alert", "Acme", "Senior Engineer")
    candidates, all_extracted = channels.ingest(
        3, channels={"boards": _channel(from_board), "mail": _channel(from_mail)}, enabled=lambda _: True)
    assert [j.link for j in candidates] == ["https://boards.greenhouse.io/acme/jobs/1"]
    assert len(all_extracted) == 2


def test_days_and_sample_reach_every_channel() -> None:
    """`--days` and `--sample` are the two run-shaping flags; a channel that ignores them re-reads
    the whole window on a sample run, which is how a 'small end-to-end test' becomes a full one."""
    seen = []

    def spy(days, sample=None):
        seen.append((days, sample))
        return []

    channels.ingest(7, 4, channels={"a": spy, "b": spy})
    assert seen == [(7, 4), (7, 4)]


def test_the_registry_is_four_built_channels_and_one_stub() -> None:
    """`ALL` is the built set plus the one honest stub, and this assertion is the reminder that
    registering a channel is a deliberate edit, not a side effect of writing one. `gmail` raises
    rather than returning nothing and ships disabled — see `test_gmail_stub.py`."""
    from .channels import agencies, boards, gmail_api, mail, paste
    assert channels.ALL == {"mail": mail.fetch, "boards": boards.fetch,
                            "agencies": agencies.fetch, "paste": paste.fetch,
                            "gmail": gmail_api.fetch}


def test_the_settings_schema_knows_exactly_these_channels() -> None:
    """The registry and the config schema name the same four channels.

    `core/settings.py` lists the channel names so a misspelled `mial:` is an error rather than a flag
    that switches nothing — but that means registering a fifth channel is an edit in two files. The
    drift fails here, in the package that owns the registry, rather than in review. Failure direction:
    a channel registered and enabled in `ALL` whose config block the loader then rejects, taking down
    every run until someone finds the second file.
    """
    assert set(CHANNEL_NAMES) == set(channels.ALL)


# --- `--channels`: the per-run selection override -----------------------------------------------
# The seam these exercise is `fetch_all(enabled=...)`, which existed before the flag did. The flag
# only builds the predicate — so what is worth testing is the predicate's edges, not the fan-out.

def test_no_selection_falls_through_to_config() -> None:
    """`None` in, `None` out. This is the property that keeps config the default: a run without
    `--channels` must not be distinguishable from one before the flag existed."""
    assert channels.selection(None) is None


def test_selection_is_exhaustive_not_additive() -> None:
    """`--channels agencies` runs agencies and NOTHING else — including channels enabled in config.

    Failure direction that matters: if selection were additive, `--channels agencies` on a normal
    config would also read mail, re-archiving a morning's inbox as a side effect of asking for
    contract supply."""
    picked = channels.selection(["agencies"])
    assert picked("agencies") is True
    assert picked("mail") is False
    assert picked("boards") is False


def test_selection_takes_several_and_ignores_whitespace_and_case() -> None:
    """`--channels mail,agencies` is the both case, and the shell makes stray spaces easy."""
    picked = channels.selection([" Mail ", "agencies"])
    assert picked("mail") is True
    assert picked("agencies") is True
    assert picked("paste") is False


def test_an_unknown_channel_is_a_hard_error_naming_it() -> None:
    """A typo must not mean "no channels", which looks exactly like a quiet morning.

    Same failure philosophy as `config/settings.yaml` validation: name the offender and the valid set
    rather than falling back to a default nobody asked for."""
    with pytest.raises(channels.UnknownChannel) as e:
        channels.selection(["agences"])
    assert "agences" in str(e.value)
    assert "agencies" in str(e.value)      # the valid set is in the message, so the fix is obvious


def test_an_empty_selection_is_an_error_not_silence() -> None:
    """`--channels ''` is a mistake, and running zero channels silently would be the worst reading."""
    with pytest.raises(channels.UnknownChannel):
        channels.selection([""])


def test_selection_drives_fetch_all_and_a_deselected_channel_reports_off() -> None:
    """End of the seam: a channel excluded by selection is `disabled`, not `ok` with zero jobs.

    That distinction is the whole point of `ChannelResult.status` — "you turned it off" and "it ran
    and found nothing" must never render the same on the health line."""
    def never(days, sample=None):
        raise AssertionError("a deselected channel must not be called")

    def one(days, sample=None):
        return []

    results = channels.fetch_all(3, None, channels={"mail": never, "agencies": one},
                                 enabled=channels.selection(["agencies"]))
    by_name = {r.name: r for r in results}
    assert by_name["mail"].status == "disabled"
    assert by_name["agencies"].status == "ok"
    assert "mail off" in channels.counts_line(results)
