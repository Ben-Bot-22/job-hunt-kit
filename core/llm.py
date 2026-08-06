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
    that the two produce the same judgment. See `docs/knowledge-base/research-structured-output.md`.

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

import json
import logging
import os
import shutil
import subprocess
import tempfile
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

# How long one `claude -p` call may take. Measured 2026-08-03: ~9 s for an analyze-shaped call, ~16 s
# for the slowest of eight run concurrently. Generous, because the cost of being wrong is asymmetric —
# a timeout is a lost judgment (the job lands in "Rejected / skipped"), a long wait is just a slow run.
CLI_TIMEOUT_S = 300


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
    build: Callable[..., Any]         # (model, api_key, max_tokens, base_url, thinking, effort) -> chat model
    env_var: str | None = None        # None = needs no key (a local model)
    structured_method: str = "json_schema"
    supports_thinking: bool = False
    supports_effort: bool = False
    tier: str = "untested"


def _missing(package: str, provider: str, exc: ImportError) -> ConfigurationError:
    return ConfigurationError(
        f"LLM provider '{provider}' needs the '{package}' package, which is not installed.\n"
        f"  pip install {package}\n"
        f"(original import error: {exc})"
    )


def _anthropic(*, model: str, api_key: str | None, max_tokens: int,
               base_url: str | None, thinking: dict | None, effort: str | None) -> Any:
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
    if effort:
        # `reasoning_effort` is langchain-anthropic's first-class field for `output_config.effort`
        # (Literal low|medium|high|xhigh|max), so this needs no `model_kwargs` passthrough.
        kw["reasoning_effort"] = effort
    return ChatAnthropic(**kw)


def _openai(*, model: str, api_key: str | None, max_tokens: int,
            base_url: str | None, thinking: dict | None, effort: str | None) -> Any:
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
            base_url: str | None, thinking: dict | None, effort: str | None) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise _missing("langchain-google-genai", "google", e) from e
    kw: dict[str, Any] = {"model": model, "max_output_tokens": max_tokens, "max_retries": MAX_RETRIES}
    if api_key:
        kw["google_api_key"] = api_key
    return ChatGoogleGenerativeAI(**kw)


def _ollama(*, model: str, api_key: str | None, max_tokens: int,
            base_url: str | None, thinking: dict | None, effort: str | None) -> Any:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise _missing("langchain-ollama", "ollama", e) from e
    kw: dict[str, Any] = {"model": model, "num_predict": max_tokens}
    if base_url:
        kw["base_url"] = base_url
    return ChatOllama(**kw)


# --------------------------------------------------------------------------------------------------
# claude_cli — the same generation, paid for by a Claude Code subscription instead of an API key
#
# THE WHOLE POINT IS THAT ONLY THE TRANSPORT CHANGES. Same prompt, same schema, same fallbacks: the
# call site cannot tell which one it is talking to, because the two things that made the API path
# trustworthy both survive the move, and both were measured rather than assumed (2026-08-03):
#
#   * NATIVE STRUCTURED OUTPUT. `claude -p --json-schema` reaches the same feature `method=
#     "json_schema"` does, and the envelope carries a parsed `structured_output` object — so this is
#     not JSON scraped out of prose, and `docs/knowledge-base/research-structured-output.md` still
#     describes what happens on the wire.
#   * THE PROMPT CACHE SURVIVES. A fresh process per job sounds like it would re-bill the rubric every
#     time. It does not: the cache is keyed on prompt CONTENT, not on a session, so the second and
#     every later call in a run reported `cache_read_input_tokens: 9525` against a 385-token write.
#     That is the same economics `analyze.py`'s `cache_control` marker buys on the API path.
#
# `--system-prompt` REPLACES Claude Code's own system prompt rather than appending to it, so none of
# its tool schedule or CLAUDE.md is billed — measured input was the rubric plus the JD and nothing
# else. `--tools ""` keeps it that way, and the run happens in a scratch directory so no project
# context can leak in through file discovery.
#
# **Never add `--bare`.** It reads as the lean option and is the exact opposite: its own help says
# auth is then strictly `ANTHROPIC_API_KEY` or `apiKeyHelper`, and OAuth is never read. It would
# silently put every call back on the API bill — the one failure this provider exists to prevent, in
# the one flag most likely to look like an optimisation.
# --------------------------------------------------------------------------------------------------

