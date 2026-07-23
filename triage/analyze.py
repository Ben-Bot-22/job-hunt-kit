"""Analyze one JD against Ben's goal anchor with Opus 4.8 -> a structured, validated judgment.

One structured call per new JD. The goal profile (the only personal rubric) + tier/verdict rules
are the system prompt, prompt-cached so only each JD's text is billed at full price. The model proposes a
tier; rank.py finalizes it deterministically from the signal fields (is_agency/cadence/employment_type).

Since stage 2 the user message also carries **precedent**: the most similar past decisions, retrieved
from the corpus by `precedent.py`. It goes in `messages`, never in `system` — everything job-specific
must stay out of the cached block, or the prompt cache misses on every single job.

The call goes through `core/llm.py`, the single generation path — this is the last of the three call
sites to move, and it went last because it is the judgment Ben reads every weekday morning. The
request on the wire is the same one `messages.parse` sent: `core/test_structured_output.py` pins it
byte-for-byte, including the `thinking` block and the `cache_control` marker, which is what makes
that claim checkable rather than hopeful.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from . import config, precedent
from core import llm
from core.models import Analysis, Job

log = logging.getLogger("triage.analyze")

@lru_cache(maxsize=1)
def _system() -> str:
    """The scorer's system block, built once per process — the rubric injected whole.

    Lazy, not a module constant, and that is the whole point: `config.goal_profile()` reads
    `profile/rubric.md` from disk, so building this at import made *importing* `triage.analyze` touch
    the filesystem. On a fresh clone `profile/` does not ship, so the import — and pytest's collection
    of every test in this module — died before a single test ran. Behind a cache the read happens on
    the first `analyze()` call instead: import is side-effect-free, and the genuinely-missing case
    still fails loudly, at call time, with the same `ConfigurationError` `goal_profile()` raises. Swap
    the rubric mid-process in a test with `_system.cache_clear()`, exactly as `goal_profile` is cleared.
    """
    return (
        "You are a precise job-fit analyst for one specific senior full-stack contractor. Judge each job "
        "STRICTLY against his goal profile below and output only the structured fields. Read the required "
        "skills and the actual role, not just the title.\n\n"
        "===== GOAL PROFILE (the 10/10 anchor) =====\n"
        f"{config.goal_profile()}\n"
        "===== END GOAL PROFILE =====\n\n"
        "TAILORABLE-FIT RULE: his core stack is GCP, but he sells credibly into AWS/cloud-keyworded full-stack "
        "roles — treat those as IN-LANE, not out-of-lane.\n\n"
        "CHANNEL TIER (propose your best guess; a deterministic step finalizes it):\n"
        "  PRIMARY = agency staffing contract, remote (or DFW-drivable hybrid) — the fastest-fill lane.\n"
        "  SECONDARY = contract platform (Braintrust/Gun.io/Upwork/Toptal).\n"
        "  OPPORTUNISTIC = everything else (strong remote perm, DFW hybrid, AI-native standout, remote startup).\n\n"
        "VERDICT + SCORE (0-100):\n"
        "  STRONG_FIT (80-95) = remote + contract/CTH + in-lane + intensity 1-3, AND an engineering IC role "
        "with no mandatory-tech gap, no 10+yr bar, and a known/credible rate. The apply-first tier. If any "
        "hard-gate in the goal profile fires (non-eng role shape, mandatory-tech gap, 10+yr bar), cap at "
        "LOW_FIT — a 'vibe coding' keyword match never lifts a disqualified role here.\n"
        "  FIT (60-79) = remote but missing one top factor (permanent / adjacent-stretch / intensity 4-5); OR "
        "DFW-hybrid contract; OR a strong remote perm.\n"
        "  LOW_FIT (40-59) = in-lane but onsite/relocation, or sub-threshold pay. Visible, deprioritized.\n"
        "  SKIP (<40) = a HARD FILTER fails only (non-US; posted contract rate clearly < $50/hr; primary stack "
        ".NET/Java/native-mobile; requires active clearance). NEVER skip for perm/intensity/cadence alone.\n\n"
        "INTENSITY (1-5, inferred, SEPARATE from fit): 1 laid-back, 3 moderate, 5 startup-velocity/on-call/"
        "always-on. Travel-heavy or FDE-style = high intensity + a red flag.\n\n"
        "RED FLAGS: call out travel/relocation, on-call/always-on, vague or sub-$50/hr rate, clearance, "
        "body-shop/generic-vendor signals, or primary stack outside his lane.\n"
        "RESUME_KEYWORDS: the terms he should tailor his resume/application toward for THIS role.\n"
        "Be honest and specific in `why`, `role_summary`, and `meets_goals` — the user reads these to decide."
    )

_MAX_JD = 8000  # chars — plenty for a verdict; keeps the prompt cheap

# Headroom, not a target. max_tokens truncates mid-generation; with structured output that means
# invalid JSON, and this call's failure path is verdict=SKIP — a truncated job would quietly land in
# "Rejected / skipped". Adaptive thinking tokens count against this cap too. Measured 0/358 failures
# at 4000 on 2026-07-20, but unused tokens aren't billed, so there is no reason to run close to the
# edge. (Same lesson as ingest.py's 8000 -> 20000 fix.)
_MAX_TOKENS = 8000


@lru_cache(maxsize=1)
def _analyze_model():
    """The scorer's runnable, built once per process — what `config.client()` used to give it.

    `core.llm.structured` builds a fresh chat model per call and this runs once per surviving job
    across a five-worker pool, so without the cache the 2026-07-20 run would have constructed 358
    clients where the native path handed out one. Built lazily, inside `analyze`'s try, so a missing
    key surfaces as the same per-job failure rather than at import — the offline tests and
    `python -m triage --help` must not need a key.
    """
    return llm.structured(Analysis, config.model("analyze"), max_tokens=_MAX_TOKENS,
                          thinking=llm.THINKING_ADAPTIVE)  # Opus 4.8: default effort is already 'high'


def user_message(job: Job, precedents: str = "") -> str:
    """The per-job half of the prompt: the JD, and the precedent block when there is one.

    Precedent comes FIRST and the JD last, so the JD — the thing being judged — is what the model
    reads into. An empty corpus produces exactly the message this tool sent before stage 2, which is
    the property that keeps day one working for a stranger with no history.
    """
    jd = job.jd_text[:_MAX_JD] or "(no JD text available — judge from title/company only; low confidence)"
    return (
        (f"{precedents}\n\n" if precedents else "")
        + f"TITLE: {job.title or 'unknown'}\n"
        f"COMPANY: {job.company or 'unknown'}\n"
        f"SOURCE: {job.source_platform or 'unknown'}\n"
        f"POSTED: {job.posted_hint or 'unknown'}\n"
        f"LINK: {job.link or '(none — inline recruiter email)'}\n"
        f"JD_SOURCE: {job.jd_source}\n\n"
        f"JOB DESCRIPTION:\n{jd}"
    )


def analyze(job: Job, precedents: str | None = None) -> Analysis:
    # Retrieval is done here rather than by the caller so every scoring path — phase 1 and the
    # phase-3 re-analysis with the browser-fetched JD — gets the same memory without remembering to.
    user = user_message(job, precedent.for_job(job) if precedents is None else precedents)
    try:
        # The system block stays a *list* carrying its `cache_control` marker. LangChain passes the
        # blocks through rather than flattening them, and a flattened string would drop the cache
        # hint on the one prompt in this pipeline that is re-sent for every single job.
        resp = _analyze_model().invoke([
            ("system", [{"type": "text", "text": _system(), "cache_control": {"type": "ephemeral"}}]),
            ("human", user),
        ])
        if resp is None:   # belt and braces: the wrapper *raises* where `messages.parse` gave None
            raise ValueError("no parsed output")
        return resp
    except Exception as e:  # noqa: BLE001 — keep the job in the list; surface the error as its reason
        log.warning("analysis failed for %s @ %s: %s", job.title, job.company, e)
        return Analysis(
            tier="OPPORTUNISTIC", fit_score=0, intensity=3, verdict="SKIP",
            why=f"analysis_error: {str(e)[:120]}", role_summary="", meets_goals="",
            red_flags=["analysis error"], resume_keywords=[],
        )
