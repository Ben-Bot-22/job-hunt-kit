# Cross-agent portability

Research findings for `.scratch/jobs-db-oss-rag/issues/02-cross-agent-portability.md`.
Researched 2026-07-21. Every load-bearing claim is cited to the vendor that owns it.

> **Note on placement.** Settled: `docs/` is the single doc root — `docs/operating/` (runbooks),
> `docs/agents/`, `docs/research/` (one-off artifacts like this one). Personal strategy notes live in
> `profile/notes/`.

## TL;DR

The honest answer is **not** "support Claude Code only" and **not** "support many agents". It is:

> **Claude Code is the only supported driver. The repo is deliberately not hostile to others, and that
> costs one new file, one file rewrite, three file moves, and one optional symlink** — because the
> largest chunk of this repo's agent surface (`.claude/skills/`, 21 skills) is already written in an
> open standard that ~40 other products read.

The two "Claude-specific" pipeline steps turn out to be the *least* Claude-specific things in the repo:
the Gmail connector is a re-badge of Google's own official Gmail MCP server, and the browser step
already has a documented degraded mode (`--no-browser`) plus an agent-neutral drop-in (Playwright MCP).

The real portability blocker in this repo is not the agent. It is **AppleScript / Apple Mail**
(`triage/ingest.py` shells out to `osascript`), which makes the tool macOS-only for *every* agent
including Claude Code. Naming that in the README matters more than naming the agent.

---

## 1. Is there a real cross-agent convention for repo-level agent instructions?

**Two conventions exist, and they are not the same shape. One is a filename convention with wide but
shallow adoption; the other is an actual specification with a governing body. The second one matters
far more to this repo.**

### AGENTS.md — real, broad, but shallow

