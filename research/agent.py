"""The research loop and the brief — point it at a company name or a job URL, get a short brief.

The loop is a LangGraph `StateGraph` with two nodes, `decide` and `act`, and a hard cap of three
lookups. A graph rather than three functions in sequence because **the agent has to pivot on what it
finds**. The worked example from the corpus: Genesis10 posts via an aggregator, so no board is
reachable; reading the agency page then reveals it is shopping a req for an unnamed "Major Financial
Institution", which *changes the next question* to "does this same JD appear in my corpus under
another company?" — and that question catches one req being shopped by three agencies. A straight
pipeline has to fix its steps before it has seen any results.

The three-pass cap is what makes the non-determinism affordable. A brief is a one-time lookup, never
diffed month over month (unlike the market report in stage 5, which is deliberately *not* an agent).

Everything the loop can reach is one of three tools, all of them already built:

    list_jobs(company_or_url)   research/boards.py   — what else is on their board
    read_page(url)              research/boards.py   — read a page through the Jina reader
    check_history(company)      research/history.py  — the applied record, skiplist and corpus

Both dependencies are injected. `fetch` is the one network call the tools make; `model` is a callable
`(view: str) -> Decision`, chosen by `choose_model` when the caller passes none — the real planner
when there is a key to pay for it, `keyless_plan` when there isn't, so `research_company("Genesis10")`
works on a cold clone with nothing configured. A scripted fake model plus a fixture `fetch` makes the
whole loop assertable offline — the only way the pass cap and the cold-trail order can be tested at
all.

**The brief ends in "Open questions", and that list is the entire interface** between this engine and
whatever is driving it. There are three documented ways to answer it:

    1. Built in     — the three tools above. Free, no key.
    2. Recommended  — hand the list to Claude Code (or any agent): the `/research-company` skill reads
                      the open questions and answers them with its own web search. Free with the
                      subscription the user already has, and no wiring between the layers.
    3. Optional     — set `PERPLEXITY_API_KEY` and let the Python agent resolve them itself, per call.
                      Ships as the documented stub `resolve_open_questions` below.

With no agent at all it degrades to a useful manual checklist, which is the point of writing it down
rather than wiring it up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Callable, Literal

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from core import llm
from . import boards, history
from .boards import BoardResult, default_fetch
from .history import History

# Three lookups. Not a tuning knob: it is the reason a non-deterministic loop is affordable here.
MAX_PASSES = 3

DEFAULT_MODEL_ID = "claude-opus-4-8"

# Phrases that mean "we are not the employer". Matched against the company name and against every page
# the loop actually read — never against a board's job titles, where "our client" language is common in
# postings that a direct employer wrote too.
_AGENCY_MARKERS = (
    "staffing", "our client", "one of our clients", "for our client", "client is seeking",
    "recruiting firm", "recruitment agency", "talent solutions", "talent acquisition partner",
    "contract-to-hire placements", "we place", "placement services", "resource augmentation",
    "consulting and staffing", "managed services provider", "third-party recruiter",
)


# ---------------------------------------------------------------- the model's move
class Decision(BaseModel):
    """One turn of the loop: what to look up next, or stop.

    Also a pydantic model because the real model returns it through `messages.parse`. A fake model in
    a test constructs it directly, which is what keeps the loop assertable offline.
    """
    action: Literal["list_jobs", "read_page", "check_history", "stop"]
    argument: str = Field(default="", description="company name or URL for the tool; empty for stop")
    why: str = Field(default="", description="one line: why this lookup, or why stop")
    open_questions: list[str] = Field(
        default_factory=list,
        description="anything you could not resolve and are not going to — goes in the brief verbatim")


@dataclass
class Lookup:
    """One executed tool call, for the "Where I looked" section. `detail` is empty when it worked."""
    action: str
    argument: str
    ok: bool
    detail: str = ""


@dataclass
class ResearchState:
    """What the loop knows. LangGraph carries this between nodes; nodes return partial updates."""
    target: str = ""                    # what we were pointed at — a company name or a job URL
    company: str = ""                   # best name we have for the employer
    jd: str = ""                        # the JD in hand, when there is one
    passes: int = 0                     # tool calls executed — hard-capped at MAX_PASSES
    board: BoardResult | None = None
    hist: History | None = None
    pages: dict[str, str] = field(default_factory=dict)   # url -> text, only pages actually read
    lookups: list[Lookup] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)    # everything unresolved, in order seen
    decision: Decision | None = None
    capped: bool = False                # stopped because the cap fired, not because the model chose to


@dataclass
class Brief:
    """The result. `markdown` is the whole product; the rest is there so a caller can act on it."""
    company: str
    markdown: str
    employer: str = "undetermined"      # agency | direct | undetermined
    employer_why: str = ""
    open_questions: list[str] = field(default_factory=list)
    researched: str = ""                # the date the lookups ran — what `cache.py` ages it against
    from_cache: bool = False            # served from `data/research/`, not looked up just now
    state: ResearchState | None = None


# ---------------------------------------------------------------- the real model
_SYSTEM = (
    "You are the lookup planner for a pre-apply company-research agent. Before someone applies to a "
    "job, you decide what to look up next about the company, one step at a time.\n\n"
    "TOOLS:\n"
    "  list_jobs(company or URL) — everything currently open on their board. Answers 'is this a "
    "growing team or one desperate backfill'.\n"
    "  read_page(URL) — read one page as text. Use it on the job link you were given, or on the "
    "company's own site, to find out WHO the employer actually is.\n"
    "  check_history(company) — the local record: already applied, on the skiplist, already scored, "
    "and the same JD in the corpus under a DIFFERENT company name (one req shopped by three "
    "agencies). Cheap, local, no network.\n"
    "  stop — you have enough, or nothing else is reachable.\n\n"
    "RULES:\n"
    f"  - You get at most {MAX_PASSES} lookups. Spend them on what is still unknown.\n"
    "  - Follow the link you already have, as far as it goes. Never guess a URL you were not given — "
    "a confidently wrong careers page is worse than 'couldn't check'.\n"
    "  - When a lookup reveals the poster is an agency shopping someone else's req, the next question "
    "is usually check_history: the same JD may already be in the corpus under another name.\n"
    "  - Anything you cannot resolve goes in open_questions, phrased so a person or an agent with web "
    "search can answer it. A gap is never silent."
)

@lru_cache(maxsize=1)
def _planner_model():
    """The planner's runnable, built once per brief — what the module's own client used to give it.

    Lazy, so importing `research.agent` still needs no key and no provider package: the offline tests
    drive an injected fake model and must never touch this.
    """
    # headroom on max_tokens: adaptive thinking counts against it, and a truncated structured
    # response is invalid JSON, i.e. a lost pass.
    return llm.structured(Decision, DEFAULT_MODEL_ID, max_tokens=4000,
                          thinking=llm.THINKING_ADAPTIVE)


def default_model(view: str) -> Decision:
    """The real planner. One structured call per pass — at most three per brief."""
    # The system block stays a *list* with its `cache_control` marker: the same prompt is re-sent on
    # every pass of the loop, and a flattened string would silently drop the cache hint.
    return _planner_model().invoke([
        ("system", [{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}]),
        ("human", view),
    ])


_NO_PLANNER = (
    "No planning model was available (the configured provider has no key), so this brief is the three "
    "default checks in their default order — nothing here pivoted on what was found. Re-read it "
    "yourself: if the poster turns out to be an agency, the question the loop would have asked next "
    "is whether the same req is in the corpus under another name."
)


def keyless_plan(target: str) -> Callable[[str], Decision]:
    """The planner for a cold clone: **the same three tools, in a fixed order, with no key at all.**

    The point of the whole stage is that a stranger gets something useful before configuring
    anything, and that Ben's own agent — which has a subscription, not an API key — can drive it
    (spec, user stories 16–17). So when there is no key, the loop still runs; what is lost is the
    pivot, and that loss is stated in the brief rather than hidden.

    Order: read the link you were handed (if you were handed one), then the board, then the local
    record. Arguments are left empty on purpose after the first step — `act` falls back to the best
    company name known *at that point*, which is how a name resolved by the board reaches the history
    check.

    An agent driving this skill can do better than a fixed order: it has web search, and `python -m
    research tool ...` exposes each tool on its own so it can choose the next one itself.
    """
    queue: list[Decision] = []
    if (target or "").strip().startswith(("http://", "https://")):
        queue.append(Decision(action="read_page", argument=target.strip(),
                              why="start from the link we were actually given"))
    queue.append(Decision(action="list_jobs", why="what else do they have open"))
    queue.append(Decision(action="check_history", why="have we dealt with them before"))
    # Said on the *first* turn, not the last: with a URL the three default steps use the whole pass
    # budget, the cap fires before any `stop` of ours is reached, and a disclosure attached to that
    # `stop` would be silently dropped in exactly the mode the skill tells an agent to prefer.
    queue[0] = Decision(**{**queue[0].model_dump(), "open_questions": [_NO_PLANNER]})

    def plan(view: str) -> Decision:
        if queue:
            return queue.pop(0)
        return Decision(action="stop", why="ran the default checks")
    return plan


def choose_model(target: str) -> Callable[[str], Decision]:
    """`default_model` when the configured provider has a key to pay for it, `keyless_plan` when not.

    The question is asked of `core/llm.py`, not of `ANTHROPIC_API_KEY`, so a stranger who configured
    a local model gets the *real* planner rather than the degraded fixed order — the key a local
    model needs is no key at all, and the old check could never say so.
    """
    try:
        llm.api_key_for(llm.resolve_provider())
    except llm.ConfigurationError:
        return keyless_plan(target)
    return default_model


def resolve_open_questions(questions: list[str]) -> list[str]:
    """STUB — path 3 (optional `PERPLEXITY_API_KEY`) is deliberately not implemented.

    Paths 1 and 2 cover the two audiences this stage has: the built-in tools work on a cold clone with
    no keys, and an agent driving the brief answers the rest with its own web search at no extra cost.
    A per-call search API is a third bill for the same answer, so it ships as this seam rather than as
    a feature — see the module docstring.

    Returns [] always. An implementation would read `PERPLEXITY_API_KEY` and return one answer per
    question, leaving unanswerable ones in place.
    """
    return []


# ---------------------------------------------------------------- the view the model gets
def _render(state: ResearchState) -> str:
    """Everything known so far, as plain text. This is the whole prompt the planner sees."""
    lines = [f"TARGET: {state.target}",
             f"COMPANY (best guess so far): {state.company or 'unknown'}",
             f"LOOKUPS USED: {state.passes} of {MAX_PASSES}"]
    if state.jd:
        lines.append(f"JD IN HAND: yes ({len(state.jd)} chars)")

    if state.board is None:
        lines.append("\nBOARD: not looked up yet.")
    elif state.board.ok:
        lines.append(f"\nBOARD ({state.board.source}, {state.board.url}): "
                     f"{len(state.board.postings)} open role(s)")
        lines += [f"  - {p.title} — {p.location}" for p in state.board.postings[:25]]
        if state.board.text:
            lines.append(f"  page text (first 1500 chars):\n{state.board.text[:1500]}")
    else:
        lines.append(f"\nBOARD: {state.board.detail}")

    if state.hist is None:
        lines.append("\nHISTORY: not checked yet.")
    else:
        h = state.hist
        lines.append("\nHISTORY:")
        lines += [f"  applied: {a.company} — {a.title} ({a.date})" for a in h.applied]
        lines += [f"  skiplist: {s.job_id} — {s.reason}" for s in h.skipped]
        lines += [f"  scored: {s.title} — {s.verdict} {s.fit_score} (seen {s.last_seen})"
                  for s in h.scored[:10]]
        lines += [f"  SAME JD under a different name: {j.company} — {j.title} (overlap {j.overlap})"
                  for j in h.same_jd]
        if not h.found:
            lines.append(f"  {h.detail}")

    for url, text in state.pages.items():
        lines.append(f"\nPAGE READ ({url}), first 2000 chars:\n{text[:2000]}")

    if state.lookups:
        lines.append("\nLOOKUPS SO FAR:")
        lines += [f"  {l.action}({l.argument}) — {'ok' if l.ok else l.detail}" for l in state.lookups]

    lines.append("\nWhat next? Choose one tool, or stop.")
    return "\n".join(lines)


# ---------------------------------------------------------------- nodes
def _build_graph(*, fetch, model, corpus_dir, skiplist):
    """The two-node loop. Both dependencies are closed over, so the graph itself holds no globals."""

    def decide(state: ResearchState) -> dict:
        if state.passes >= MAX_PASSES:
            # The cap, enforced here rather than trusted to the model — a model that always asks for
            # one more lookup is exactly the case this exists for.
            return {"decision": Decision(action="stop", why=f"reached the {MAX_PASSES}-lookup cap"),
                    "capped": True}
        try:
            decision = model(_render(state))
        except Exception as e:  # noqa: BLE001 — the planner is a network call like any other
            gap = (f"⚠ couldn't reach the planning model ({str(e)[:80]}) — the brief below is only "
                   f"what had already been looked up")
            return {"decision": Decision(action="stop", why=f"planner unavailable: {str(e)[:120]}",
                                         open_questions=[gap]),
                    "questions": [*state.questions, gap]}
        # Questions are harvested here, not in `act` — the last decision is a `stop`, which never
        # reaches `act`, and that is exactly the turn where the model says what it gave up on.
        return {"decision": decision,
                "questions": [*state.questions, *decision.open_questions]}

    def act(state: ResearchState) -> dict:
        d = state.decision or Decision(action="stop")
        arg = (d.argument or "").strip()
        update: dict = {"passes": state.passes + 1}

        if d.action == "list_jobs":
            result = boards.list_company_jobs(arg or state.company or state.target, fetch=fetch)
            update["board"] = result
            update["lookups"] = [*state.lookups,
                                 Lookup("list_jobs", arg, result.ok, result.detail)]
            if result.ok and result.company and not state.company:
                update["company"] = result.company

        elif d.action == "read_page":
            text = boards.read_page(arg, fetch=fetch) if arg else ""
            update["lookups"] = [*state.lookups, Lookup(
                "read_page", arg, bool(text), "" if text else f"⚠ couldn't read {arg or '(no url)'}")]
            if text:
                update["pages"] = {**state.pages, arg: text}

        elif d.action == "check_history":
            company = arg or state.company or state.target
            h = history.check_my_history(company, jd=state.jd, corpus_dir=corpus_dir,
                                         skiplist=skiplist)
            update["hist"] = h
            update["lookups"] = [*state.lookups, Lookup("check_history", company, h.ok, h.detail)]

        else:  # an unknown action would otherwise burn a pass silently
            update["lookups"] = [*state.lookups, Lookup(
                d.action, arg, False, f"⚠ unknown lookup '{d.action}' — skipped")]

        return update

    def next_step(state: ResearchState) -> str:
        return END if (state.decision and state.decision.action == "stop") else "act"

    graph = StateGraph(ResearchState)
    graph.add_node("decide", decide)
    graph.add_node("act", act)
    graph.set_entry_point("decide")
    graph.add_conditional_edges("decide", next_step, {"act": "act", END: END})
    graph.add_edge("act", "decide")
    return graph.compile()


# ---------------------------------------------------------------- agency vs direct
def _agency_marker(text: str) -> str:
    low = (text or "").lower()
    for marker in _AGENCY_MARKERS:
        if marker in low:
            return marker
    return ""


def classify_employer(state: ResearchState) -> tuple[str, str]:
    """(verdict, why) where verdict is agency | direct | undetermined.

    Only evidence we actually read counts. A board answering under the company's name is **not**
    evidence of a direct employer — Genesis10 has its own board too, full of other people's reqs — so
    "direct" needs a page we read that carries no agency language. Everything else is `undetermined`,
    which becomes an open question rather than a guess.
    """
    marker = _agency_marker(state.company)
    if marker:
        return "agency", f"the name itself reads as an agency (\"{marker}\")"

    for url, text in state.pages.items():
        marker = _agency_marker(text)
        if marker:
            return "agency", f"{url} says \"{marker}\""

    if state.board and state.board.ok and state.board.text:
        marker = _agency_marker(state.board.text)
        if marker:
            return "agency", f"{state.board.url} says \"{marker}\""

    if state.hist and state.hist.same_jd:
        j = state.hist.same_jd[0]
        return "agency", (f"the same JD is in your corpus under {j.company} "
                          f"({int(j.overlap * 100)}% phrase overlap) — one req, more than one poster")

    if state.pages:
        url = next(iter(state.pages))
        return "direct", (f"nothing on {url} reads as agency language — probable direct employer, "
                          f"on one page's evidence")

    return "undetermined", "nothing was read that says who the employer actually is"


# ---------------------------------------------------------------- the brief
_Q_SHINGLE = 4
_Q_SAME = 0.5


def _q_shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(words[i:i + _Q_SHINGLE]) for i in range(len(words) - _Q_SHINGLE + 1)}


def _dedupe_questions(questions: list[str]) -> list[str]:
    """Drop questions that restate one already asked, keeping the first phrasing.

    The planner runs up to three passes and each pass emits its own `open_questions`, which are
    concatenated — so a gap it could not close on pass 1 is usually asked again, in slightly
    different words, on pass 2. A live `research_company("Genesis10")` produced seven questions of
    which two pairs were restatements; that is the whole reason this exists, and no offline test
    caught it because the fakes each answer once.

    Word 4-grams compared by overlap coefficient, the same shape `history.py` uses on JDs but
    shorter, because a question is a sentence rather than a posting. 0.5 is deliberately
    conservative: two questions about the same subject phrased differently ("is the role still
    open?" vs "is it the same req?") share almost no 4-grams and both survive. **A duplicate
    surviving costs one redundant line; a distinct question dropped costs a gap Ben never sees**,
    and the second failure is the expensive one.
    """
    kept: list[str] = []
    seen: list[set[str]] = []
    for q in questions:
        sh = _q_shingles(q)
        if sh and any(s and len(sh & s) / min(len(sh), len(s)) >= _Q_SAME for s in seen):
            continue
        kept.append(q)
        seen.append(sh)
    return kept


def _collect_questions(state: ResearchState, employer: str) -> list[str]:
    """Every gap, in one list. A gap that never reaches this list reads to Ben as a clean result."""
    out: list[str] = list(state.questions)

    if employer == "undetermined":
        out.append(f"Is {state.company or state.target} the direct employer, or an agency shopping "
                   f"someone else's req? (couldn't determine from what was reachable)")

    if state.board is None:
        out.append(f"What else does {state.company or state.target} currently have open? "
                   f"(no board lookup was made)")
    elif not state.board.ok:
        tried = ", ".join(state.board.attempts) or "nothing reachable"
        out.append(f"{state.board.detail} — what else do they have open? (tried: {tried})")

    if state.hist is None:
        out.append(f"Have you dealt with {state.company or state.target} before? "
                   f"(the local record was not checked)")
    elif not state.hist.ok:
        out.append(f"{state.hist.detail} — your history with them is incomplete")

    # Only the lookups the two branches above don't already speak for — a board failure reported twice
    # reads as two separate gaps.
    for lookup in state.lookups:
        if not lookup.ok and lookup.detail and lookup.action not in ("list_jobs", "check_history"):
            out.append(lookup.detail)

    if state.capped:
        out.append(f"The loop stopped at its {MAX_PASSES}-lookup cap — there may be more to find.")

    # Near-match, not exact: the exact-match pass this replaces never fired, because a planner
    # restating a question rewords it.
    return _dedupe_questions(out)


_HOW_TO_ANSWER = (
    "_Three ways to close these: (1) the built-in tools already tried what they can reach; "
    "(2) **recommended** — hand this list to the agent you're running, which answers them with its "
    "own web search; (3) optional — set `PERPLEXITY_API_KEY` and let the Python agent resolve them "
    "per call._"
)


def render_brief(state: ResearchState) -> Brief:
    """State -> markdown. Deterministic: the model chose the lookups, not the prose."""
    employer, why = classify_employer(state)
    questions = _collect_questions(state, employer)
    name = state.company or state.target
    researched = date.today().isoformat()
    label = {"agency": "**Agency** — not the employer", "direct": "**Direct employer** (probable)",
             "undetermined": "**Undetermined**"}[employer]

    out = [f"# {name}", "",
           f"_{researched} · {state.passes} of {MAX_PASSES} lookups used_", "",
           f"**Who you'd be talking to:** {label} — {why}", "", "## What they have open", ""]

    board = state.board
    if board is None:
        out.append("Not looked up — see Open questions.")
    elif not board.ok:
        out.append(board.detail)
    elif not board.postings and not board.text:
        out.append(f"Their {board.source} board answered and has nothing open right now "
                   f"({board.url}).")
    elif board.postings:
        out.append(f"{len(board.postings)} open on their {board.source} board ({board.url}):")
        out += [f"- {p.title}" + (f" — {p.location}" if p.location else "") for p in board.postings]
    else:
        out.append(f"Read their careers page ({board.url}); it isn't a machine-readable board, so "
                   f"the roles below are unparsed:")
        out += ["", "```", board.text[:1200].strip(), "```"]

    out += ["", "## Your history with them", ""]
    h = state.hist
    if h is None:
        out.append("Not checked — see Open questions.")
    elif not h.ok:
        out.append(h.detail)
    elif not h.found:
        out.append(h.detail)
    else:
        for a in h.applied:
            out.append(f"- **Applied** {a.date or '(no date)'} — {a.title or 'role not recorded'}"
                       + (f" · {a.note}" if a.note else ""))
        for s in h.skipped:
            out.append(f"- **Skiplisted** {s.title or s.job_id}"
                       + (f" — {s.reason}" if s.reason else " — no reason recorded"))
        for s in h.scored:
            out.append(f"- Scored {s.fit_score if s.fit_score is not None else '?'} "
                       f"({s.verdict or 'no verdict'}) — {s.title}, last seen {s.last_seen}")
        for j in h.same_jd:
            out.append(f"- ⚠ **Same JD under {j.company}** ({int(j.overlap * 100)}% phrase overlap, "
                       f"seen {j.seen}) — one req being shopped by more than one poster")

    out += ["", "## Where I looked", ""]
    if state.lookups:
        out += [f"- `{l.action}({l.argument})` — {'ok' if l.ok else l.detail}" for l in state.lookups]
    else:
        out.append("- nothing — no lookup was made")

    out += ["", "## Open questions", ""]
    out += [f"- [ ] {q}" for q in questions] or ["- none — everything asked was answered"]
    out += ["", _HOW_TO_ANSWER, ""]

    return Brief(company=name, markdown="\n".join(out), employer=employer, employer_why=why,
                 open_questions=questions, researched=researched, state=state)


# ---------------------------------------------------------------- entry point
def research_company(name_or_url: str, *, jd: str = "",
                     fetch: Callable[[str], str] = default_fetch,
                     model: Callable[[str], Decision] | None = None,
                     corpus_dir=history.CORPUS_DIR,
                     skiplist=history.SKIPLIST) -> Brief:
    """Research one company and write the brief. At most `MAX_PASSES` lookups, always a brief.

    `name_or_url` is a company name or any link you already have for them. `jd` is the job
    description you're actually looking at, when you have one — it lets the corpus be checked for the
    same req under a different company name before this posting has ever been scored.

    `fetch` and `model` are parameters because the pass cap and the cold-trail order are only
    assertable with them injected. `model=None` picks the real planner when there is a key and
    `keyless_plan` when there isn't, so this runs on a fresh clone with nothing configured.
    """
    target = (name_or_url or "").strip()
    model = model or choose_model(target)
    company = target
    if target.startswith(("http://", "https://")):
        domain = boards.company_domain(target)
        # An aggregator link carries no company domain, so we start with no name at all — resolving it
        # is the loop's first job, not something to guess from the URL.
        company = boards._name_from_domain(domain) if domain else ""

    graph = _build_graph(fetch=fetch, model=model, corpus_dir=corpus_dir, skiplist=skiplist)
    final = graph.invoke(ResearchState(target=target, company=company, jd=jd))
    state = final if isinstance(final, ResearchState) else ResearchState(**final)
    return render_brief(state)
