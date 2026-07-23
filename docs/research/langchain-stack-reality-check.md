# LangChain stack reality check

Research findings for ticket `.scratch/jobs-db-oss-rag/issues/01-langchain-stack-reality-check.md`.
Judged against the map's [standing rules](../../.scratch/jobs-db-oss-rag/map.md): **(1) free to run for a
stranger with nothing but their own Claude Code / Anthropic subscription, retrieval offline with no API
key; (2) technology earns its place on tool merit first, credential-motivated adoption labelled and
capped; (3) contain scope; (4) two audiences.**

Researched 2026-07-21 against primary sources (official docs, pricing pages, PyPI metadata, LICENSE
files, SDK source, HuggingFace model cards). Install footprints were **measured locally**, not estimated.

---

## TL;DR

| # | Question | Answer | Recommendation |
|---|---|---|---|
| 1 | Licensing & cost | LangChain/LangGraph are MIT, no account. LangSmith is a paid hosted SaaS; self-hosting is Enterprise-only and license-gated. | **Adopt LangChain/LangGraph freely if they earn it. LangSmith fails standing rule 1 as a dependency — opt-in only, off by default.** |
| 2 | Privacy | Tracing is OFF unless `LANGSMITH_TRACING=true`. When on, it ships inputs + outputs + metadata by default; masking is opt-in. | **Never enable by default. If wired at all, ship it off with `HIDE_INPUTS`/`HIDE_OUTPUTS` pre-set and a loud README warning.** |
| 3 | Does LangChain earn its place? | Measured: +24 packages, +32 MB, and it makes `langsmith` + `langgraph` hard dependencies. It wraps the exact SDK calls `triage/` already makes correctly. | **No. Do not adopt `langchain` in `triage/`. Keep the raw Anthropic SDK.** |
| 4 | Embedding stack | The model is fine (rank 9 of 71 among ≤160M models). `sentence-transformers` is not: measured **1.0 GB** vs a 40 MB baseline, 536 MB of it torch — and **~2 GB on Linux**, which pulls CUDA by default. Brute-force numpy search takes **0.03 ms** at this corpus size. | **Keep `bge-small-en-v1.5`; drop `sentence-transformers` for an ONNX loader (178 MB, same weights). Ship a numpy dot product — no FAISS, no vector DB.** |
| 5 | LangGraph as credential | Real programming model; genuine wins are durable resume + typed pipeline seam. A wrapper around `ThreadPoolExecutor` is not. | **Adopt narrowly and label it: LangGraph for the RAG/agentic path only. Do not rewrite `triage/`'s working loop.** |

---

## 1. Licensing and cost

### LangChain and LangGraph are MIT and require no account

Both are MIT-licensed, confirmed from three independent primary sources each:

