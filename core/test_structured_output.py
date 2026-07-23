"""The one property stage 3 rests on: LangChain must send the request the native SDK already sends.

`triage/analyze.py` calls `messages.parse(..., output_format=Analysis)` — Anthropic's *native*
structured outputs, which constrain the response. Stage 3 replaces that call with LangChain's
`with_structured_output()`. If the wrapper reaches the wire differently, the difference arrives as
**changed scores**, silently, in the judgment Ben reads every weekday morning.

It reaches the wire two different ways, and only one of them is safe:

  - `method="json_schema"` binds `output_config.format` — the same native feature, byte for byte.
  - `method="function_calling"` (**the default**) binds the schema as a forced tool instead. That
    moves the schema into a `tools` block, which renders *before* `system` in the request, and it
    drops `output_config` entirely. It is a different prompt.

So the failure direction these tests protect against is a silent one: a `langchain-anthropic` bump
that changes the default, the payload shape, or the failure mode, landing as a scoring drift nobody
can attribute. Offline — an httpx MockTransport, no key, no network, no spend.

Findings and measurements: `docs/research/structured-output-spike.md`.
Run:  .venv/bin/python -m pytest core/test_structured_output.py -q
"""
from __future__ import annotations

import json
import warnings

import anthropic
import httpx
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException

from .models import Analysis

MODEL = "claude-opus-4-8"
SYSTEM = [{"type": "text", "text": "SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}}]
USER = "USER MESSAGE"

# A well-formed response carrying JSON that does NOT satisfy `Analysis` — the shape a truncated or
# refused generation actually arrives in. Used to pin the failure path, not the happy path.
_UNPARSEABLE = {
    "id": "msg_test", "type": "message", "role": "assistant", "model": MODEL,
    "content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def _client(sink: list[dict]) -> anthropic.Anthropic:
    """An Anthropic client that records the request body and answers from a fixture."""
    def handler(request: httpx.Request) -> httpx.Response:
        sink.append(json.loads(request.content))
        return httpx.Response(200, json=_UNPARSEABLE)
    return anthropic.Anthropic(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _native_request() -> dict:
    """What `triage/analyze.py` sends today, verbatim."""
    sink: list[dict] = []
    with pytest.raises(Exception):  # noqa: B017,PT011 — `{}` never validates; the request is the point
        _client(sink).messages.parse(
            model=MODEL, max_tokens=8000, thinking={"type": "adaptive"}, system=SYSTEM,
            messages=[{"role": "user", "content": USER}], output_format=Analysis)
    return sink[0]


def _langchain_call(method: str) -> tuple[dict, BaseException]:
    """The request LangChain sent, and what the wrapper did when the response didn't validate."""
    sink: list[dict] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # function_calling + thinking warns; asserted separately
        llm = ChatAnthropic(model=MODEL, api_key="test", max_tokens=8000,
                            thinking={"type": "adaptive"})
        llm._client = _client(sink)       # noqa: SLF001 — the only seam a fake transport fits through
        try:
            llm.with_structured_output(Analysis, method=method).invoke(
                [("system", SYSTEM), ("human", USER)])
        except BaseException as e:  # noqa: BLE001 — the raise *is* one of the findings
            return sink[0], e
    raise AssertionError("expected the unparseable fixture to fail")


def _langchain_request(method: str) -> dict:
    return _langchain_call(method)[0]


def test_json_schema_method_sends_exactly_the_native_request() -> None:
    """The whole migration in one assertion: same body, so the model sees the same prompt.

    Whole-payload equality on purpose. Checking only `output_config` would pass while LangChain
    quietly dropped `thinking`, or flattened the `system` list and with it the `cache_control`
    marker that activates the moment the system prompt crosses 4,096 tokens.
    """
    assert _langchain_request("json_schema") == _native_request()


def test_the_default_method_would_not() -> None:
    """Guard the guard — and pin the reason `method="json_schema"` is not optional.

    The default binds a tool. A future version defaulting the other way is a scoring change with no
    diff to point at, so this test fails loudly instead.
    """
    default = _langchain_request("function_calling")
    assert default != _native_request()
    assert default.get("output_config") is None, "the native schema constraint is gone"
    assert [t["name"] for t in default["tools"]] == ["Analysis"], "the schema became a tool"


def test_forced_tool_calling_is_not_forced_when_thinking_is_on() -> None:
    """The trap under the default: `analyze.py` runs `thinking={"type": "adaptive"}`.

    The API rejects a forced `tool_choice` alongside thinking, so LangChain drops the forcing and
    warns. The model is then merely *invited* to call the tool — an un-called tool raises, and
    `analyze.py`'s except-everything lands the job in "Rejected / skipped".
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ChatAnthropic(model=MODEL, api_key="test", thinking={"type": "adaptive"}) \
            .with_structured_output(Analysis)
    assert any("not guaranteed when `thinking` is enabled" in str(w.message) for w in caught)
    assert "tool_choice" not in _langchain_request("function_calling")


def test_a_bad_response_raises_instead_of_returning_none() -> None:
    """The failure-path difference the call sites must absorb.

    Native `messages.parse` hands back `parsed_output=None` on a refusal; LangChain raises
    `OutputParserException` instead. It subclasses `Exception`, so `analyze.py`'s handler still
    produces `verdict=SKIP` and `prefilter.py`'s still keeps the job — but a migrated call site that
    only checked `is None` would sail straight past the error.
    """
    assert issubclass(OutputParserException, Exception)
    _, raised = _langchain_call("json_schema")   # the fixture returns `{}`, which `Analysis` rejects
    assert isinstance(raised, OutputParserException)
