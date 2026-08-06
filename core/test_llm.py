"""Tests for the single generation path — selection, and the error a stranger's first run produces.

Everything here runs **offline with no key and no provider package**: the two facts worth pinning are
"the provider you configured is the one you got" and "a missing key reads as config, not as a stack
trace", and neither needs a model. Selection is exercised over a *fake* registry, so these tests
don't quietly become a test of whether `langchain-openai` happens to be installed.

The one place a real client is built — that `method="json_schema"` reaches Anthropic's native
structured outputs byte-for-byte — is already pinned by `core/test_structured_output.py` against a
mock transport. It is not re-tested here.

Run:  .venv/bin/python -m pytest core/test_llm.py -q
"""
from __future__ import annotations

import pytest

from . import llm
from .llm import ConfigurationError, Provider
from .settings import load

# --- a registry with no packages and no network behind it ---------------------------------------------


def _recording_build(seen: list[dict]):
    def build(**kw):
        seen.append(kw)
        return _FakeChatModel(kw)
    return build


class _FakeChatModel:
    """Just enough of a chat model to observe what `structured()` binds."""

    def __init__(self, kw: dict):
        self.kw = kw
        self.bound: tuple | None = None

    def with_structured_output(self, schema, method):
        self.bound = (schema, method)
        return self


def _registry(seen: list[dict]) -> dict[str, Provider]:
    build = _recording_build(seen)
    return {
        "alpha": Provider(name="alpha", package="fake-alpha", build=build,
                          env_var="ALPHA_KEY", supports_thinking=True, supports_effort=True,
                          tier="tested"),
        "beta": Provider(name="beta", package="fake-beta", build=build,
                         env_var="BETA_KEY", structured_method="json_mode"),
        "local": Provider(name="local", package="fake-local", build=build, env_var=None),
    }


# --- selection ----------------------------------------------------------------------------------------

def test_the_configured_provider_is_the_one_selected(monkeypatch) -> None:
    """The whole capability in one assertion: the config value picks the vendor.

    Failure direction: a default that wins over the configured value means a stranger edits
    `llm.provider`, sees nothing change, and concludes the tool is Anthropic-only after all.
    """
    seen: list[dict] = []
    monkeypatch.setenv("BETA_KEY", "k")
    llm.chat_model("some-model", max_tokens=100,
                   config={"llm": {"provider": "beta"}}, registry=_registry(seen))
    assert llm.resolve_provider({"llm": {"provider": "beta"}}, _registry(seen)).name == "beta"
    assert seen[0]["model"] == "some-model" and seen[0]["api_key"] == "k"


def test_the_default_provider_is_anthropic(monkeypatch) -> None:
    """No `llm:` section at all — a fresh clone with only ANTHROPIC_API_KEY keeps working."""
    monkeypatch.setenv("ALPHA_KEY", "k")
    reg = _registry([])
    reg["anthropic"] = reg.pop("alpha")
    assert llm.resolve_provider({}, reg).name == "alpha"      # `name` is the spec's, not the key's


def test_an_unknown_provider_names_the_ones_that_exist() -> None:
    """A typo in `llm.provider` must not read as "this tool is broken"."""
    with pytest.raises(ConfigurationError) as e:
        llm.resolve_provider({"llm": {"provider": "antropic"}}, _registry([]))
    assert "antropic" in str(e.value)
    assert "alpha (tested)" in str(e.value) and "beta (untested)" in str(e.value)


def test_the_shipped_settings_file_names_a_real_provider() -> None:
    """`config/settings.yaml` is the file a stranger edits first; it must load and resolve.

    Failure direction: a bad indent or a renamed provider ships green because every other test here
    passes its config in by hand.
    """
    assert llm.SETTINGS_PATH.exists(), f"{llm.SETTINGS_PATH} is the documented config surface"
    assert llm.resolve_provider(load(llm.SETTINGS_PATH)).name in llm.PROVIDERS


