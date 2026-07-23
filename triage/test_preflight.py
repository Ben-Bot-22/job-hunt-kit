"""Preflight fires on the degradations that are silent today, and stays quiet on a good config.

The point of these tests is that the *messages* can't rot unnoticed: a preflight that stops warning
about the example rubric is worse than none, because it vouches for a config that produces fiction.
Each check is pinned to a config that should trigger it and one that shouldn't.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from . import config, preflight
from .preflight import Severity


@pytest.fixture(autouse=True)
def _clear_caches():
    """Every accessor here is `lru_cache`d on the config files; these tests rewrite them per case."""
    config.cfg.cache_clear() if hasattr(config.cfg, "cache_clear") else None
    config.profile.cache_clear()
    config.goal_profile.cache_clear()
    yield
    config.profile.cache_clear()
    config.goal_profile.cache_clear()


#: The real function, captured before the autouse fixture below replaces it — the tests that exercise
#: the key check itself need the genuine article, not the stub every other test runs against.
_real_missing_provider_key = preflight._missing_provider_key


@pytest.fixture(autouse=True)
def _key_check_is_neutral(monkeypatch):
    """The provider-key finding is the one check that depends on the machine, not on the config.

    A developer with a key in `.env` and a stranger on a cold clone without one would otherwise get
    different findings from identical config, and every assertion about how many CRITICALs a config
    produces would be true only on one of those machines. Neutralised here; the two tests that care
    set it explicitly.
    """
    monkeypatch.setattr(preflight, "_missing_provider_key", lambda: None)


def _severities(findings) -> set[Severity]:
    return {f.severity for f in findings}


def _whats(findings) -> str:
    return " || ".join(f.what for f in findings)


# --------------------------------------------------------------------------------------------------
# The provider key — the likeliest thing to be missing on a first run
# --------------------------------------------------------------------------------------------------

def test_a_missing_provider_key_is_flagged_first_and_critical(monkeypatch):
    """Without a key every job is fetched and screened before scoring fails, once per job.

    It is reported first because nothing below it matters: a run that cannot score writes no verdicts,
    so a perfect rubric and a full board list change nothing about the outcome.
    """
    monkeypatch.setattr(preflight, "_missing_provider_key",
                        lambda: ("anthropic", "ANTHROPIC_API_KEY"))
    monkeypatch.setattr(preflight, "_rubric_is_example", lambda: False)

    findings = preflight.check()
    assert findings[0].severity is Severity.CRITICAL
    assert "ANTHROPIC_API_KEY" in findings[0].what
    assert ".env" in findings[0].fix


def test_a_provider_that_needs_no_key_is_never_flagged(monkeypatch):
    """`ollama` runs locally and takes no key — `env_var=None` must not read as "missing"."""
    monkeypatch.setattr(preflight, "resolve_provider",
                        lambda: SimpleNamespace(name="ollama", env_var=None))
    assert _real_missing_provider_key() is None


def test_an_unresolvable_provider_is_not_this_modules_error(monkeypatch):
    """A misspelled `llm.provider` is `resolve_provider`'s error to raise at the real call site.

    Preflight exists to explain what is wrong; one that raises while doing it is worse than none.
    """
    def boom():
        raise ValueError("Unknown LLM provider 'anthropc'")
    monkeypatch.setattr(preflight, "resolve_provider", boom)
    assert _real_missing_provider_key() is None


# --------------------------------------------------------------------------------------------------
# The rubric — the CRITICAL one
# --------------------------------------------------------------------------------------------------

def test_the_example_rubric_is_flagged_critical(monkeypatch, tmp_path):
    """A rubric byte-identical to config/example/rubric.md means the scores are a fictional seeker's."""
    example = preflight._EXAMPLE_RUBRIC
    clone = tmp_path / "rubric.md"
    clone.write_bytes(example.read_bytes())            # the exact example, copied — the seed-and-run case
    monkeypatch.setattr(config, "RUBRIC_PATH", clone)

    findings = preflight.check()
    critical = [f for f in findings if f.severity is Severity.CRITICAL]
    assert len(critical) == 1
    assert "rubric" in critical[0].what and "example" in critical[0].what
    assert "/setup" in critical[0].fix or "rubric.md" in critical[0].fix


