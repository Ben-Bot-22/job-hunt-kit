"""The subscription transport: routed per role, and never carrying an API key into the child.

Two things in `core/llm.py`'s `claude_cli` provider are worth a test rather than a docstring, and
they are the two that fail *quietly*:

  * **The env scrub.** `api_key_for` calls `load_dotenv`, so by the time a run reaches the analyzer a
    sibling call site has usually already lifted `ANTHROPIC_API_KEY` into `os.environ`. `claude`
    prefers an API key over its stored login, so a subprocess that inherits one does not error — it
    succeeds, bills the API, and is indistinguishable from a working subscription call. The saving
    silently does not happen. Nothing but this test notices.
  * **The role routing.** `cli_roles: [analyze]` moving *every* role would be the same failure with a
    bigger blast radius: the cheap high-volume roles would start spending a rate limit instead of a
    bill, and the API path would stop being exercised.

Neither test runs the CLI or touches the network — the command is built and inspected. That is
deliberate: the suite ships, and a stranger's clone has no `claude` binary and no subscription.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "A role routed to the Claude Code CLI bills the subscription: no API key reaches the subprocess."

import os
from unittest import mock

import pytest
from pydantic import BaseModel

from core import llm


class _Schema(BaseModel):
    verdict: str


# --------------------------------------------------------------------------------------------------
# The env scrub — the one that fails by succeeding
# --------------------------------------------------------------------------------------------------

def test_no_anthropic_credential_reaches_the_subprocess() -> None:
    """The whole point of the provider. A key in the environment must not reach the child."""
    with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-leaked",
                                      "ANTHROPIC_AUTH_TOKEN": "oat-leaked",
                                      "PATH": os.environ.get("PATH", "")}):
        env = llm._cli_env()
    assert "ANTHROPIC_API_KEY" not in env, "the API key reached the CLI — it would bill the API"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "PATH" in env, "the scrub must remove credentials, not the whole environment"


def test_bare_is_never_passed() -> None:
    """`--bare` forces API-key auth and would put every routed call back on the bill.

    Pinned because it reads as the lean option: it disables hooks, plugins and CLAUDE.md discovery,
    which is exactly what this provider wants — and, in the same breath, stops OAuth being read at
    all. The most plausible future 'optimisation' is the one that undoes the point.
    """
    cmd = _built_command()
    assert "--bare" not in cmd


# --------------------------------------------------------------------------------------------------
# Role routing
# --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("role, expected", [
    ("analyze", "claude_cli"),      # the one role that is routed
    ("prefilter", "anthropic"),     # high volume, cheap: stays on the bill, not the rate limit
    ("cv_review", "anthropic"),
    (None, "anthropic"),            # no role at all -> the configured provider
])
def test_only_named_roles_are_routed_to_the_cli(role: str | None, expected: str) -> None:
    config = {"llm": {"provider": "anthropic", "cli_roles": ["analyze"]}}
    assert llm.resolve_provider(config, role=role).name == expected


def test_unset_cli_roles_leaves_every_role_on_the_configured_provider() -> None:
    """What a fresh clone gets: no CLI, no subscription, nothing routed."""
    config = {"llm": {"provider": "anthropic"}}
    for role in ("analyze", "prefilter", "extract", "cv_parse", "cv_review", None):
        assert llm.resolve_provider(config, role=role).name == "anthropic"


def test_a_bare_string_reads_as_one_role() -> None:
    """`cli_roles: analyze` is the likely hand-edit; it must not read as five single letters."""
    assert llm.cli_roles({"llm": {"cli_roles": "analyze"}}) == frozenset({"analyze"})


# --------------------------------------------------------------------------------------------------
# The command, and the message shapes this repo actually sends
# --------------------------------------------------------------------------------------------------

def _built_command() -> list[str]:
    """Build one command without running it, by intercepting `subprocess.run`."""
    model = llm._ClaudeCLI(model="claude-sonnet-5", effort="medium").with_structured_output(_Schema)
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return mock.Mock(returncode=0, stdout='{"structured_output": {"verdict": "SKIP"}}', stderr="")

    with mock.patch("core.llm.shutil.which", return_value="/usr/bin/claude"), \
         mock.patch("core.llm.subprocess.run", side_effect=fake_run):
        out = model.invoke([("system", [{"type": "text", "text": "RUBRIC",
                                         "cache_control": {"type": "ephemeral"}}]),
                            ("human", "THE JD")])
    assert out.verdict == "SKIP"
    assert seen["kwargs"]["env"].get("ANTHROPIC_API_KEY") is None
    return seen["cmd"]


def test_the_command_asks_for_native_structured_output_and_no_tools() -> None:
    cmd = _built_command()
    assert "--json-schema" in cmd, "without this the output is prose, not a validated object"
    assert cmd[cmd.index("--tools") + 1] == "", "tool schemas would be billed on every call"
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5"
    assert cmd[cmd.index("--effort") + 1] == "medium"
    # The rubric must arrive as the system prompt, REPLACING Claude Code's own — that is what keeps
    # its tool schedule and CLAUDE.md off the bill, and what makes the prompt cache hit run to run.
    assert cmd[cmd.index("--system-prompt") + 1] == "RUBRIC"


@pytest.mark.parametrize("messages", [
    # The tuple form with cache_control blocks: analyze, prefilter, extract, the research planner.
    [("system", [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]),
     ("human", "USER")],
    # The plain dict form: cv_parse, cv_review.
    [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}],
])
def test_both_message_shapes_in_this_repo_are_understood(messages) -> None:
    """Both are in the tree today, so the shim has to speak both or a role flip breaks a call site."""
    assert llm._split_messages(messages) == ("SYS", "USER")


# --------------------------------------------------------------------------------------------------
# Failure shape — the call sites were written against `except Exception`
# --------------------------------------------------------------------------------------------------

def test_a_failed_call_raises_so_the_call_site_fallback_fires() -> None:
    """`analyze.py` turns this into verdict=SKIP *and* `analysis_errored`, which keeps the job out of
    `seen.json` so tomorrow re-scores it. Returning None instead would silently record a real SKIP."""
    model = llm._ClaudeCLI(model="m", effort=None).with_structured_output(_Schema)
    with mock.patch("core.llm.shutil.which", return_value="/usr/bin/claude"), \
         mock.patch("core.llm.subprocess.run",
                    return_value=mock.Mock(returncode=1, stdout="", stderr="not logged in")):
        with pytest.raises(Exception, match="not logged in"):
            model.invoke([("human", "x")])


def test_a_missing_binary_names_the_setting_that_caused_it() -> None:
    model = llm._ClaudeCLI(model="m", effort=None).with_structured_output(_Schema)
    with mock.patch("core.llm.shutil.which", return_value=None):
        with pytest.raises(llm.ConfigurationError, match="cli_roles"):
            model.invoke([("human", "x")])
