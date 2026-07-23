"""The single generation path. One module builds every model client, for whichever provider is configured.

Before this file, every LLM call in the pipeline reached for `anthropic.Anthropic` directly —
`triage/config.py:client()`, `research/agent.py:_client()`, and the frozen pipeline's scorer. That is why the tool
simply did not run for a stranger holding an OpenAI key or a local model: the provider was spelled
into the code four times. Here it is one value in `config/settings.yaml`.

The other half of the point is negative, and it is the reason `core/` exists at all: **there must
never be two generation paths.** Stage 2 put LangChain in the tree for retrieval. A second, native
path alongside it would mean every prompt, retry and failure mode maintained twice and drifting
apart. So this module is a *file* that owns generation, not a promise that someone will remember.

The promise is **tiered honestly**, the same way it is for agents and for input channels:

  * **anthropic — tested.** Every measurement in this repo was taken on it, and
    `core/test_structured_output.py` pins its request byte-for-byte against the native SDK call it
    replaced.
  * **openai, google, ollama — untested, should work.** They are registered, they take a key (or
    none, for a local model), and nothing about them has been run. What specifically does *not*
    transfer is the equivalence argument: `method="json_schema"` reaches Anthropic's own structured
    outputs, while elsewhere it is LangChain's translation of the same schema, and no claim is made
    that the two produce the same judgment. See `docs/research/structured-output-spike.md`.

**`method="json_schema"` is load-bearing and is not the library's default.** The default
(`function_calling`) binds the schema as a tool, which re-orders the prompt — and under
`thinking`, the forcing is silently dropped, so the model is merely *invited* to call the tool and a
job that declines lands in "Rejected / skipped" for a reason that has nothing to do with the job.
That is exactly the kind of thing a call site forgets, which is why the keyword lives here and the
call sites never pass it.

**Retry is ported, not reinvented.** `anthropic.Anthropic()` retries twice with backoff on
408/409/429/5xx, and that is what the current call sites have always had. `MAX_RETRIES` below pins
the same 2 explicitly rather than inheriting a library default that could move. Nothing is wrapped in
LangChain's `with_retry()` — that would stack a second retry loop on top of the SDK's and quadruple a
rate-limited call. The *failure* handling stays where it already is: each call site catches and
returns its own fallback (keep the job / empty list / verdict=SKIP), because the right fallback is a
property of the call site, not of the model.

Nothing here reads `triage.config` — `core/` imports nothing local (see `core/__init__.py`).
Model ids stay with the caller, because they are provider-specific strings — but since stage 4's
config split they sit under `models:` in the same `config/settings.yaml` as `llm.provider`, so
switching vendor is one file rather than two.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .settings import REPO_ROOT, SETTINGS_PATH, ConfigurationError, load, settings

log = logging.getLogger("core.llm")

# Taken from `settings.py` rather than derived from `SETTINGS_PATH`, which no longer sits two levels
# below the root when `JOBSDB_CONFIG_HOME` points the config elsewhere. The key lives in the repo's
# own `.env` whichever configuration is loaded: a config home is not a secrets home.

# LangSmith arrives as a transitive dependency of langchain-core and is **dormant** — it traces only
# when `LANGSMITH_TRACING` is truthy. It must stay dormant: when on it ships inputs, outputs and
# metadata *unredacted by default*, which here means the resume, inbox-derived job data and the goal
# profile. `setdefault` rather than a hard set, so someone who deliberately exports it still gets
# what they asked for — but importing this module never turns it on.
os.environ.setdefault("LANGSMITH_TRACING", "false")

# What `anthropic.Anthropic()` has always done, made explicit so a library default can't move it.
MAX_RETRIES = 2

# Anthropic's extended thinking, as `triage/analyze.py` and `research/agent.py` already pass it.
# Dropped for providers that don't declare support rather than forwarded into a TypeError.
THINKING_ADAPTIVE: dict[str, str] = {"type": "adaptive"}


# --------------------------------------------------------------------------------------------------
# The provider registry
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    """One provider: the key it needs, the package that supplies it, and how it takes a schema.

    `build` is a callable rather than an import path so the registry can be faked whole in a test —
    the selection logic is then exercised with no provider package installed and no key anywhere.
    """
    name: str
    package: str                      # pip install <this> — named in the error when it's missing
    build: Callable[..., Any]         # (model, api_key, max_tokens, base_url, thinking) -> chat model
    env_var: str | None = None        # None = needs no key (a local model)
    structured_method: str = "json_schema"
    supports_thinking: bool = False
    tier: str = "untested"


def _missing(package: str, provider: str, exc: ImportError) -> ConfigurationError:
    return ConfigurationError(
        f"LLM provider '{provider}' needs the '{package}' package, which is not installed.\n"
        f"  pip install {package}\n"
        f"(original import error: {exc})"
    )


def _anthropic(*, model: str, api_key: str | None, max_tokens: int,
               base_url: str | None, thinking: dict | None) -> Any:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise _missing("langchain-anthropic", "anthropic", e) from e
    kw: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "max_retries": MAX_RETRIES}
    if api_key:
        kw["api_key"] = api_key
    if base_url:
        kw["base_url"] = base_url
    if thinking:
        kw["thinking"] = thinking
    return ChatAnthropic(**kw)


def _openai(*, model: str, api_key: str | None, max_tokens: int,
            base_url: str | None, thinking: dict | None) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise _missing("langchain-openai", "openai", e) from e
    kw: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "max_retries": MAX_RETRIES}
    if api_key:
        kw["api_key"] = api_key
    if base_url:
        kw["base_url"] = base_url     # also the door for any OpenAI-compatible local server
    return ChatOpenAI(**kw)


def _google(*, model: str, api_key: str | None, max_tokens: int,
            base_url: str | None, thinking: dict | None) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise _missing("langchain-google-genai", "google", e) from e
    kw: dict[str, Any] = {"model": model, "max_output_tokens": max_tokens, "max_retries": MAX_RETRIES}
    if api_key:
        kw["google_api_key"] = api_key
    return ChatGoogleGenerativeAI(**kw)


def _ollama(*, model: str, api_key: str | None, max_tokens: int,
            base_url: str | None, thinking: dict | None) -> Any:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise _missing("langchain-ollama", "ollama", e) from e
    kw: dict[str, Any] = {"model": model, "num_predict": max_tokens}
    if base_url:
        kw["base_url"] = base_url
    return ChatOllama(**kw)


# `tier` is the honest half of the promise and is printed in the error a stranger sees, so the README
# and the code cannot drift on which providers have actually been run.
PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        name="anthropic", package="langchain-anthropic", build=_anthropic,
        env_var="ANTHROPIC_API_KEY", supports_thinking=True, tier="tested"),
    "openai": Provider(
        name="openai", package="langchain-openai", build=_openai,
        env_var="OPENAI_API_KEY"),
    "google": Provider(
        name="google", package="langchain-google-genai", build=_google,
        env_var="GOOGLE_API_KEY"),
    # A local model: no key, and `llm.base_url` in settings points at the server. This is the row that
    # makes "no job data leaves my machine" a config edit rather than a fork.
    "ollama": Provider(
        name="ollama", package="langchain-ollama", build=_ollama, env_var=None),
}


def provider_catalogue(registry: Mapping[str, Provider] | None = None) -> str:
    """`anthropic (tested), google (untested), ...` — the line every configuration error ends with."""
    reg = PROVIDERS if registry is None else registry
    return ", ".join(f"{n} ({p.tier})" for n, p in sorted(reg.items()))


# --------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------

def _llm_settings(override: Mapping[str, Any] | None) -> dict:
    section = (settings() if override is None else override).get("llm") or {}
    if not isinstance(section, dict):
        raise ConfigurationError(f"`llm:` in {SETTINGS_PATH} must be a mapping, not a {type(section).__name__}")
    return section


def resolve_provider(config: Mapping[str, Any] | None = None,
                     registry: Mapping[str, Provider] | None = None) -> Provider:
    """The configured provider, or a configuration error naming the ones that exist."""
    reg = PROVIDERS if registry is None else registry
    name = str(_llm_settings(config).get("provider") or "anthropic").strip().lower()
    if name not in reg:
        raise ConfigurationError(
            f"Unknown LLM provider '{name}'.\n"
            f"Set `llm.provider` in {SETTINGS_PATH} to one of: {provider_catalogue(reg)}"
        )
    return reg[name]


def api_key_for(provider: Provider) -> str | None:
    """The provider's key from the environment (repo-root `.env` included), or a clear error.

    `.env` is read here rather than at import so that constructing nothing costs nothing, and so the
    file is re-read if a caller writes it mid-process. `python-dotenv` never overrides an already
    exported variable, so an exported key still wins.
    """
    if provider.env_var is None:
        return None
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:      # optional — an exported key works fine without it
        pass
    key = os.getenv(provider.env_var)
    if not key:
        raise ConfigurationError(
            f"LLM provider '{provider.name}' is configured, but {provider.env_var} is not set.\n"
            f"  Put it in {REPO_ROOT / '.env'} as `{provider.env_var}=...`, or export it.\n"
            f"  Or change `llm.provider` in {SETTINGS_PATH} to a provider whose key you have: "
            f"{provider_catalogue()}"
        )
    return key


# --------------------------------------------------------------------------------------------------
# The generation path
# --------------------------------------------------------------------------------------------------

def chat_model(model: str, *, max_tokens: int, thinking: dict | None = None,
               config: Mapping[str, Any] | None = None,
               registry: Mapping[str, Provider] | None = None) -> Any:
    """A chat model from the configured provider. The only place a model client is constructed.

    `model` is the caller's — model ids are provider-specific strings and live under `models:` in
    `config/settings.yaml`, next to the provider they belong to.
    `thinking` is Anthropic's extended thinking; it is dropped (with a warning) on a provider that
    doesn't declare support, because forwarding it would be a TypeError on the stranger's first run.
    """
    provider = resolve_provider(config, registry)
    llm_cfg = _llm_settings(config)
    if thinking and not provider.supports_thinking:
        log.warning("provider %r does not support `thinking` — dropping it", provider.name)
        thinking = None
    return provider.build(
        model=model,
        api_key=api_key_for(provider),
        max_tokens=max_tokens,
        base_url=(llm_cfg.get("base_url") or None),
        thinking=thinking,
    )


def structured(schema: type, model: str, *, max_tokens: int, thinking: dict | None = None,
               config: Mapping[str, Any] | None = None,
               registry: Mapping[str, Provider] | None = None) -> Any:
    """A runnable that returns a validated `schema` instance. **This is what call sites use.**

    The structured-output method is fixed here on purpose. For Anthropic, `json_schema` binds
    `output_config.format` — the native structured-output feature the pipeline already used, so the
    request is byte-identical to the `messages.parse` call it replaced (`core/test_structured_output.py`).
    Leaving the choice to call sites is how one of them quietly ends up on the default and starts
    sending a different prompt.

    Failure shape, and it differs from what the old call sites saw: native `messages.parse` returned
    `parsed_output=None` on a refusal, while this raises `OutputParserException`. It subclasses
    `Exception`, so the existing `except Exception` fallbacks still fire — but a migrated call site
    that only checks `is None` would sail straight past it.
    """
    provider = resolve_provider(config, registry)
    method = str(_llm_settings(config).get("structured_method") or provider.structured_method)
    llm = chat_model(model, max_tokens=max_tokens, thinking=thinking, config=config, registry=registry)
    return llm.with_structured_output(schema, method=method)
