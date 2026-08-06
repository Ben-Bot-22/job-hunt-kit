"""The schema over `config/settings.yaml` — the half of the config that is settings.
Run:  .venv/bin/python -m pytest core/test_settings.py -q

Offline, no key, no network: everything here is a dict against a Pydantic model, plus the repo's own
shipped settings file read from disk.

The failure directions, in the order they cost something:

  * **A misspelled key running at the default forever.** This is the live defect the ticket names:
    `max_worker: 12` parsed fine, matched no accessor, and the run stayed at 5 workers with nothing
    printed. Nobody discovers that by reading a log — you discover it when you finally diff your own
    config against the accessor list. Every test below that writes a typo is guarding this.
  * **A validator that fails a run it should not have failed.** The opposite direction and it is the
    one that costs a *morning*: settings load at import of `triage.config`, so an over-strict schema
    doesn't degrade the run, it stops it. Hence a missing file is still `{}`, every key is still
    optional, and the bounds are only where a value outside them is a mistake rather than a taste.
  * **The rubric acquiring a schema by accident.** `profile/rubric.md` is prose and is deliberately
    unvalidated — a rubric edit must never be able to stop the tool booting, which is why it left
    YAML in 06. Asserted here as well as in `triage/test_config.py`, from the schema's side.
  * **The published schema drifting from the model.** `config/settings.schema.json` is the artifact an
    agent reads to know what it may edit. A stale one is worse than none: it invites an edit the
    loader then rejects, or blesses a key that no longer exists.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "`config/settings.yaml` is schema-validated on load, so a misspelled key names itself instead of silently defaulting."
import json

import pytest

from .settings import (CHANNEL_NAMES, DEFAULT_MODELS, SCHEMA_PATH, SETTINGS_PATH, ConfigurationError,
                       Settings, model,
                       load, schema_json, settings, validate)


# --------------------------------------------------------------------------------------------------
# The shipped file
# --------------------------------------------------------------------------------------------------

def test_the_repos_own_settings_file_validates() -> None:
    """The first thing a schema must not do is reject the config the tool ships with."""
    assert validate(load(SETTINGS_PATH)) == load(SETTINGS_PATH)


def test_validation_returns_the_plain_dict_untouched() -> None:
    """Accessors speak dict-with-a-default and keep doing so; validation is a gate, not a rewrite.

    Failure direction: returning the *model* would silently drop every key the schema doesn't name,
    so a Stage 5 report key added to the YAML but not to the model would read as absent — the exact
    silent-default bug, reintroduced by the fix for it.
    """
    raw = {"max_workers": 7, "channels": {"mail": {"enabled": False}}}
    out = validate(raw)
    assert out is raw and out["channels"]["mail"]["enabled"] is False


def test_a_missing_settings_file_is_still_not_an_error() -> None:
    """A fresh clone with a key exported runs. `{}` validates; the accessors supply the defaults."""
    assert validate({}) == {}


# --------------------------------------------------------------------------------------------------
# A typo fails loudly, and the message names the key
# --------------------------------------------------------------------------------------------------

def test_a_misspelled_key_raises_rather_than_silently_defaulting() -> None:
    """**The live defect.** `max_worker: 12` used to run at 5 forever with no error at all."""
    with pytest.raises(ConfigurationError) as e:
        validate({"max_worker": 12})
    assert "max_worker" in str(e.value)
    assert "Did you mean `max_workers`?" in str(e.value)


@pytest.mark.parametrize("bad, key", [
    ({"models": {"analyse": "claude-opus-4-8"}}, "models.analyse"),
    ({"liveness": {"worker": 8}}, "liveness.worker"),
    ({"dedup": {"min_jd_char": 500}}, "dedup.min_jd_char"),
    ({"channels": {"mial": {"enabled": True}}}, "channels.mial"),
    ({"channels": {"boards": {"greenhosue": ["anthropic"]}}}, "channels.boards.greenhosue"),
    ({"llm": {"provdier": "openai"}}, "llm.provdier"),
])
def test_a_misspelling_at_any_depth_names_its_full_path(bad: dict, key: str) -> None:
    """Nesting is where a typo hides best: the block parses, so YAML is happy and the value is orphaned.

    The full dotted path is in the message because "unknown setting: worker" sends you looking in the
    wrong block — there is a `workers` under `liveness` and there was nearly one everywhere else.
    """
    with pytest.raises(ConfigurationError, match=key.replace(".", r"\.")):
        validate(bad)


def test_every_wrong_key_is_reported_at_once() -> None:
    """Fix-one-rerun is how a config edit turns into six runs. Pydantic collects; so does the message."""
    with pytest.raises(ConfigurationError) as e:
        validate({"max_worker": 12, "window_dais": 3})
    assert "max_worker" in str(e.value) and "window_dais" in str(e.value)


def test_the_error_points_at_the_file_and_at_the_schema() -> None:
    """A stranger's typo has to read as their typo, at a path they can open."""
    with pytest.raises(ConfigurationError) as e:
        validate({"nonsense": 1})
    assert str(SETTINGS_PATH) in str(e.value) and str(SCHEMA_PATH) in str(e.value)