# --- the missing key ----------------------------------------------------------------------------------

def test_a_missing_key_is_a_configuration_error_naming_what_is_missing(monkeypatch) -> None:
    """The stranger's first run. Failure direction: an SDK traceback they can't attribute to their
    own config, three frames deep in a library they didn't choose."""
    monkeypatch.delenv("BETA_KEY", raising=False)
    monkeypatch.setattr(llm, "REPO_ROOT", llm.REPO_ROOT / "no-such-dir")   # no .env to rescue it
    with pytest.raises(ConfigurationError) as e:
        llm.chat_model("m", max_tokens=10, config={"llm": {"provider": "beta"}}, registry=_registry([]))
    msg = str(e.value)
    assert "beta" in msg and "BETA_KEY" in msg, "the error must name the provider AND the variable"
    assert ".env" in msg, "and where to put it"


def test_a_keyless_provider_needs_no_key(monkeypatch) -> None:
    """A local model is the case where "no key" is the correct configuration, not a missing one."""
    monkeypatch.delenv("ALPHA_KEY", raising=False)
    seen: list[dict] = []
    llm.chat_model("llama3", max_tokens=10,
                   config={"llm": {"provider": "local", "base_url": "http://localhost:11434"}},
                   registry=_registry(seen))
    assert seen[0]["api_key"] is None and seen[0]["base_url"] == "http://localhost:11434"


def test_a_missing_package_is_a_configuration_error_too() -> None:
    """The other half of a stranger's first run: the provider is real, the package isn't installed.

    Exercised through the real registry, because the point is that the *real* factories raise
    `ConfigurationError` rather than `ImportError`. Skips if the package happens to be present.
    """
    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("langchain-openai is installed, so there is no missing-package path to see")
    with pytest.raises(ConfigurationError) as e:
        llm.PROVIDERS["openai"].build(model="gpt", api_key="k", max_tokens=10,
                                      base_url=None, thinking=None, effort=None)
    assert "pip install langchain-openai" in str(e.value)


# --- what the path binds ------------------------------------------------------------------------------

def test_structured_binds_the_provider_s_method(monkeypatch) -> None:
    """`method="json_schema"` is load-bearing and is NOT the library default.

    Failure direction, and it is the trap the spike existed to find: the default binds the schema as
    a forced tool, and the forcing is silently dropped when thinking is on — so `analyze.py` would
    park real jobs in "Rejected / skipped" intermittently, with no diff to point at. Fixing it here
    means no call site can forget it.
    """
    monkeypatch.setenv("ALPHA_KEY", "k")
    seen: list[dict] = []
    bound = llm.structured(dict, "m", max_tokens=10, thinking=llm.THINKING_ADAPTIVE,
                           config={"llm": {"provider": "alpha"}}, registry=_registry(seen))
    assert bound.bound == (dict, "json_schema")
    assert seen[0]["thinking"] == {"type": "adaptive"}


def test_the_structured_method_is_overridable_from_config(monkeypatch) -> None:
    """An untested provider that spells it differently is a config edit, not a patch."""
    monkeypatch.setenv("BETA_KEY", "k")
    bound = llm.structured(dict, "m", max_tokens=10,
                           config={"llm": {"provider": "beta"}}, registry=_registry([]))
    assert bound.bound == (dict, "json_mode")     # from the provider spec
    bound = llm.structured(dict, "m", max_tokens=10,
                           config={"llm": {"provider": "beta", "structured_method": "function_calling"}},
                           registry=_registry([]))
    assert bound.bound == (dict, "function_calling")


def test_thinking_is_dropped_for_a_provider_that_does_not_support_it(monkeypatch) -> None:
    """Anthropic's extended thinking is Anthropic's. Forwarding it is a TypeError on someone's first
    run of a provider they were told was untested-but-should-work — dropping it is merely different."""
    monkeypatch.setenv("BETA_KEY", "k")
    seen: list[dict] = []
    llm.chat_model("m", max_tokens=10, thinking=llm.THINKING_ADAPTIVE,
                   config={"llm": {"provider": "beta"}}, registry=_registry(seen))
    assert seen[0]["thinking"] is None