- AGENTS.md is "a simple, open format for guiding coding agents." It "emerged from collaborative
  efforts across the AI software development ecosystem, including OpenAI Codex, Amp, Jules from Google,
  Cursor, and Factory," and is "stewarded by the Agentic AI Foundation under the Linux Foundation."
  ([agents.md](https://agents.md/))
- Its own site claims it is "used by over 60k open-source projects" and lists 23 supporting products,
  including Codex, Jules, Factory, Aider, goose, opencode, Zed, Warp, VS Code, Devin, Junie, Amp,
  Cursor, RooCode, Gemini CLI, GitHub Copilot's coding agent, Windsurf, and Augment Code.
  ([agents.md](https://agents.md/))

So: this is a genuine multi-vendor convention, not one vendor's proposal. **But** it is only a filename
+ "it's markdown" agreement. There is no schema, no frontmatter, no semantics. It buys you one thing:
another agent will read your instructions file without being told to.

**Claude Code does not read it.** This is the point most secondary write-ups get wrong — several search
results asserted Claude Code reads AGENTS.md natively. The primary source is explicit:

> "Claude Code reads `CLAUDE.md`, not `AGENTS.md`. If your repository already uses `AGENTS.md` for
> other coding agents, create a `CLAUDE.md` that imports it so both tools read the same instructions
> without duplicating them."
> — [code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory.md)

The documented bridges are a one-line `@AGENTS.md` import at the top of `CLAUDE.md`, or
`ln -s AGENTS.md CLAUDE.md` (symlink requires Administrator or Developer Mode on Windows, so the import
is the portable form). Separately, `/init` with `CLAUDE_CODE_NEW_INIT=1` reads `AGENTS.md`,
`.cursor/rules/`, `.github/copilot-instructions.md`, `.windsurf/rules/` and `.clinerules` when
generating a CLAUDE.md. ([memory docs](https://code.claude.com/docs/en/memory.md))

Gemini CLI is a partial adopter: its default context filename is `GEMINI.md`, configurable via a
`contextFileName` / `context.fileName` setting in `settings.json` that accepts a filename or a list
(e.g. `"contextFileName": "AGENTS.md"`).
([geminicli.com/docs/cli/gemini-md](https://geminicli.com/docs/cli/gemini-md/);
[gemini-cli issue #12345](https://github.com/google-gemini/gemini-cli/issues/12345))

### Agent Skills — the one that actually matters here

This is the bigger finding, and it changes the answer to the whole ticket.

- **Agent Skills is a published open specification** with a formal frontmatter contract, a reference
  validator (`skills-ref validate`), and a public repo. "The Agent Skills format was originally
  developed by Anthropic, released as an open standard, and has been adopted by a growing number of
  agent products." ([agentskills.io](https://agentskills.io/),
  [spec](https://agentskills.io/specification),
  [github.com/agentskills/agentskills](https://github.com/agentskills/agentskills))
- Required frontmatter is only `name` (≤64 chars, lowercase/digits/hyphens, must match the parent
  directory name) and `description` (≤1024 chars). Optional: `license`, `compatibility`, `metadata`,
  `allowed-tools` (experimental). ([spec](https://agentskills.io/specification))
- The client showcase lists ~40 adopters including Claude Code, Claude, OpenAI Codex, Cursor, Gemini
  CLI, GitHub Copilot, VS Code, opencode, Goose, OpenHands, Amp, Junie, Factory, Kiro, Roo Code, Letta,
  Mistral Vibe, Tabnine, Databricks, Snowflake and Spring AI, each with a link to its own skills doc.
  ([agentskills.io](https://agentskills.io/))
- Claude Code says so itself: "Claude Code skills follow the [Agent Skills](https://agentskills.io)
  open standard, which works across multiple AI tools." Codex says the same: "Skills build on the open
  agent skills standard." ([code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills),
  [Codex build-skills](https://learn.chatgpt.com/docs/build-skills))

**The one gap: the spec does not define where skills live on disk.** It defines the folder shape
(`skill-name/SKILL.md` + optional `scripts/`, `references/`, `assets/`) but discovery is left to each
client. Observed paths:

| Client | Project-level skill directories | Source |
|---|---|---|
| Claude Code | `.claude/skills/<name>/SKILL.md` only (plus `~/.claude/skills/`, enterprise, nested `.claude/skills/` in subdirs) | [skills docs](https://code.claude.com/docs/en/skills) |
| OpenAI Codex | `.agents/skills` scanned from cwd up to repo root (plus `~/.agents/skills`, `/etc/codex/skills`) | [Codex build-skills](https://learn.chatgpt.com/docs/build-skills) |
| Cursor | `.agents/skills/`, `.cursor/skills/`, **plus `.claude/skills/` and `.codex/skills/` for compatibility** | [Cursor skills](https://cursor.com/docs/context/skills) |
| opencode | `.opencode/skills/`, **`.claude/skills/`**, `.agents/skills/` | [opencode skills](https://opencode.ai/docs/skills/) |

Two of the four read `.claude/skills/` directly. `.agents/skills/` is the emerging neutral path; Claude
Code does **not** read it.

**Verdict on Q1.** AGENTS.md is a real convention worth honouring with one import line, but it is
low-value here — this repo's instruction file is 30 lines. Agent Skills is the real standard, and this
repo already has 21 skills sitting in it. The portability work is mostly done by accident.

---

## 2. What is the portable subset?

| Claude Code artifact | Nearest equivalent elsewhere | Portable? |
|---|---|---|
| `CLAUDE.md` | `AGENTS.md` (23 products), `GEMINI.md`, `.github/copilot-instructions.md`, `.cursor/rules/` | **Content yes, filename no.** Bridge is a 1-line `@AGENTS.md` import. |
| `.claude/commands/*.md` | Codex custom prompts (`~/.codex/prompts/`), Cursor commands | **No, and don't try.** See below. |
| `.claude/skills/*/SKILL.md` | Agent Skills, same file, ~40 clients | **Yes — this is the portable subset.** Only the directory path differs. |
| `.claude/agents/*.md` (subagents) | No cross-vendor standard. Some agents have their own subagent concept with incompatible schemas. | **No.** |
| Hooks (`.claude/settings.json`) | No cross-vendor standard; each agent has bespoke plugin/hook systems | **No.** |
| MCP servers (`.mcp.json`) | MCP itself is an open protocol with broad client support; the *config file format* is per-client | **Protocol yes, config file no.** |

### Slash commands: the important detail

Claude Code has already merged commands into skills:

> "**Custom commands have been merged into skills.** A file at `.claude/commands/deploy.md` and a skill
> at `.claude/skills/deploy/SKILL.md` both create `/deploy` and work the same way. Your existing
> `.claude/commands/` files keep working."
> — [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)

And Codex's custom prompts are explicitly *not* repo-shareable:

> "Custom prompts require explicit invocation and live in your local Codex home directory (for example,
> `~/.codex`), so they're not shared through your repository."
> — [Codex custom prompts](https://learn.chatgpt.com/docs/custom-prompts)

Codex's own doc points at skills as the repo-shareable replacement. Cursor's skill frontmatter has
`disable-model-invocation: true` meaning "only included when explicitly invoked via `/skill-name`" —
the same field Claude Code uses ([Cursor skills](https://cursor.com/docs/context/skills)).

**So the single highest-leverage portability move in this repo is: convert `.claude/commands/job-triage.md`,
`sync-applied.md` and `tailor-cv.md` into `.claude/skills/<name>/SKILL.md`.** Zero behaviour change in
Claude Code, and they become readable by Cursor and opencode for free.

### MCP client support (relevant to Q4)

MCP is genuinely cross-vendor: "AI assistants like Claude and ChatGPT, development tools like Visual
Studio Code, Cursor, MCPJam, and many others all support MCP."
([modelcontextprotocol.io](https://modelcontextprotocol.io/)) Each client keeps its own config file
format — Claude Code uses `.mcp.json` at project root with a `mcpServers` key, http/sse/ws/stdio
transports ([code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp.md)).

### What has no equivalent at all

Subagents and hooks. If the OSS tool ever depends on a hook or a subagent for correctness rather than
speed, it becomes Claude-Code-only in a way no amount of file-shuffling fixes. Today it does not: the
`/job-triage` step-5 subagent is a throughput optimisation, not a correctness requirement.

---

## 3. The hard-dependency steps

### 3a. Gmail archiving — the least Claude-specific step in the repo

`/job-triage` step 5 uses `mcp__claude_ai_Gmail__{list_labels, search_threads, label_thread,
unlabel_thread}`. **Google publishes an official Gmail MCP server exposing exactly these tools:**

> URL `https://gmailmcp.googleapis.com/mcp/v1`, HTTP transport, OAuth 2.0, tools: `create_draft`,
> `get_thread`, `label_message`, `label_thread`, `list_drafts`, `list_labels`, `search_threads`,
> `unlabel_message`, `unlabel_thread`. "Available as part of the Google Workspace Developer Preview
> Program."
> — [developers.google.com/workspace/gmail/api/guides/configure-mcp-server](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server)

That is the same nine-tool surface, name for name. So the Claude Gmail connector is a hosted wrapper
around a Google-published MCP server, and any MCP client can load it. **It is Developer Preview,
though**, which under standing rule 3 disqualifies it as the recommended baseline for a stranger.

The boring, small, agent-neutral path is the Gmail REST API directly:

- `POST https://gmail.googleapis.com/gmail/v1/users/{userId}/messages/{id}/modify` with `addLabelIds[]`
  / `removeLabelIds[]`; scope `https://www.googleapis.com/auth/gmail.modify`.
  ([users.messages.modify](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify))
- "All standard use of the Gmail API is available at no additional cost." Per-day-per-project threshold
  80,000,000 quota units; `messages.modify` costs 5 units per call.
  ([Gmail API usage limits](https://developers.google.com/workspace/gmail/api/reference/quota))

At 5 units per call, a 300-email archive run is 1,500 units against an 80M/day allowance. Cost is zero;
the only friction is that the user must create their own Google Cloud project and OAuth client. That is
one account they already have (Gmail) and no paid tier — compatible with standing rule 1.

**This is a strict improvement even for Claude Code.** The current step is 3 MCP calls per email over
100+ emails, delegated to a subagent, with a documented near-miss (a College Board interview thread
nearly archived on 2026-07-20 because Gmail archives per *thread* and the list is per *message*). A
`triage/archive.py` that does the thread-level SENT check in code and calls `messages.modify` is
deterministic, testable, faster, and removes an entire agent capability from the critical path.

### 3b. Browser JD retrieval

Claude-in-Chrome is a built-in `claude-in-chrome` MCP server over a localhost WebSocket, driven by
Anthropic's Chrome extension; per Anthropic's docs it requires a direct Anthropic plan and is not
available on WSL or via third-party model providers (Bedrock, Vertex, Foundry)
([code.claude.com/docs/en/chrome](https://code.claude.com/docs/en/chrome)). It is Claude-Code-only, and
it is also the step this repo's own runbook documents as the most fragile — the desktop-app connection
conflict, blank MV3 popups, and CAPTCHA handoffs.

The agent-neutral equivalent is **Playwright MCP** (Microsoft): an MCP server providing browser
automation via accessibility snapshots, which can drive a persistent profile, attach to an existing
browser over a **CDP endpoint**, or use its own Chrome extension to "connect to existing browser tabs
and leverage your logged-in sessions and browser state." Its README ships config snippets for VS Code,
Cursor, Claude Desktop, Cline, Codex, Copilot, Factory, Gemini CLI, Goose, Grok, Junie, Kiro, LM
Studio, opencode, Qodo Gen, Warp and Windsurf; headed by default, `--headless` available.
([github.com/microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp))

The logged-in-real-browser property that makes the current step work (residential IP, existing session,
human CAPTCHA click) is preserved by the CDP/extension modes. So this is a genuine like-for-like
substitute — but it is not free: it is a second install, a second permission model, and a second set of
tool names in the runbook.

**There is already a degraded mode and it is already documented.** `python -m triage --no-browser`
gives Tier-1-only results, and the pipeline surfaces unfetchable JDs in a "⚠ Couldn't fetch" block
rather than silently dropping them (`triage/README.md`, `core/fetch.py`). Given standing rule 3, the
recommendation is: **do not build a browser abstraction. Document `--no-browser` as the portable path
and name Playwright MCP as the user's own upgrade if they want Tier 2 on a non-Claude agent.**

### 3c. The dependency nobody listed: AppleScript

`triage/ingest.py` reads mail by shelling out to `osascript` against Apple Mail (`triage/ingest.py:161`),
because Apple Mail preserves anchored URLs in raw message source. This is **macOS-only and
agent-independent**. A Linux or Windows stranger cannot run Phase 1 at all, with any agent.

If ingestion ever moves to the Gmail API (`users.messages.get?format=raw`), the same OAuth setup as 3a
covers it and the tool becomes cross-platform. That is a bigger job than this ticket and belongs in the
repo-layout / config tickets — but it should be named, because **"which agents do we support" is a
smaller question than "which operating systems do we support", and this repo currently answers the
second one with "one".**

---

## 4. MCP as the portability layer

**Assessment: no. Packaging jobs-db's capabilities as an MCP server is the wrong direction of travel
for this tool, and it would not remove either hard dependency.**

The argument for it — write once, every MCP client gets it — is real in general and false here, for
four reasons:

1. **Direction mismatch.** MCP lets an agent call *out* to a capability. jobs-db's Claude-specific
   steps are capabilities the pipeline needs to reach *in* (a browser session, a mailbox). Wrapping
   `triage` in an MCP server exposes `run_triage` to clients; it does nothing about Chrome or Gmail.
   Those stay exactly as they are.
2. **The CLI already is the portable interface.** `python -m triage --days N`, `--merge`,
   `--no-browser` is a complete, documented, agent-neutral API. Every coding agent on earth can run a
   subprocess. An MCP server would be a JSON-RPC wrapper around an argv parser.
3. **It costs config in every client, forever.** MCP's protocol is standard; the config file is not.
   Shipping a server means documenting `.mcp.json` for Claude Code, `~/.codex/config.toml` for Codex,
   Cursor's MCP settings, VS Code's, etc. — and keeping them current. That is the maintenance burden
   the ticket asks about, and it is recurring, not one-off.
4. **It fights rule 1.** A server process is one more thing that has to be installed, started, kept
   alive, and debugged before a stranger sees a worklist.

**Where MCP *does* pay off is as a consumer, not a producer:** the Gmail MCP server (§3a) and Playwright
MCP (§3b) are both third-party-maintained, both cross-client, and both replace a Claude-specific
capability with a documented config block. That is MCP doing real work at zero build cost — and even
there, the Gmail one is Developer Preview, so the plain-Python `messages.modify` path stays the
recommended baseline.

---

## Recommended support matrix

| Tier | Driver | What works | Promise made in README |
|---|---|---|---|
| **1 — Supported** | Claude Code | Everything: skills, `/job-triage` end to end, Tier-2 browser JD retrieval, Gmail archiving | "This is what it's built for and what gets tested." |
| **2 — Works, unsupported** | Any Agent-Skills client that reads `.claude/skills/` (Cursor, opencode today) or `.agents/skills/` (Codex, Gemini CLI, Copilot/VS Code, Amp, Goose … via the optional symlink) | The skills load and describe the workflow; the Python CLI runs; Tier-1 JD fetch, ranking, worklist, CV tailoring all work. Tier-2 browser JDs need the user's own Playwright MCP. Archiving needs the Gmail path from §3a. | "The skills are standard Agent Skills and the pipeline is a plain CLI. Other agents can drive it. We don't test them." |
| **3 — Always available** | No agent at all | `python -m triage --days N --no-browser`, `--merge`; degraded but functional | "Everything the agent does, it does by running documented commands." |
| **Not supported** | Non-macOS anything | Nothing (AppleScript ingestion) | State this first, above the agent question. |

### What it costs in files to maintain

| Change | Files | Recurring cost |
|---|---|---|
| `AGENTS.md` at root — the portable instructions; `CLAUDE.md` becomes `@AGENTS.md` + a short Claude-only delta | **+1 new, 1 rewritten** | One file to keep current instead of one — no increase, just a rename plus a 3-line stub |
| Convert `.claude/commands/{job-triage,sync-applied,tailor-cv}.md` → `.claude/skills/<name>/SKILL.md` | **3 moved, 0 net new** | Zero. Claude Code treats them identically; Cursor/opencode get them free |
| `.agents/skills` → `.claude/skills` symlink (committed), for Codex/Gemini/Copilot | **+1 symlink** | Zero, but it is a symlink in git — flag Windows caveat in the README and treat it as best-effort |
| `triage/archive.py` — Gmail `messages.modify` archiving, replacing the connector step | **+1 module, +1 test, edits to `/job-triage` step 5 and `triage/README.md`** | Real but small, and it *removes* the riskiest agent-dependent step. Worth doing on tool merit alone, portability is a side effect |
| README section: "Which agents does this work with?" with the table above | **+0 (section in existing README)** | One paragraph, reviewed when a tier changes |
| Playwright MCP | **0 files** — documented as the user's own optional setup, not shipped | Zero |
| MCP server wrapping jobs-db | **Not recommended** | Would be per-client config docs, forever |

**Net: one new markdown file, one new Python module, three file moves, one symlink.** No abstraction
layer, no plugin system, no second implementation.

### The sentence for the README

> jobs-db is built for and tested with **Claude Code**. Its workflows are packaged as standard
> [Agent Skills](https://agentskills.io), so other skills-compatible agents can read and drive them —
> but only Claude Code is supported, and two steps (browser JD retrieval, Gmail archiving) need
> per-agent setup elsewhere. Everything the agent does, it does by running commands you can run
> yourself. **The tool currently requires macOS**, because mail ingestion goes through Apple Mail.

---

## Sources

- [agents.md](https://agents.md/) — AGENTS.md format, stewardship, supporting-tool list, 60k-repo claim
- [agentskills.io](https://agentskills.io/) and [specification](https://agentskills.io/specification) — Agent Skills standard, frontmatter, client showcase
- [github.com/agentskills/agentskills](https://github.com/agentskills/agentskills) — reference validator
- [code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory.md) — CLAUDE.md locations, AGENTS.md import/symlink, `/init` rule ingestion
- [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills) — skill directories, commands-merged-into-skills, Agent Skills conformance
- [code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp.md) — `.mcp.json`, transports, scopes
- [code.claude.com/docs/en/chrome](https://code.claude.com/docs/en/chrome) — Claude in Chrome architecture and availability limits
- [learn.chatgpt.com/docs/build-skills](https://learn.chatgpt.com/docs/build-skills) — Codex `.agents/skills` discovery, open-standard statement
- [learn.chatgpt.com/docs/custom-prompts](https://learn.chatgpt.com/docs/custom-prompts) — Codex prompts are user-level, not repo-shared
- [cursor.com/docs/context/skills](https://cursor.com/docs/context/skills) — Cursor skill dirs incl. `.claude/skills` compatibility, frontmatter
- [opencode.ai/docs/skills](https://opencode.ai/docs/skills/) — opencode skill dirs incl. `.claude/skills`
- [geminicli.com/docs/cli/gemini-md](https://geminicli.com/docs/cli/gemini-md/) and [gemini-cli#12345](https://github.com/google-gemini/gemini-cli/issues/12345) — `contextFileName` / AGENTS.md
- [modelcontextprotocol.io](https://modelcontextprotocol.io/) — MCP overview and client ecosystem
- [developers.google.com/workspace/gmail/api/guides/configure-mcp-server](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server) — official Gmail MCP server, tool list, Developer Preview status
- [Gmail users.messages.modify](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/modify) — label add/remove, scopes
- [Gmail API usage limits](https://developers.google.com/workspace/gmail/api/reference/quota) — no-cost standard use, quota units
- [github.com/microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) — Playwright MCP, CDP/extension modes, client list
- Repo artifacts read directly: `CLAUDE.md`, `.claude/commands/{job-triage,sync-applied,tailor-cv}.md`, `.claude/skills/` (21 skills), `triage/README.md`, `triage/ingest.py`