# --------------------------------------------------------------------------------------------------
# Wrong type, wrong range
# --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad, key", [
    ({"max_workers": 0}, "max_workers"),            # a pool of nothing; the accessor would clamp to 1
    ({"max_workers": 500}, "max_workers"),          # 500 concurrent calls is a rate-limit ban
    ({"max_workers": "twelve"}, "max_workers"),
    ({"window_days": 0}, "window_days"),            # a zero-day window is a run that finds nothing
    ({"dedup": {"similarity": 1.5}}, "dedup.similarity"),   # a cosine is bounded: 1.5 collapses nothing
    ({"dedup": {"overlap": -0.1}}, "dedup.overlap"),        # ...and -0.1 collapses everything
    ({"precedent": {"k": 400}}, "precedent.k"),     # k is the per-job token bill
    ({"liveness": {"max_check": -1}}, "liveness.max_check"),
    ({"prefilter": {"enabled": "yes please"}}, "prefilter.enabled"),
    ({"channels": {"mail": {"enabled": "sometimes"}}}, "channels.mail.enabled"),
    ({"channels": {"boards": {"greenhouse": "anthropic"}}}, "channels.boards.greenhouse"),
])
def test_an_out_of_range_or_wrong_typed_value_fails_loudly(bad: dict, key: str) -> None:
    """The bounds are where a value outside them is a *mistake*, not a preference.

    `similarity: 1.5` is the one worth reading twice: it is a cosine, so nothing can ever clear it and
    dedup silently stops collapsing anything. That reads exactly like a quiet week of unique postings.
    """
    with pytest.raises(ConfigurationError, match=key.replace(".", r"\.")):
        validate(bad)


@pytest.mark.parametrize("ok", [
    {"max_workers": 1}, {"max_workers": 64}, {"window_days": 365},
    {"dedup": {"similarity": 0.0}}, {"dedup": {"overlap": 1.0}},
    {"precedent": {"k": 0}}, {"liveness": {"max_check": 0}},
    {"channels": {"boards": {"greenhouse": [], "lever": ["brex"]}}},
])
def test_the_edges_of_every_range_are_allowed(ok: dict) -> None:
    """The bounds are inclusive. `max_check: 0` means "check none" and `k: 0` means "no precedent" —
    both are documented ways to turn a feature off, and a schema that rejected them would take away a
    switch the comments in `config/settings.yaml` tell you to use."""
    assert validate(ok) == ok


def test_the_provider_name_is_not_constrained_here() -> None:
    """`core/llm.py` owns the provider registry and its error already names every provider and tier.

    Two lists of provider names would drift, and the schema's version would be the one that goes stale
    — so an unknown provider is a `core/llm.py` error, not a schema error.
    """
    assert validate({"llm": {"provider": "something-new"}}) == {"llm": {"provider": "something-new"}}


# --------------------------------------------------------------------------------------------------
# What is deliberately NOT validated
# --------------------------------------------------------------------------------------------------