def _cli_env() -> dict[str, str]:
    """The child's environment, with every Anthropic API credential removed.

    **This function is the provider.** `api_key_for` calls `load_dotenv`, which lifts
    `ANTHROPIC_API_KEY` out of the repo's `.env` and into `os.environ` for the whole process — so by
    the time a run reaches the analyzer, a sibling call site on the `anthropic` provider has usually
    already put the key where a subprocess would inherit it. `claude` prefers an API key over the
    stored OAuth profile, so inheriting one does not fail loudly: it succeeds, bills the API, and
    looks exactly like a working subscription call. Scrubbing is the only thing standing between the
    two, which is why it is here and not left to the caller.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    return env


def _split_messages(messages: Any) -> tuple[str, str]:
    """LangChain-style messages -> (system text, user text).

    Both shapes this repo actually sends are accepted, because both are in the tree today: the tuple
    form with a `cache_control`-carrying block list (`analyze`, `prefilter`, `extract`, the research
    planner) and the plain dict form (`cv_parse`, `cv_review`). The `cache_control` marker is dropped
    rather than translated — the CLI has no flag for it and needs none, since it caches the system
    prompt on its own; see the module comment above for the measurement.
    """
    system: list[str] = []
    user: list[str] = []

    def text_of(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content)
        return str(content)

    for message in messages:
        if isinstance(message, tuple):
            role, content = message
        elif isinstance(message, dict):
            role, content = message.get("role", "user"), message.get("content", "")
        else:                                   # a LangChain message object
            role = getattr(message, "type", None) or getattr(message, "role", "user")
            content = getattr(message, "content", "")
        (system if str(role) in ("system", "developer") else user).append(text_of(content))

    return "\n\n".join(t for t in system if t), "\n\n".join(t for t in user if t)


class _ClaudeCLI:
    """A chat model whose transport is a `claude -p` subprocess. Built only by `_claude_cli` below.

    Mirrors the two methods `core/llm.py` actually uses off a LangChain chat model —
    `with_structured_output(schema, method=...)` and `.invoke(messages)` — and nothing else, so the
    surface stays as small as the thing it stands in for.

    **Failures raise**, deliberately, and that is the contract the call sites were already written
    against: `OutputParserException` on the API path is an `Exception`, every call site catches
    `Exception` and returns its own fallback (keep the job / empty list / verdict=SKIP), and a
    non-zero exit or unparseable envelope here lands in exactly the same branch. In particular
    `analyze.py` sets `analysis_errored`, which keeps a failed job OUT of `seen.json` so tomorrow's
    run scores it again — the right behaviour for a transport that can time out.
    """

    def __init__(self, *, model: str, effort: str | None, schema: type | None = None) -> None:
        self._model = model
        self._effort = effort
        self._schema = schema

    def with_structured_output(self, schema: type, method: str | None = None) -> "_ClaudeCLI":
        # `method` is accepted and ignored: there is one structured-output mode here, and it is the
        # one `json_schema` names on the API path. Rejecting the argument would make this provider
        # fail on a call site that is correct for every other provider.
        return _ClaudeCLI(model=self._model, effort=self._effort, schema=schema)

    def invoke(self, messages: Any) -> Any:
        if self._schema is None:
            raise ConfigurationError(
                "the claude_cli provider is structured-output only — call llm.structured(), not "
                "llm.chat_model(). Nothing in this repo generates free text.")

        binary = shutil.which("claude")
        if not binary:
            raise ConfigurationError(
                "`llm.cli_roles` routes a call through the Claude Code CLI, but `claude` is not on "
                "PATH.\n"
                "  Install it (https://claude.com/claude-code) and sign in with `claude`, or drop "
                f"the role from `llm.cli_roles` in {SETTINGS_PATH} to put it back on the API.")

        system, user = _split_messages(messages)
        cmd = [
            binary, "--print", user,
            "--system-prompt", system,
            "--json-schema", json.dumps(self._schema.model_json_schema()),
            "--output-format", "json",
            "--model", self._model,
            # Everything below trims the child to one stateless generation: no tools, no skills, no
            # settings files, no session written to disk.
            "--tools", "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--setting-sources", "",
        ]
        if self._effort:
            cmd += ["--effort", self._effort]

        try:
            # `cwd` is a scratch directory, not the repo: it is the second half of "no project
            # context leaks in", the first being `--system-prompt` replacing the default prompt.
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_S,
                                  env=_cli_env(), cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"claude CLI did not answer within {CLI_TIMEOUT_S}s") from e

        if done.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {done.returncode}: "
                f"{(done.stderr or done.stdout or '').strip()[:400]}")

        try:
            envelope = json.loads(done.stdout)
        except json.JSONDecodeError as e:
            raise ValueError(f"claude CLI returned no JSON envelope: {done.stdout[:400]}") from e

        if envelope.get("is_error"):
            raise RuntimeError(f"claude CLI reported an error: {str(envelope.get('result'))[:400]}")

        # `structured_output` is the already-parsed object; `result` is its JSON text. Prefer the
        # former and fall back rather than pinning one — this is the one shape owned by the CLI's
        # envelope rather than by us, so it is the one most likely to move underneath this file.
        payload = envelope.get("structured_output")
        if payload is None:
            payload = json.loads(envelope["result"])
        return self._schema(**payload)


def _claude_cli(*, model: str, api_key: str | None, max_tokens: int,
                base_url: str | None, thinking: dict | None, effort: str | None) -> Any:
    # `max_tokens` and `base_url` have no CLI equivalent and are dropped in silence: the first is
    # truncation headroom the CLI manages itself, the second is meaningless for a local binary.
    # `thinking` is dropped too, but is NOT a loss and so does not warn — adaptive thinking is
    # already the default for these models, which is why the CLI exposes no flag for it.
    return _ClaudeCLI(model=model, effort=effort)


# `tier` is the honest half of the promise and is printed in the error a stranger sees, so the README
# and the code cannot drift on which providers have actually been run.
PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        name="anthropic", package="langchain-anthropic", build=_anthropic,
        env_var="ANTHROPIC_API_KEY", supports_thinking=True, supports_effort=True, tier="tested"),
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
    # The Claude Code CLI, billed to a subscription rather than to an API key. `package` names the
    # binary rather than a pip install because that is what the reader has to go get; `env_var=None`
    # because the credential is the CLI's own stored OAuth profile and this repo must never hold it.
    # `supports_thinking` is True and means "passing it is harmless", not "there is a knob" — see
    # `_claude_cli`.
    "claude_cli": Provider(
        name="claude_cli", package="claude (the Claude Code CLI)", build=_claude_cli, env_var=None,
        supports_thinking=True, supports_effort=True, tier="tested"),
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


def cli_roles(config: Mapping[str, Any] | None = None) -> frozenset[str]:
    """The model roles routed through the Claude Code CLI instead of `llm.provider`."""
    raw = _llm_settings(config).get("cli_roles") or []
    if isinstance(raw, str):     # a bare `cli_roles: analyze` reads as one role, not five letters
        raw = [raw]
    return frozenset(str(r).strip() for r in raw if str(r).strip())


def resolve_provider(config: Mapping[str, Any] | None = None,
                     registry: Mapping[str, Provider] | None = None,
                     role: str | None = None) -> Provider:
    """The provider for `role`, or a configuration error naming the ones that exist.

    `role` is the *reason* this is per-role rather than one global switch. Cost is concentrated:
    `analyze` is a minority of the calls and most of the bill, so moving it alone captures most of
    the saving, while leaving the high-volume cheap roles on the API keeps a subscription rate limit
    from being spent on them — and keeps the API path exercised every single run, which is what stops
    it rotting for the stranger who has only that one.
    """
    reg = PROVIDERS if registry is None else registry
    if role and role in cli_roles(config) and "claude_cli" in reg:
        return reg["claude_cli"]
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
               registry: Mapping[str, Provider] | None = None,
               role: str | None = None) -> Any:
    """A chat model from the configured provider. The only place a model client is constructed.

    `model` is the caller's — model ids are provider-specific strings and live under `models:` in
    `config/settings.yaml`, next to the provider they belong to.
    `thinking` is Anthropic's extended thinking; it is dropped (with a warning) on a provider that
    doesn't declare support, because forwarding it would be a TypeError on the stranger's first run.
    """
    provider = resolve_provider(config, registry, role)
    llm_cfg = _llm_settings(config)
    if thinking and not provider.supports_thinking:
        log.warning("provider %r does not support `thinking` — dropping it", provider.name)
        thinking = None
    effort = (llm_cfg.get("effort") or None)
    if effort and not provider.supports_effort:
        log.warning("provider %r does not support `effort` — dropping it", provider.name)
        effort = None
    return provider.build(
        model=model,
        api_key=api_key_for(provider),
        max_tokens=max_tokens,
        base_url=(llm_cfg.get("base_url") or None),
        thinking=thinking,
        effort=effort,
    )


def structured(schema: type, model: str, *, max_tokens: int, thinking: dict | None = None,
               config: Mapping[str, Any] | None = None,
               registry: Mapping[str, Provider] | None = None,
               role: str | None = None) -> Any:
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
    provider = resolve_provider(config, registry, role)
    method = str(_llm_settings(config).get("structured_method") or provider.structured_method)
    llm = chat_model(model, max_tokens=max_tokens, thinking=thinking, config=config,
                     registry=registry, role=role)
    return llm.with_structured_output(schema, method=method)