def test_effort_reaches_the_client_from_settings(monkeypatch) -> None:
    """`llm.effort` is the dominant cost lever — billing is output-token dominated and effort sets
    output length. Call sites never pass it, so a value that stops arriving is a silent bill increase
    with no other symptom: the run still works, it just costs what it used to."""
    monkeypatch.setenv("ALPHA_KEY", "k")
    seen: list[dict] = []
    llm.chat_model("m", max_tokens=10,
                   config={"llm": {"provider": "alpha", "effort": "medium"}}, registry=_registry(seen))
    assert seen[0]["effort"] == "medium"


def test_effort_is_dropped_for_a_provider_that_does_not_support_it(monkeypatch) -> None:
    """Same reasoning as `thinking` above: effort is Anthropic's `output_config.effort`, and
    forwarding it to a provider that doesn't take it is a TypeError on a stranger's first run."""
    monkeypatch.setenv("BETA_KEY", "k")
    seen: list[dict] = []
    llm.chat_model("m", max_tokens=10,
                   config={"llm": {"provider": "beta", "effort": "medium"}}, registry=_registry(seen))
    assert seen[0]["effort"] is None


def test_unset_effort_leaves_the_provider_default(monkeypatch) -> None:
    """Omitting the key must mean 'the provider decides', not 'low'. A default invented here would
    silently re-tune every install that never opted in."""
    monkeypatch.setenv("ALPHA_KEY", "k")
    seen: list[dict] = []
    llm.chat_model("m", max_tokens=10, config={"llm": {"provider": "alpha"}}, registry=_registry(seen))
    assert seen[0]["effort"] is None


def test_the_real_anthropic_factory_takes_reasoning_effort(monkeypatch) -> None:
    """The fake registry can't catch a misspelled kwarg. `reasoning_effort` is langchain-anthropic's
    field name for `output_config.effort`; if a version bump renames it, the cost lever silently
    stops working on the one provider anything was measured on."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-used")
    model = llm.chat_model("claude-sonnet-5", max_tokens=8000, thinking=llm.THINKING_ADAPTIVE,
                           config={"llm": {"provider": "anthropic", "effort": "medium"}})
    assert model.reasoning_effort == "medium"


def test_the_real_anthropic_factory_builds_the_call_analyze_py_makes(monkeypatch) -> None:
    """The fake registry can't catch a misspelled kwarg. This one does, without a key or a request.

    Failure direction: `max_tokens` or `thinking` renamed in a `langchain-anthropic` bump, so the
    tested provider — the only one anything was measured on — raises on the first real run.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-used")
    model = llm.chat_model("claude-opus-4-8", max_tokens=8000, thinking=llm.THINKING_ADAPTIVE,
                           config={"llm": {"provider": "anthropic"}})
    assert (model.model, model.max_tokens, model.thinking, model.max_retries) == (
        "claude-opus-4-8", 8000, {"type": "adaptive"}, 2)


def test_retry_is_ported_not_reinvented() -> None:
    """The SDK has always retried twice with backoff; that is what the call sites are losing when
    they stop constructing their own client. Pinned so a library default can't move it — and so
    nobody stacks `with_retry()` on top, which would quadruple a rate-limited call."""
    import anthropic
    assert llm.MAX_RETRIES == anthropic._constants.DEFAULT_MAX_RETRIES


def test_importing_the_module_does_not_enable_tracing() -> None:
    """LangSmith ships inputs, outputs and metadata unredacted by default — here the resume, the
    inbox-derived job data and the goal profile. It is dormant unless switched on, and importing the
    generation path must never be what switches it on."""
    import os
    assert os.environ.get("LANGSMITH_TRACING", "false").lower() in ("false", "0", "")