- LangChain: [`LICENSE`](https://github.com/langchain-ai/langchain/blob/master/LICENSE) — "MIT License, Copyright (c) LangChain, Inc."; [PyPI `langchain` 1.3.14](https://pypi.org/pypi/langchain/json) reports `License: MIT`.
- LangGraph: [`LICENSE`](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) — "MIT License, Copyright (c) 2024 LangChain, Inc."; [PyPI `langgraph` 1.2.9](https://pypi.org/pypi/langgraph/json) reports MIT; the [README](https://github.com/langchain-ai/langgraph/blob/main/README.md) carries an MIT badge.

The LangGraph README states plainly that the OSS library "can be used without LangChain", and presents
LangSmith and LangSmith Deployment as optional, not required.

> ⚠️ One doc page rendered as claiming LangGraph is Apache 2.0. The LICENSE file, the PyPI metadata, and
> the README badge all say MIT. **Trust the LICENSE file.** Flagging because a licence discrepancy in
> rendered docs is the kind of thing that trips an audit later.

### LangGraph Platform has been renamed and is not required

The old `docs.langchain.com/langgraph-platform/pricing` URL now **404s**. The product has been folded
into LangSmith branding as **"LangSmith Deployment"** (per the LangGraph README, which lists
"LangSmith Deployment" as the optional hosted service). Deployment options per
[the self-host docs](https://docs.langchain.com/langsmith/deploy-standalone-server):

- **Cloud SaaS** — Plus and Enterprise plans.
- **Hybrid** (SaaS control plane, self-hosted data plane) — **Enterprise only**.
- **Fully self-hosted** — **Enterprise only**.
- **Developer-plan self-hosted** — a basic self-hostable LangGraph server, free up to 100k nodes
  executed/month.

**None of this is needed to `pip install langgraph` and run a graph in-process.** The Graph API and the
Functional API both run locally with no account, no API key, no hosted service
([Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api),
[Functional API docs](https://docs.langchain.com/oss/python/langgraph/use-functional-api)). Checkpointer
backends are separate MIT packages — e.g. [`langgraph-checkpoint-sqlite` 3.1.0, MIT](https://pypi.org/pypi/langgraph-checkpoint-sqlite/json).

### LangSmith: current tiers

Primary source: [langchain.com/pricing](https://www.langchain.com/pricing) (the old
`docs.langchain.com/langsmith/pricing-faq` 307-redirects here; `docs.langchain.com/langsmith/pricing` 404s).

| Plan | Price | Seats | Included traces |
|---|---|---|---|
| Developer | $0/seat/mo, then pay-as-you-go | **Maximum of 1 seat** | Up to 5k base traces/mo |
| Plus | $39/seat/mo, then pay-as-you-go | Unlimited seats at $39 each | Up to 10k base traces/mo |
| Enterprise | Custom | Custom seats + workspaces | Custom |

There is no "Business" tier. Usage units for LangSmith Deployment are billed separately: **LCU
(LangChain Compute Unit) $1.50/unit**, **LSU (LangChain Storage Unit) $1.00/unit**.

**Per-trace overage**, verbatim from [usage-and-billing](https://docs.langchain.com/langsmith/usage-and-billing):

- "The Base Charge for a trace is .05¢ per trace" → **$0.0005/trace = $0.50 per 1k base traces**.
- "an `extended` retention trace costs 10x the price of a base tier trace (.50¢ per trace)" →
  **$0.005/trace = $5.00 per 1k extended traces**; the upgrade delta is $4.50/1k.

Traces **silently auto-upgrade** to extended retention (and 10× pricing) when you add feedback, send to
an annotation queue, or match an automation rule. That is a real cost trap for anyone building an eval
harness, which is precisely the adjacent use case the map flags under "Evaluation".

> ⚠️ **Pricing volatility — do not treat these numbers as settled.** Every third-party tracker currently
> reports $2.50 per 1k base traces; the official docs say $0.50. I could not find $2.50 anywhere on a
> langchain.com property. Separately, extended retention is documented as **400 days** on
> [usage-and-billing](https://docs.langchain.com/langsmith/usage-and-billing) and
> [observability-concepts](https://docs.langchain.com/langsmith/observability-concepts) but **180 days**
> on [the pricing page](https://www.langchain.com/pricing). Base retention is consistently 14 days.
> The docs are mid-migration from `docs.smith.langchain.com`; deep links are fragile.

### Account and card requirements

- **An account and API key are required to use hosted LangSmith at all** — the prerequisites on
  [observability-quickstart](https://docs.langchain.com/langsmith/observability-quickstart) are "A
  LangSmith account" and "A LangSmith API key". Even the local `langgraph dev` flow lists a LangSmith
  API key as a prerequisite ([local-dev-testing](https://docs.langchain.com/langsmith/local-dev-testing)).
- A credit card is **not** required to start, but a Developer org **without a payment method is
  hard-capped at 5,000 traces/month** and 50,000 hourly ingest events; adding payment raises the hourly
  cap to 250,000 ([usage-and-billing](https://docs.langchain.com/langsmith/usage-and-billing)).

### Self-hosting LangSmith is Enterprise-only

Verbatim from [self-hosted](https://docs.langchain.com/langsmith/self-hosted): *"Self-hosted LangSmith is
an add-on to the Enterprise plan designed for our largest, most security-conscious customers."* It
requires a **license key obtained through sales**
([support article](https://support.langchain.com/articles/7011309930-how-do-i-obtain-a-self-hosted-langsmith-license-key)).
The Docker path is deprecated in favour of Kubernetes ([docker](https://docs.langchain.com/langsmith/docker)).

**There is no free or OSS self-hosted LangSmith server, and no "LangSmith Lite" in the current docs.**
The only MIT-licensed piece is the client SDK: [`langsmith` 0.10.9, MIT](https://pypi.org/project/langsmith/),
[LICENSE](https://github.com/langchain-ai/langsmith-sdk/blob/main/LICENSE).

### Recommendation — point 1

**LangChain and LangGraph are safe to depend on under standing rule 1.** MIT, no account, no key, no
hosted service, fully offline-capable. Whether they *should* be depended on is points 3 and 5.

**LangSmith cannot be a dependency.** Every path to it requires a second account and an API key, and the
only self-hosted option is gated behind an Enterprise sales conversation. That fails standing rule 1
outright. If LangSmith appears in this repo at all it must be **strictly opt-in, off by default, and
never on any code path required for the tool to function** — which is exactly what the standing rule
already says about "anything hosted".

Do not build the eval harness (the map's "Evaluation" fog) on LangSmith. If evaluation ships, it must
have a local, keyless default.

---

## 2. The privacy question

This repo handles a résumé, inbox-derived job data (`triage/ingest.py` reads Ben's actual Gmail via
AppleScript), and a private fit profile (`profile/rubric.md`, which is injected
verbatim into every analysis prompt). That is the exact payload LangSmith tracing captures.

### What is transmitted by default

When tracing is enabled, LangSmith transmits **inputs, outputs, and metadata** for every run.
[Observability concepts](https://docs.langchain.com/langsmith/observability-concepts) states integrations
"capture inputs, outputs, and metadata without requiring manual code changes". **Nothing is redacted by
default** — masking is entirely opt-in
([mask-inputs-outputs](https://docs.langchain.com/langsmith/mask-inputs-outputs)).

Concretely, with tracing on, a triage run would ship to LangChain Inc.'s servers: the full goal profile,
every scraped job description, and every fit judgment including the `why` field.

### Tracing is OFF by default — verified in source, not just docs

This is the reassuring part, and it is verifiable rather than a docs promise. In
[`langsmith/utils.py`](https://github.com/langchain-ai/langsmith-sdk/blob/main/python/langsmith/utils.py),
`tracing_is_enabled()` resolves `TRACING_V2` falling back to `TRACING`, across the namespaces
`("LANGSMITH", "LANGCHAIN")`, and returns `var_result == "true"`.

So the honoured env vars are `LANGSMITH_TRACING`, `LANGSMITH_TRACING_V2`, `LANGCHAIN_TRACING`,
`LANGCHAIN_TRACING_V2`, and **an unset variable evaluates to `False`**. Only the literal string `"true"`
turns it on. `LANGSMITH_TRACING` is the current documented name; `LANGCHAIN_TRACING_V2` is the legacy
alias. Explicit disable is `LANGSMITH_TRACING=false`
([data-storage-and-privacy](https://docs.langchain.com/langsmith/data-storage-and-privacy)).

**Important consequence for point 3:** installing `langchain` installs the `langsmith` client library as
a hard transitive dependency (measured below). The library is present and imported; it is merely
*inert* absent the env var. That is an acceptable posture, but it is "dormant", not "absent" — worth
being honest about in a README.

### Redaction mechanisms, if tracing is ever enabled

All from [mask-inputs-outputs](https://docs.langchain.com/langsmith/mask-inputs-outputs):

Environment variables (all-or-nothing):
- `LANGSMITH_HIDE_INPUTS=true`
- `LANGSMITH_HIDE_OUTPUTS=true`
- `LANGSMITH_HIDE_METADATA=true`

`Client(...)` constructor params (accept a bool **or** a callable, so granular transforms are possible):
- `hide_inputs`, `hide_outputs`, `hide_metadata`
- `anonymizer` — regex/function redaction over serialized inputs and outputs. Note the interaction: the
  anonymizer is **skipped** for inputs when `LANGSMITH_HIDE_INPUTS=true` (likewise for outputs).
- `process_buffered_run_ops` (Python only) — batch post-processing before transmission

Per-function on `@traceable`: `process_inputs` / `process_outputs`.
Reference implementations: [langsmith-pii-removal](https://github.com/langchain-ai/langsmith-pii-removal).

### Can it be run locally?

**No.** Per §1, self-hosted LangSmith is Enterprise + license key. The nearest local thing is
`langgraph dev` — a lightweight local LangGraph server persisting to a `.langgraph_api` directory
([local-dev-testing](https://docs.langchain.com/langsmith/local-dev-testing)) — but that is a LangGraph
server, not a local LangSmith backend, and the docs still list a LangSmith API key as a prerequisite.

### Separate telemetry to know about

Distinct from tracing, per [data-storage-and-privacy](https://docs.langchain.com/langsmith/data-storage-and-privacy):

- **LangGraph CLI telemetry is ON by default** (OS, versions, command name, flag booleans). Disable with
  `LANGGRAPH_CLI_NO_ANALYTICS=1`. If the LangGraph CLI ever appears in a documented setup step for a
  stranger, that env var should be set in the same breath.
- LangGraph Studio collects page visits/clicks/browser info when logged in; docs state "no application
  data or code...are collected".
- Local `langgraph up` Postgres can be encrypted via `LANGGRAPH_AES_KEY`.

### Regions and retention

Four regional instances ([regions-faq](https://docs.langchain.com/langsmith/regions-faq)): GCP US
(`api.smith.langchain.com`), GCP EU (`eu.api.smith.langchain.com`), GCP APAC, and AWS US. Region is
selected client-side via `LANGSMITH_ENDPOINT`. Regional instances are available on all plans including
free. An org cannot span regions.

Retention: base traces **14 days** (consistent everywhere); extended retention is **400 days** per the
docs and **180 days** per the pricing page — see the volatility warning in §1. Some metadata persists
indefinitely for analytics and billing even after traces expire.

### Recommendation — point 2

**Do not enable LangSmith tracing by default, and do not make it easy to enable accidentally.**

The default-off behaviour is genuinely safe and source-verified, so the risk is not "it leaks silently"
— it is "a stranger follows a tutorial, exports `LANGSMITH_TRACING=true`, and ships their own résumé and
inbox to a third party without connecting the dots."

If tracing is ever wired in:
1. Ship it off, and document it as off.
2. Pre-set `LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` in the sample env file, so the
   opt-in default is metadata-only rather than full payload.
3. Put a blunt sentence in the README: *enabling this transmits your résumé, your inbox-derived job
   data, and your fit profile to LangChain Inc.*
4. Set `LANGGRAPH_CLI_NO_ANALYTICS=1` anywhere the LangGraph CLI is documented.

Under standing rule 4 ("two audiences"), note the conflict out loud: tracing is genuinely useful for
*Ben* debugging his own scoring drift, and genuinely hazardous for a *stranger* who cloned the repo. The
resolution is opt-in with a scary README line, not silent convenience.

---

## 3. Does LangChain earn its place for *this* codebase?

Short answer: **no**, and the measurement is not close.

### What the code actually does today

`triage/` makes exactly three kinds of model call, all through the raw Anthropic SDK
(`triage/config.py` constructs one lazy `anthropic.Anthropic()` client):

| Call site | Model | Shape |
|---|---|---|
| `triage/analyze.py:analyze()` | `claude-opus-4-8` | `messages.parse()` with `output_format=Analysis` (Pydantic), `thinking={"type": "adaptive"}`, system block with `cache_control: ephemeral`, `max_tokens=8000` |
| `triage/prefilter.py:cheap_screen()` | `claude-sonnet-5` | `messages.parse()` with `output_format=_Screen`, cached system block, `max_tokens=400` |
| `triage/ingest.py` | `claude-sonnet-5` | email → `EmailExtraction` structured extraction |

Orchestration is `ThreadPoolExecutor(max_workers=12)` over `_process` in `triage/__main__.py`. Model IDs
are config-driven in `config/settings.yaml`. Both model call sites already fail safe (analysis errors
become a `SKIP` verdict with the error in `why`; prefilter fails *open* so a screen error never drops a
job).

This is not naive code. It uses prompt caching deliberately (the goal profile is the cached prefix, so
only each JD's text is billed at full price — documented in `analyze.py`'s docstring), it sizes
`max_tokens` from measured truncation failures, and it has a documented reason for every fallback.

### What LangChain would add

`langchain-anthropic`'s `ChatAnthropic` does support the features this code uses — I checked rather than
assumed ([integration docs](https://docs.langchain.com/oss/python/integrations/chat/anthropic)):
`cache_control: {"type": "ephemeral"}` including `ttl: "1h"`, `thinking={"type": "adaptive"}`,
`with_structured_output(..., method="json_schema")` mapping to Anthropic's native structured outputs,
citations, and `get_num_tokens_from_messages()`. `claude-opus-4-8` appears in its own examples. So this
is *not* a "LangChain lags Anthropic features" argument — it is current.

The argument is that it adds a layer without adding a capability:

- `messages.parse(output_format=Analysis)` → `ChatAnthropic(...).with_structured_output(Analysis)`.
  Same Pydantic model, same native `json_schema` path underneath, one more object in between.
- `cache_control` blocks: hand-written either way.
- Model swapping: already solved by `config.yaml` + `config.model(role)`. LangChain's `init_chat_model`
  would solve a portability problem this repo has explicitly declined to have — CLAUDE.md and the
  `claude-api` skill both commit to the Anthropic SDK, and standing rule 1 assumes an Anthropic
  subscription.
- Retries/timeouts: the Anthropic SDK already retries 429/5xx with backoff by default.

Meanwhile it costs a real translation layer between the code and the API surface the project is actually
committed to — every Anthropic feature has to be looked up twice (once in Anthropic's docs, once in
LangChain's mapping), and the failure paths in `analyze.py`/`prefilter.py`, which are load-bearing and
hard-won, would need rewriting against different exception types.

### Package restructuring and dependency weight — measured

LangChain 1.0 reorganised the ecosystem
([v1 release notes](https://docs.langchain.com/oss/python/releases/langchain-v1)): the `langchain`
package is now a slim agent-building surface (`create_agent`, `langchain.messages`, `langchain.tools`,
`langchain.chat_models`, `langchain.embeddings`); legacy chains, retrievers, the indexing API, the hub
module, and the `langchain-community` re-exports all moved to a new **`langchain-classic`** package.
**`create_agent` is now built on LangGraph.**

That restructuring is genuinely good news for dependency weight versus LangChain 0.x. It is still not
free. Measured on this machine (macOS arm64, Python 3.14.3, fresh venvs, 2026-07-21):

| Install | Packages | `site-packages` size |
|---|---|---|
| `pip install anthropic` (today's baseline) | **16** | **40 MB** |
| `pip install langchain langchain-anthropic` | **40** | **72 MB** |
| **Delta** | **+24 packages** | **+32 MB** |

The dependency chain is worth stating explicitly, because it is not obvious from the package name:

- [`langchain` 1.3.14](https://pypi.org/pypi/langchain/json) requires `langchain-core>=1.4.9`,
  **`langgraph>=1.2.5`**, `pydantic`.
- [`langchain-core` 1.5.0](https://pypi.org/pypi/langchain-core/json) requires **`langsmith>=0.3.45`**,
  plus `jsonpatch`, `langchain-protocol`, `packaging`, `pydantic`, `pyyaml`, `tenacity`,
  `typing-extensions`, `uuid-utils`.
- [`langchain-anthropic` 1.4.8](https://pypi.org/pypi/langchain-anthropic/json) requires
  `anthropic>=0.96.0,<1.0.0` and `langchain-core>=1.4.7`.

**Installing `langchain` therefore makes both `langgraph` and the `langsmith` client hard dependencies,
whether or not you use either.** It also pins `anthropic<1.0.0` from a second direction —
`triage/requirements.txt` currently says `anthropic>=0.111` with no upper bound, so LangChain would
introduce an upper bound this project did not choose and would gate future Anthropic SDK upgrades on
`langchain-anthropic` catching up. For a repo whose entire value proposition is riding the Anthropic
API closely, that is a meaningful coupling, not a footnote.

### Recommendation — point 3

**Do not adopt `langchain` in `triage/`. Keep the raw Anthropic SDK.**

This is standing rule 2 working exactly as intended: LangChain would be adopted here for its name, not
its function. Everything it would provide, `triage/` already has — structured outputs, prompt caching,
adaptive thinking, retries, config-driven model selection — and it would cost +24 packages, +32 MB, a
transitive dependency on a hosted-observability client, an unrequested `anthropic<1.0.0` ceiling, and a
rewrite of two carefully-reasoned failure paths. Standing rule 2's "don't rip out what already works"
clause is dispositive.

The narrower question — *should the new RAG/retrieval code use LangChain?* — is a different decision and
should be made when "Which RAG capabilities ship" resolves. Flag for that ticket: if the answer is
"local embeddings + a numpy dot product" (see §4), LangChain adds nothing there either; its retrieval
abstractions earn their keep when you are swapping between many vector stores, which is explicitly not
this project's shape.

---

## 4. The embedding stack

The headline finding is not about the model. **The model is fine; `sentence-transformers` is the
problem.** Measured, not estimated.

### The corpus this actually has to serve

Grounding the scale question in real numbers from this repo:

- 6 `state-*.json` run files at roughly 350 scored jobs each → **~2,000 scored job records**
- `profile/bullet-bank.md`: 359 lines
- `docs/operating/*.md` + `profile/notes/*.md`: 4,100 lines total

Even with aggressive chunking, the corpus is **low single-digit thousands of short documents**. That
number matters enormously for the index decision below.

### Is `BAAI/bge-small-en-v1.5` still a sound choice?

Yes, on the model's own merits. From the
[model card](https://huggingface.co/BAAI/bge-small-en-v1.5):

| Property | Value |
|---|---|
| Parameters | **33.4M** |
| Embedding dimension | **384** |
| Max sequence length | **512 tokens** |
| License | **MIT** |
| Stated MTEB average | **62.17** (56 tasks) |

Two model-card details worth encoding in whatever wrapper gets written:

- **The query instruction prefix is optional in v1.5.** The card gives it verbatim as
  `"Represent this sentence for searching relevant passages:"`, to be prepended to *queries* (not
  passages) in short-query-to-long-passage retrieval — but explicitly notes that for v1.5 models "no
  instruction only has a slight degradation in retrieval performance compared with using instruction".
  Asymmetric prefixing is a classic silent-bug source; given it is optional here, **skip it** and keep
  the code symmetric.
- **Normalize and use cosine, and pool on CLS — not mean.** The card recommends normalized embeddings
  (`normalize_embeddings=True`) and cosine similarity; once normalized, dot product *is* cosine, which
  is what makes the index below valid. Its `1_Pooling/config.json` specifies **CLS pooling**, and the
  card's raw-transformers example normalizes the CLS token. Mean-pooling this model by reflex — the
  common default, and what most tutorial code does — silently degrades it.

Weight files, from the [HF tree API](https://huggingface.co/api/models/BAAI/bge-small-en-v1.5/tree/main?recursive=true):
`model.safetensors` 127.3 MiB, `onnx/model.onnx` (fp32) 133 MB, tokenizer ~0.9 MB. The repo was last
modified 2024-02-22 and the v1.5 weights date from 2023-09-12 — **this is a ~2.5-year-old model.** It has
aged unusually well (see below) but is no longer the frontier.

### How it compares to current small alternatives

> ⚠️ **Verification caveat — read before using these numbers.** The
> [MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard) is a JS/Gradio Space that returns
> only a loading shell to a fetcher, so **the rendered leaderboard could not be read**, and searches for
> "2026 MTEB rankings" return almost entirely SEO content farms, which are not cited here. The table
> below was instead computed from the **official results repository**
> ([embeddings-benchmark/results](https://github.com/embeddings-benchmark/results)) via the `mteb` PyPI
> package, restricted to the 41 tasks of `MTEB(eng, v2)`, keeping only the 176 models with complete
> 41/41 coverage, as an **unweighted mean over tasks**. The public leaderboard aggregates differently
> (mean of per-task-*type* means, plus Borda ranking), so these are the same underlying data but **not
> identical to the displayed score or rank**. Treat ordering as indicative.

Note this means the "62.17" printed on bge-small's own model card and the "64.30" below are **different
benchmarks** (MTEB v1, 56 tasks vs MTEB eng-v2, 41 tasks) — do not compare them to each other.

**bge-small-en-v1.5 today: 64.30 on MTEB(eng, v2) — rank 66 of 176 overall, rank 9 of 71 among models
≤160M params.** Retrieval-only subset (10 tasks, mean nDCG@10): **53.86**.

The overall top of the board is entirely 0.6B–8B decoder embedders (75–76 range), none CPU-viable here.
The small-model band that matters:

| Model | eng-v2 mean | Retrieval | Params | Dim | License | Max tok |
|---|---|---|---|---|---|---|
| [GIST-Embedding-v0](https://huggingface.co/avsolatorio/GIST-Embedding-v0) | 65.50 | 53.59 | 109.5M | 768 | MIT | 512 |
| [**bge-base-en-v1.5**](https://huggingface.co/BAAI/bge-base-en-v1.5) | 65.14 | 54.75 | 109M | 768 | MIT | 512 |
| [GIST-small-Embedding-v0](https://huggingface.co/avsolatorio/GIST-small-Embedding-v0) | 64.76 | 52.00 | 33.4M | 384 | MIT | 512 |
| [**bge-small-en-v1.5**](https://huggingface.co/BAAI/bge-small-en-v1.5) | **64.30** | **53.86** | **33.4M** | **384** | **MIT** | **512** |
| [gte-small](https://huggingface.co/thenlper/gte-small) | 63.22 | 50.26 | 33.4M | 384 | MIT | 512 |
| [granite-embedding-english-r2](https://huggingface.co/ibm-granite/granite-embedding-english-r2) | 62.84 | **56.43** | 149.0M | 768 | Apache 2.0 | **8192** |
| [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) | 62.20 | 47.97 | 136.7M | 768 | Apache 2.0 | 8192 |
| [**arctic-embed-s**](https://huggingface.co/Snowflake/snowflake-arctic-embed-s) | 61.59 | **54.85** | **33.4M** | **384** | Apache 2.0 | 512 |
| [arctic-embed-m-v1.5](https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5) | 61.51 | **58.05** | 109.5M | 768 | Apache 2.0 | 512 |
| [e5-small-v2](https://huggingface.co/intfloat/e5-small-v2) | 61.32 | 48.46 | 33M | 384 | MIT | 512 |
| [**granite-embedding-small-english-r2**](https://huggingface.co/ibm-granite/granite-embedding-small-english-r2) | 61.07 | 53.93 | **47.7M** | **384** | Apache 2.0 | **8192** |
| [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | 59.69 | 46.43 | 118M | 384 | MIT | 512 |
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | 59.03 | 42.92 | 22.7M | 384 | Apache 2.0 | **256** |
| [potion-retrieval-32M](https://huggingface.co/minishlab/potion-retrieval-32M) (static) | 53.92 | **35.06** | 32.3M | 512 | MIT | ∞ |

What this actually says:

- **bge-small holds up remarkably well for a Sept-2023 model.** Nothing in its own size class beats it
  on the overall average, and the best ≤160M model overall (GIST-Embedding-v0, 65.50) is 3.3× the
  parameters for **+1.2 points**. That is noise for personal retrieval over a few thousand documents.
- **If retrieval is all you care about, there are same-size wins.**
  [`arctic-embed-s`](https://huggingface.co/Snowflake/snowflake-arctic-embed-s) is an exact drop-in —
  33.4M params, 384 dims, *identical* query prefix — and scores **+1.0 retrieval** over bge-small, while
  giving up 2.7 points on the non-retrieval tasks. A genuine like-for-like alternative, not an upgrade
  worth churning for.
- **`all-MiniLM-L6-v2` is the wrong default in 2026** — 11 retrieval points below bge-small and capped
  at **256 word pieces**, far too short for a job description. Worth stating explicitly because it is
  still the reflexive choice in most tutorials.
- **Static/Model2Vec embeddings cost ~19 retrieval points** (35.06 vs 53.86). That is not a tradeoff,
  it is a different quality tier — which settles model2vec's role below.

**The one genuinely interesting differentiator is context length,** and here the earlier candidate was
wrong. `triage/analyze.py` already truncates JDs at 8,000 characters, so job descriptions comfortably
exceed bge-small's 512 tokens and **will have to be chunked**. If the corpus design (the map's "Corpus &
chunking design" fog) concludes it wants whole-JD embeddings instead, the right candidate is
[`granite-embedding-small-english-r2`](https://huggingface.co/ibm-granite/granite-embedding-small-english-r2):
**8,192 tokens at 47.7M params and the same 384 dims, with no prefix required**, and retrieval (53.93)
statistically indistinguishable from bge-small. That is 1.4× the parameters — not the 4.5× that
`gte-modernbert-base` would cost. (`gte-modernbert-base` has **no full eng-v2 coverage** in the results
repo; its widely-quoted 64.38 is MTEB **v1** and is not comparable to this table.)

Chunking remains the boring, small option and is almost certainly right. But note the deciding variable
for that ticket.

### Install footprint — the real cost, measured

This is where the recommendation actually turns. Measured on this machine (macOS arm64, Python 3.14.3,
fresh venvs, 2026-07-21):

| Install | Packages | `site-packages` |
|---|---|---|
| `anthropic` (today's `triage/` baseline) | 16 | **40 MB** |
| **`sentence-transformers`** | 40 | **1.0 GB** |
| `fastembed` (ONNX Runtime) | 28 | **178 MB** |
| `model2vec` (static embeddings, pure numpy) | 22 | **87 MB** |

Breakdown of the `sentence-transformers` 1.0 GB:

| Package | Size |
|---|---|
| `torch` | **536 MB** |
| `transformers` | 110 MB |
| `scipy` | 99 MB |
| `sympy` | 76 MB |
| `sklearn` | 47 MB |
| `numpy` | 34 MB |
| `networkx` | 17 MB |

**`sentence-transformers` makes a 40 MB project a 1 GB project — a 25× increase — to run a 33 M-parameter
model.** Over half of that is torch, and a further ~190 MB is `sympy` + `networkx` + `scipy`, which are
torch's transitive dependencies and are not used for embedding at all.

**And macOS arm64 is the *favourable* case.** Wheel sizes from [PyPI](https://pypi.org/project/torch/#files)
and the [torch PyPI JSON](https://pypi.org/pypi/torch/json):

| Platform / index | torch wheel | CUDA baggage |
|---|---|---|
| macOS arm64 (default PyPI) | 111 MB | none — no `+cpu` variant exists or is needed |
| **linux x86_64 (default PyPI)** | **527 MB** | **hard nvidia deps: cudnn 503 MB, nccl 216 MB, triton 198 MB, cusparselt 172 MB, nvshmem 135 MB, plus `cuda-toolkit==13.0.3` components** |
| linux x86_64 (`+cpu` index) | **192 MB** | **none** |

On Linux, `torch` declares the entire CUDA stack as a **hard dependency gated on
`platform_system == "Linux"`** — not an extra. So a stranger who runs `pip install -r requirements.txt`
on Linux downloads **roughly 2 GB** (≈4–6 GB installed) of GPU runtime for a CPU-only job-search tool,
unless they know to pass `--index-url https://download.pytorch.org/whl/cpu`
([pytorch.org install docs](https://pytorch.org/get-started/locally/)). **That single flag is the largest
lever in this entire review**, and it is exactly the kind of thing a stranger cloning the repo will not
know to do.

### The no-torch paths

`fastembed` (Qdrant) runs the model through ONNX Runtime with **no torch at all**. Its docs state the
motivation directly: *"don't download GBs of PyTorch dependencies, and instead use the ONNX Runtime."*
Critically, **`BAAI/bge-small-en-v1.5` is an explicitly supported model** — listed at 384 dims, 0.067 GB,
MIT ([supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/)), as are
`all-MiniLM-L6-v2` and `arctic-embed-s`. So this is the *same model and the same vectors*, not a
downgrade. (No Qwen or granite entries, which constrains the long-context option above.)

Leaner still: `onnxruntime` alone is an **18.4 MB wheel** — you can run bge-small's shipped
`onnx/model.onnx` with `tokenizers` directly and skip fastembed's Pillow/hub dependencies.

Two traps worth naming:

- **`sentence-transformers[onnx]` does not save any space.** ST supports `backend="onnx"` and
  `"openvino"` with real speedups (up to **3.08× on CPU** with int8, per the
  [efficiency docs](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)), but torch
  remains a *core* dependency. It is a speed win, not an install-size win.
- **`model2vec` (87 MB, numpy-only) costs ~19 retrieval points** (35.06 vs 53.86 above). That is a
  different quality tier, not a tradeoff. Reserve it for a world where install size dominates
  everything — which is not this project.

### Is a normalized numpy matrix genuinely sufficient? — benchmarked

Yes, overwhelmingly. With normalized vectors, cosine similarity *is* the dot product, so the entire
index is `scores = X @ q` plus an `argpartition`. Benchmarked on this machine (float32, 384 dims,
`X @ q` + top-10 selection, median of 20 runs; 5 for the 1M case):

| N vectors | Matrix size | Latency/query | Queries/sec |
|---:|---:|---:|---:|
| 1,000 | 1.5 MB | **0.012 ms** | 83,000 |
| 10,000 | 15.4 MB | **0.085 ms** | 11,700 |
| 100,000 | 153.6 MB | **0.93 ms** | 1,080 |
| 1,000,000 | 1,536 MB | 14.7 ms | 68 |

**At this project's actual scale (~2–5k vectors), a brute-force search costs about 0.03 ms and 5 MB of
RAM.** It is exact, has zero index-build step, zero tuning parameters, no recall/latency tradeoff, no
extra dependency, and serializes to a single `.npy` file.

A second independent benchmark run (different process, same machine) produced 0.021 / 0.088 / 1.37 /
13.6 ms across the same four sizes — same order of magnitude, so the numbers are stable.

**FAISS's own guidance says exactly this.** From
[Guidelines to choose an index](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index),
verbatim:

> "If you plan to perform only a few searches (say 1000-10000), the index building time will not be
> amortized by the search time. Then direct computation is the most efficient option."

and on `Flat`:

> "The only index that can guarantee exact results" … it "does not compress the vectors, but does not
> add overhead on top of them."

The wiki's clustering recommendations do not even begin until **below 1M vectors → `IVF_K`**, escalating
to `IVF65536_HNSW32` at 1M–10M and beyond. **This corpus sits two to three orders of magnitude below the
point FAISS's own documentation starts giving advice.**

**Where the crossover actually sits:** below ~10k vectors the question is moot (<0.1 ms). From 10k to
~100k, brute force stays under ~1.5 ms — still inside any UI latency budget. Only past ~10⁵–10⁶ vectors,
*and* only if serving many queries per second, does IVF/HNSW earn its complexity. Even a pessimistic
future — every JD chunked ten ways, ten years of runs accumulated — lands near 10⁵, which the table
shows is still ~1 ms.

Note the argument is **not** about install size: `faiss-cpu` 1.14.3 is MIT and only a 4.8 MB macOS wheel
([PyPI files](https://pypi.org/project/faiss-cpu/#files)). It is about complexity — an index build step,
tuning parameters, approximate results, and a recall/latency failure mode — bought for nothing. And it
would be *visible* ceremony to the employer-audience of standing rule 4: a reviewer who knows retrieval
will notice an ANN index over two thousand vectors and read it as cargo-culting, not competence.

### Recommendation — point 4

1. **Keep `BAAI/bge-small-en-v1.5` as the model.** MIT, 33.4M params, 384 dims, offline, no API key.
   At rank 9 of 71 among models ≤160M on MTEB(eng, v2), nothing in its size class beats it overall, and
   the best ≤160M model anywhere buys +1.2 points for 3.3× the parameters. Age is not a problem here.
   It satisfies standing rule 1 cleanly.
2. **Do not make `sentence-transformers` the default dependency.** This is the single largest scope
   violation in the whole stack under review — a 25× install-size increase, and a much worse one for a
   stranger on Linux who gets CUDA wheels by accident. Standing rule 3 ("prefer the boring, small
   version") and the map's "does this improve the tool *or the ramp*" test both point the same way: a
   1 GB install is a bad ramp.
3. **Default to an ONNX-based loader — `fastembed` at 178 MB — serving the same bge-small weights.**
   Confirmed: bge-small-en-v1.5 is an explicitly supported fastembed model, so this is the same model,
   same vectors, same quality, no torch. If `sentence-transformers` is wanted for local
   experimentation, make it an optional extra, not a base requirement. Note that
   `sentence-transformers[onnx]` is *not* a substitute — it still pulls torch.
   **If `sentence-transformers` does end up in a requirements file, document the Linux `+cpu` index URL
   next to it**, or strangers on Linux silently download ~2 GB of CUDA.
4. **Ship exact search: a normalized float32 numpy matrix and `X @ q`.** No FAISS, no vector database,
   no ANN index. Persist as `.npy` + a JSON sidecar of metadata. This is ~20 lines and is *faster in
   wall-clock* than any indexed alternative at this scale.
5. **Skip the query instruction prefix.** The v1.5 card says it is optional with only slight
   degradation; symmetric encoding removes a whole class of silent bug (prefixing passages as well as
   queries is the classic version).
6. **Use CLS pooling, not mean pooling,** and normalize at write time so the stored matrix is already
   unit-norm and retrieval is a single matmul. Mean-pooling by reflex quietly degrades this model.
7. **Flag for "Corpus & chunking design":** bge-small caps at 512 tokens, and JDs exceed that. Chunking
   is required and is the right call. Only if that ticket concludes it wants whole-document embeddings
   should the model choice be reopened — in which case the candidate is
   **`granite-embedding-small-english-r2`** (8,192 tokens, 47.7M params, 384 dims, no prefix, Apache
   2.0, retrieval indistinguishable from bge-small), *not* `gte-modernbert-base`. Caveat: granite is not
   in fastembed's supported list, so that route would mean hand-rolling the ONNX path.
8. **If a future eval shows retrieval specifically is the weak link,**
   `snowflake-arctic-embed-s` is a same-size, same-dim, same-prefix drop-in worth +1.0 retrieval. Not
   worth churning for pre-emptively.
8. **Revisit only on evidence.** Set the trigger explicitly: swap the model if a real eval shows
   retrieval quality is the bottleneck; add an ANN index if the corpus passes ~100k vectors. Neither is
   true today, and neither is close.

---

## 5. LangGraph as credential

### The actual programming model

LangGraph offers two APIs over the same runtime.

**Graph API** ([docs](https://docs.langchain.com/oss/python/langgraph/graph-api)) — three primitives:

- **State**: a shared `TypedDict` or Pydantic model representing the current snapshot. Fields may carry
  `Annotated` **reducers** defining how updates merge (default replaces; `operator.add` accumulates).
- **Nodes**: plain Python functions taking state and returning a partial update. Per the docs, "nodes do
  the work, edges tell what to do next."
- **Edges**: static (`add_edge`) or dynamic via routing functions (`add_conditional_edges`).

You build with `StateGraph(State)`, `.add_node()`, `.add_edge()`, `.add_conditional_edges()`, then
`.compile()` — which validates structure and binds runtime options like a checkpointer — then
`.invoke()` or `.stream()`.

**Functional API** ([docs](https://docs.langchain.com/oss/python/langgraph/use-functional-api)) —
`@task` decorates individual operations (returning futures you `.result()`), `@entrypoint` marks the
workflow function and takes a `checkpointer`. The docs pitch it as requiring "minimal changes to your
existing code": you annotate existing functions rather than declaring nodes and edges.

**Persistence** ([durable-execution docs](https://docs.langchain.com/oss/python/langgraph/durable-execution)):
`compile(checkpointer=...)` snapshots state per `thread_id`, enabling resume, time-travel, and fault
tolerance. Backends are `InMemorySaver`, `SqliteSaver`, and `PostgresSaver`/`AsyncPostgresSaver`; the
SQLite one is [MIT-licensed and free](https://pypi.org/pypi/langgraph-checkpoint-sqlite/json).

**Crucially, all of this runs in-process with no account, no API key, and no hosted service.** LangGraph
passes standing rule 1 cleanly.

### What the smallest honest adoption looks like for a `triage/`-shaped pipeline

The pipeline is `ingest → fetch → prefilter → analyze → rank → liveness → worklist`, currently
`ThreadPoolExecutor.map(_process, fresh)` plus straight-line calls in `_phase1`. Mapping it to LangGraph:

```python
class TriageState(TypedDict):
    days: int
    candidates: Annotated[list[Job], operator.add]
    jobs: Annotated[list[Job], operator.add]
    skipped_pre: int

g = StateGraph(TriageState)
g.add_node("ingest", ingest_node)
g.add_node("process", process_node)      # fetch + prefilter + analyze, fanned out
g.add_node("rank", rank_node)
g.add_node("liveness", liveness_node)
g.add_node("worklist", worklist_node)
g.add_edge("ingest", "process")
# ... etc
graph = g.compile(checkpointer=SqliteSaver(...))
```

**What this genuinely improves:**

1. **Durable resume.** This is the only argument I find compelling on tool merit. The 2026-07-20 run
   processed 358 jobs and took ~25 minutes of paid Opus calls. Today, a crash at the ranking step loses
   every analysis. A checkpointer makes the run resumable at node granularity. The current design
   already gropes toward this — `_paths()`, the `state-<run_id>.json` file, `latest-run.txt`, and the
   whole Phase-1/Phase-3 `--merge` split exist because the run is long, expensive, and interruptible.
   That is a hand-rolled checkpointer. LangGraph's is better and someone else maintains it.
2. **A typed seam.** `TriageState` with reducers documents the pipeline's data contract in a way the
   current implicit `Job` mutation does not.
3. **Human-in-the-loop primitives.** The Phase-1 → browser-fetch → Phase-3 handoff is literally an
   interrupt-and-resume pattern, hand-built. LangGraph's `interrupt` is the named version of it.

**What would be pure wrapper:**

1. **Replacing `ThreadPoolExecutor`.** The work is network-bound and embarrassingly parallel;
   `ex.map(_process, fresh)` is four lines and correct. `config.max_workers()` is documented as the
   dominant runtime lever. Reimplementing this as graph fan-out buys nothing.
2. **Node-ifying `rank`, `worklist`, `store`.** These are deterministic pure-ish functions called once
   in sequence. Wrapping them in nodes and edges converts three readable lines into a graph declaration.
3. **Conditional edges for the prefilter.** `hard_skip` → `cheap_screen` → `analyze` is already an
   `if/else` in `_process` with a documented bias (fails open, kills render under "Rejected / skipped").
   Making it a conditional edge makes the control flow *harder* to read, not easier.
4. **Anything in `cv/`.** Résumé tailoring is a human-gated single-shot flow.

### The credential angle, stated plainly

Standing rule 2 permits credential-motivated adoption if labelled and capped. LangGraph is the most
defensible candidate in this stack: it is the specific thing employers mean by "agentic orchestration",
it is MIT and keyless so it costs the stranger nothing, and unlike LangChain it has at least one
mechanism (durable checkpointing) this codebase demonstrably wants.

But the honest framing is that `triage/` is a **batch scoring pipeline**, not an agent. It has no loop,
no tool-calling, no model-driven control flow. Rewriting a working `ThreadPoolExecutor` as a StateGraph
to have LangGraph on the résumé is exactly the "résumé cosplay" standing rule 2 forbids — and a reviewer
reading the repo would see a graph where a `for` loop belonged, which is *worse* for the credential than
not using LangGraph at all.

### Recommendation — point 5

**Adopt LangGraph narrowly, on the new RAG/agentic path, and leave `triage/`'s core loop alone.**

Concretely:

1. **Do not rewrite `triage/`'s fetch → prefilter → analyze → rank → worklist flow as a graph.** It
   works, it is well-commented, and the graph version would be less readable.
2. **Do consider LangGraph for the grounded-tailoring / retrieval path**, if that path turns out to have
   real branching, tool use, or a retrieve → draft → verify → revise loop. That is a genuine agent
   shape and LangGraph fits it. Decide once "Which RAG capabilities ship" names the capabilities.
3. **Separately, consider a checkpointer for `triage/`'s run state** — the strongest tool-merit
   argument here. But scope it honestly: if all that's wanted is resumability, the existing
   `state-<run_id>.json` could be hardened for a fraction of the cost. Adopting LangGraph *for* the
   checkpointer means accepting the framework's model everywhere it touches. Evaluate that as its own
   decision, not as a free side effect.
4. **Label it in the repo.** Under standing rule 2, if LangGraph goes in partly for credential value,
   the goals/philosophy doc should say so. A reviewer who sees an honest "we used LangGraph here and
   deliberately not there, here's why" reads as better engineering judgment than uniform adoption.
5. **Cap it:** LangGraph OSS only. No LangSmith Deployment, no LangGraph Platform, no CLI in a
   documented setup step without `LANGGRAPH_CLI_NO_ANALYTICS=1` alongside it.

Note that adopting LangGraph *alone* is much cheaper than adopting LangChain: `langgraph` depends on
`langchain-core` (and therefore transitively on the `langsmith` client) but not on the `langchain`
package itself.

---

## Ambiguity and volatility flags

Collected for whoever acts on this:

1. **LangSmith base-trace price.** Docs say $0.50/1k; every third-party tracker says $2.50/1k. Verify
   in-app before any cost decision.
2. **Extended retention window.** 400 days (docs) vs 180 days (pricing page). Unresolved.
3. **LangGraph Platform → LangSmith Deployment rename.** The old pricing URL 404s; the product has been
   re-shelved under LangSmith branding. Any pre-2026 write-up about "LangGraph Platform pricing" is
   describing a differently-named thing.
4. **Docs migration in progress.** `docs.smith.langchain.com` → `docs.langchain.com/langsmith/*`, with
   redirects and 404s in the mix. Links in this document may rot.
5. **One doc page rendered LangGraph's licence as Apache 2.0** against MIT in the LICENSE file, the
   README badge, and PyPI. Trust the LICENSE.
6. **Version churn.** All version numbers here are as of 2026-07-21. LangChain shipped a 1.0
   restructuring recently enough that pre-1.0 advice about `langchain-community` weight is stale in the
   project's favour.
7. **The rendered MTEB leaderboard could not be read** — it is a JS/Gradio Space, and search results for
   current rankings are dominated by SEO content farms, which are not cited here. §4's table is computed
   from the official `embeddings-benchmark/results` repo using an **unweighted 41-task mean**, whereas
   the leaderboard uses per-task-type means plus Borda ranking. Same data, different aggregation:
   **scores and ranks will not match the leaderboard exactly.** The §4 recommendation does not depend on
   exact ordering — it turns on install footprint and corpus scale, both measured directly.
8. **`gte-modernbert-base` has no full MTEB(eng, v2) coverage** in the results repo. Its widely-quoted
   64.38 is MTEB **v1** and is not comparable to §4's table. Any comparison you see between that number
   and a v2 score is wrong.
9. **`mteb`'s own `ModelMeta` reports bge-small-en-v1.5's `embed_dim` as 512.** That is a bug — the
   model card and `config.json` both say **384**. Don't trust that field if you script against it.
10. **Not verified:** installed-on-disk size of the Linux `+cpu` torch wheel (only the 192 MB download
    was confirmed; macOS expanded ~4.8× from wheel to disk, suggesting ~700–900 MB, but that is an
    estimate). The default-Linux CUDA total (~2 GB) sums the pinned `nvidia-*` wheels but does not
    enumerate every `cuda-toolkit` component, so the real figure is **higher**, not lower.
11. **Not verified:** whether `llama.cpp`'s `llama-embedding` officially supports BGE/BERT GGUF
    embedding models. Its server README documents `--embedding` with `cls`/`mean`/`last` pooling — so it
    is architecturally plausible — but names no BGE model and gives no binary size. Left as unverified
    rather than asserted.

### On method

Install sizes, package counts, and retrieval latencies in §3 and §4 were **measured on this machine**
(macOS arm64, Python 3.14.3, fresh virtualenvs, 2026-07-21) rather than taken from documentation, and
the MTEB figures were computed from the official results repo rather than read off a leaderboard. The
`sentence-transformers` 1.0 GB figure and the retrieval latency table were each produced twice in
independent runs and agreed.

These numbers are reproducible but platform-specific. The Linux x86_64 `torch` figure is **worse, not
better**, than the macOS one measured here, because the default PyPI wheel declares the CUDA stack as a
hard platform-gated dependency.
