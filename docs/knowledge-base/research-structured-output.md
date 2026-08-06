# Structured output: LangChain vs the native Anthropic path

Findings for ticket `.scratch/oss-rag-3-generation-path/issues/01-structured-output-spike.md` — the
spike that had to land before `triage/analyze.py` moves onto the single generation path.

Measured 2026-07-22 against `langchain-anthropic 1.5.0` / `langchain-core 1.5.0` / `anthropic 0.111.0`,
Python 3.14. Reproduce with `.venv/bin/python scripts/probe_structured_output.py` (offline) and
`--live` (two API calls). The load-bearing findings are pinned as tests in
`core/test_structured_output.py`.

---

## TL;DR

**Go.** The migration is safe **on one condition**: every structured call must pass
`method="json_schema"`. With it, the request LangChain puts on the wire is **byte-identical** to the
one `messages.parse()` sends today — same schema, same `thinking`, same `system` blocks, same
`cache_control`. With the **default** (`method="function_calling"`) it is a different prompt, and
under `thinking` it is also a different *reliability* story.

| | native `messages.parse` | LC `json_schema` | LC `function_calling` (default) |
|---|---|---|---|
| Wire mechanism | `output_config.format` | `output_config.format` | `tools` + `tool_choice` |
| Request body | — | **identical** | different |
| Schema position in prompt | after `system` | after `system` | **before `system`** |
| Guaranteed structure | yes | yes | only when `tool_choice` is forced |
| Works with `thinking` | yes | yes | **forcing is dropped** — see below |
| Bad output | returns `None` | raises `OutputParserException` | raises `OutputParserException` |
| Retries | 2 | 2 | 2 |

---

## 1. The mechanism

`ChatAnthropic.with_structured_output(schema, method=...)`
(`langchain_anthropic/chat_models.py:2035`) has two implementations:

- **`method="function_calling"` — the default.** `convert_to_anthropic_tool(schema)` turns the
  Pydantic model into a tool definition, `bind_tools(..., tool_choice="Analysis")` forces it, and a
  `PydanticToolsParser` reads the tool call back out.
- **`method="json_schema"`.** `bind(output_config={"format": ...})` — Anthropic's native structured
  outputs, the same feature `messages.parse(output_format=...)` uses — with a `PydanticOutputParser`
  over the response text.

The ticket's hypothesis was right: **the default is not what this repo does today.** Under it the
schema stops being a response constraint and becomes a tool definition, and tools render *before*
`system` in the request — so the model reads a 1.5 KB tool schema before it reads the goal profile.
That is a prompt change wearing a refactor's clothes.

## 2. The round-trip, offline

Both paths were pointed at an `httpx.MockTransport` and the outgoing JSON bodies diffed
(`scripts/probe_structured_output.py`). Against `analyze.py`'s real call — Opus 4.8, `max_tokens=8000`,
`thinking={"type": "adaptive"}`, a `system` list carrying `cache_control`, `output_format=Analysis`:

```
--- json_schema vs native messages.parse
      max_tokens      same
      messages        same
      model           same
      output_config   same
      system          same
      thinking        same
      identical: True
```

**Identical, key for key, including the `cache_control` marker** — LangChain passes a list-of-blocks
system message straight through rather than flattening it to a string. (The ticket records that the
marker is inert today at 3,375 tokens against a 4,096-token minimum; the point is that nothing about
the migration breaks it when the prefix grows.)

The default method diverges exactly where you'd expect: `output_config` is gone, a `tools` array
appears, and the schema is re-encoded — 1,510 bytes as a tool against 1,872 as an output format,
because the two encoders disagree on the details in §4.

## 3. The round-trip, live

One Opus call through the LangChain `json_schema` path on a real stored JD (Genesis10, *Senior Full
Stack Developer — Remote*, from `state-2026-07-20-094851.json`), same prompt, compared field by field
against the judgment the **native** path stored for that same job on 2026-07-20:

| field | native (2026-07-20) | LangChain (2026-07-22) |
|---|---|---|
| `tier` | PRIMARY | PRIMARY |
| `fit_score` | 90 | **90** |
| `intensity` | 3 | 3 |
| `verdict` | STRONG_FIT | STRONG_FIT |
| `cadence` / `employment_type` / `is_agency` | remote / contract / true | identical |
| `rate` | `$65/hr` | `$65.00/hr` |
| `why`, `role_summary`, `meets_goals`, `red_flags`, `resume_keywords` | — | same substance, different words |

**Every field that ranking touches came back identical**, two days apart, through a different
wrapper. The prose differs, which is what a non-zero-temperature model does and not something a
migration can or should hold still. `rate` differing by a formatting nicety is the same effect.

A second live call ran the cheap `prefilter._Screen` schema through Sonnet — `keep=True`, one-line
reason, correct type. That is the call site 04 migrates first, so it is the one that had to be proven
cheapest-first.

Two live calls total. No loop, no re-scoring sweep.

## 4. What changes silently — carry these into 02 and 06

1. **`method="json_schema"` is mandatory and must be impossible to forget.** It is not the default.
   `core/llm.py` (ticket 02) should own the call so no call site can omit it, and
   `core/test_structured_output.py` fails if a version bump changes the default's payload.
2. **Forced tool calling is silently un-forced under `thinking`.**
   `_get_llm_for_structured_output_when_thinking_is_enabled` (`chat_models.py:1882`) drops
   `tool_choice` — the API rejects forcing alongside thinking — warns, and raises
   `OutputParserException` if the model doesn't volunteer the tool call. `analyze.py` runs
   `thinking={"type": "adaptive"}`, and its except-everything handler turns that into
   **`verdict=SKIP`**: a real job in "Rejected / skipped" for a reason that isn't about the job. This
   is the single worst outcome available in this stage, and `json_schema` avoids it entirely.
3. **Failure is a raise, not a `None`.** Native `messages.parse` returns `parsed_output=None` on a
   refusal (verified with a `stop_reason: "refusal"` fixture); LangChain raises
   `OutputParserException`, which subclasses `ValueError` and therefore `Exception`. Both current
   call sites already catch `Exception` and both already fail in the direction they intend
   (`analyze.py` → SKIP with the error in `why`; `prefilter.py` → keep the job), so **06 needs no new
   handling — but it must not delete the `except`**, and `prefilter.py`'s `if s is None` branch
   becomes dead code rather than the live guard it is today.
4. **The two encoders describe the same schema differently.** The native format keeps
   `additionalProperties: false` and pushes Pydantic constraints into prose
   (`"description": "{maximum: 100, minimum: 0}"`); the tool encoder keeps `maximum`/`minimum` as real
   JSON Schema keywords and sets no `additionalProperties`. Under `json_schema` this is moot — the
   payload is produced by the same SDK code either way — and it is recorded only so nobody re-derives
   it while debugging the other path.
5. **`max_retries` defaults to 2** on `ChatAnthropic` (`chat_models.py:956`), matching the Anthropic
   SDK's own default. Retry behaviour is preserved by doing nothing, which is the right kind of
   preserved.
6. **Tracing stays off.** Nothing here enables it; `langsmith` was already in the tree via
   `langchain-core` and remains dormant unless `LANGSMITH_TRACING=true`. See
   [langchain-stack-reality-check.md](research-langchain-stack.md) §2 for why that matters here.

## 5. Cost of the dependency

`langchain-anthropic 1.5.0` is **one package, ~0.5 MB** on top of what stage 2 already installed
(`anthropic`, `langchain-core`, `pydantic` were all present): 76 → 77 packages, site-packages
unchanged at 288 MB to the nearest megabyte. It requires `anthropic<1.0.0,>=0.96.0` — the ceiling the
spec already accepted, currently satisfied by 0.111.0. The spec's "+24 packages / +32 MB" figure was
measured against a tree without `langchain-core`; that cost was paid in stage 2, not here.