def test_the_schema_covers_the_operational_half_and_nothing_else() -> None:
    """The rubric gets no schema, and neither does identity — the deliberate line from the spec.

    Validating prose is a category error and this repo has the receipt: two rubrics existed and the
    *structured* one was the dead one, saying "cast a wide net, relocation OK" while the live prose
    rubric said "remote only, contract first". Identity is left alone for a smaller reason: its
    accessors default to empty, so a missing key there costs a blank field, not a wrong number.
    """
    top = set(Settings.model_fields)
    assert "goal_profile" not in top and "rubric" not in top
    assert not top & {"inbox", "archive_mailbox", "applied_sheet",
                      "primary_agencies", "secondary_platforms"}


# --------------------------------------------------------------------------------------------------
# The generated schema — the artifact an agent reads
# --------------------------------------------------------------------------------------------------

def test_the_published_schema_is_in_sync_with_the_model() -> None:
    """A stale schema is worse than none: it blesses an edit the loader then rejects.

    Regenerate with `python -m core.settings`.
    """
    assert SCHEMA_PATH.exists()
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_json(), (
        "config/settings.schema.json is stale — run `python -m core.settings`")


def test_the_published_schema_is_readable_json_schema_and_forbids_unknown_keys() -> None:
    """The agent-editable boundary is a file, so the file has to say the two things that matter:
    what the keys are, and that anything else is an error."""
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert doc["$schema"].startswith("https://json-schema.org/")
    assert doc["additionalProperties"] is False
    assert set(doc["properties"]) == set(Settings.model_fields)
    assert "profile/rubric.md" in doc["description"]      # the boundary, stated where an agent reads it


def test_the_settings_file_points_an_editor_at_the_schema() -> None:
    """`# yaml-language-server: $schema=` is the convention every YAML LSP reads, so the typo is
    underlined in the editor before it is ever an error at runtime."""
    assert "# yaml-language-server: $schema=./settings.schema.json" in SETTINGS_PATH.read_text()


def test_the_channel_names_are_pinned() -> None:
    """The four registered channels. `triage/test_channels.py` asserts these match the live registry —
    here so that `core/` alone still fails if one is quietly dropped from the schema."""
    assert CHANNEL_NAMES == ("mail", "boards", "agencies", "paste", "gmail")


# --------------------------------------------------------------------------------------------------
# Which model each role runs on — owned by the code, stated once
# --------------------------------------------------------------------------------------------------

def test_every_role_has_a_default_so_no_settings_file_has_to_name_one() -> None:
    """`model()` was the ONE accessor with no fallback, and that is what made the duplication.

    Every other accessor carries `cfg().get(key, default)`, so a settings file may stay silent about
    anything it does not care about. `models` could not: `cfg()["models"][role]` raised, so every
    settings file had to spell all five ids out — which meant `config/example/settings.yaml` held a
    second copy of them, kept in step by a human reading a diff. On 2026-07-29 the owner moved
    `analyze` to Sonnet on cost and the example was not touched, so for two weeks every new user's
    default was an older, more expensive model nobody had chosen, and the only thing watching was a
    manual step in the publish checklist.
    """
    from .settings import ModelSettings
    # Iterated off the SCHEMA, not off DEFAULT_MODELS: iterating the dict against itself would pass
    # for a role added to `ModelSettings` and forgotten here, which then raises KeyError on the first
    # real call. The two sets must stay equal, and this is the assertion that says so.
    assert set(DEFAULT_MODELS) == set(ModelSettings.model_fields)
    for role in ModelSettings.model_fields:
        assert model(role), f"{role} has no default"


def test_an_unknown_role_says_so_rather_than_raising_a_bare_keyerror() -> None:
    """The roles are a fixed set in the code, never user input, so a miss here is a typo in a call."""
    with pytest.raises(KeyError, match="unknown model role"):
        model("analyse")


def test_a_settings_file_still_overrides_the_default(monkeypatch) -> None:
    """The default is a starting point, not a policy. Switching provider is still one file."""
    monkeypatch.setattr("core.settings.settings", lambda: {"models": {"analyze": "gpt-5"}})
    assert model("analyze") == "gpt-5"
    assert model("prefilter") == DEFAULT_MODELS["prefilter"]   # untouched roles keep the default