def test_a_written_rubric_is_not_flagged(monkeypatch, tmp_path):
    """One byte different from the example is a rubric someone owns — no CRITICAL."""
    clone = tmp_path / "rubric.md"
    clone.write_text(preflight._EXAMPLE_RUBRIC.read_text() + "\n# my own line\n", encoding="utf-8")
    monkeypatch.setattr(config, "RUBRIC_PATH", clone)

    assert Severity.CRITICAL not in _severities(preflight.check())


def test_a_missing_rubric_is_not_this_modules_job(monkeypatch, tmp_path):
    """Missing is `goal_profile()`'s loud failure; preflight must not swallow it as 'still the example'."""
    monkeypatch.setattr(config, "RUBRIC_PATH", tmp_path / "does-not-exist.md")
    assert Severity.CRITICAL not in _severities(preflight.check())


# --------------------------------------------------------------------------------------------------
# Standing job source
# --------------------------------------------------------------------------------------------------

def test_no_standing_source_is_degraded(monkeypatch):
    """boards with no tokens AND agencies off = an unattended run finds nothing, and nothing says why."""
    monkeypatch.setattr(config, "board_tokens", lambda: {"greenhouse": [], "lever": []})
    monkeypatch.setattr(config, "channel_enabled", lambda name: name not in ("agencies",))
    # keep the rubric check quiet so we read the source finding in isolation
    monkeypatch.setattr(preflight, "_rubric_is_example", lambda: False)

    findings = preflight.check()
    assert Severity.DEGRADED in _severities(findings)
    assert "no standing job source" in _whats(findings)


def test_named_boards_satisfy_the_source_check(monkeypatch):
    """A greenhouse token is a standing source; the degraded-source finding must not appear."""
    monkeypatch.setattr(config, "board_tokens", lambda: {"greenhouse": ["stripe"], "lever": []})
    monkeypatch.setattr(config, "channel_enabled", lambda name: name == "boards")
    monkeypatch.setattr(preflight, "_rubric_is_example", lambda: False)

    assert "no standing job source" not in _whats(preflight.check())


def test_agencies_on_satisfies_the_source_check(monkeypatch):
    """Agencies enabled is a standing source even with no board tokens."""
    monkeypatch.setattr(config, "board_tokens", lambda: {"greenhouse": [], "lever": []})
    monkeypatch.setattr(config, "channel_enabled", lambda name: name == "agencies")
    monkeypatch.setattr(preflight, "_rubric_is_example", lambda: False)

    assert "no standing job source" not in _whats(preflight.check())


# --------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------

def test_clean_config_renders_nothing():
    """No findings => empty block, no summary line, no banner. The caller prints nothing."""
    assert preflight.format_block([]) == ""
    assert preflight.summary_line([]) is None
    assert preflight.worklist_banner([]) is None


def test_banner_is_critical_only():
    """The worklist banner reserves itself for scores-not-yours; DEGRADED/NOTE stay off the page."""
    degraded = [preflight.Finding(Severity.DEGRADED, "w", "c", "f")]
    critical = [preflight.Finding(Severity.CRITICAL, "rubric is the example's", "fiction", "run /setup")]
    assert preflight.worklist_banner(degraded) is None
    banner = preflight.worklist_banner(critical)
    assert banner and banner.startswith(">") and "not be about you" in banner


def test_summary_line_counts_by_severity():
    findings = [
        preflight.Finding(Severity.CRITICAL, "a", "b", "c"),
        preflight.Finding(Severity.DEGRADED, "d", "e", "f"),
        preflight.Finding(Severity.DEGRADED, "g", "h", "i"),
    ]
    line = preflight.summary_line(findings)
    assert line == "preflight: 1 critical · 2 degraded"
