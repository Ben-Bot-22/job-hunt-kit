"""Cheap two-stage screen that runs BEFORE the expensive Opus analysis.

Why: Opus 4.8 at high effort ran on every one of 358 jobs in the 2026-07-20 run (~25 min, ~5 workers).
Most of those jobs were never going to clear the bar — they failed a rule Ben has already written down.
Paying Opus to rediscover "12+ years required" 300 times is waste.

Two gates, cheapest first:

  1. `hard_skip`  — deterministic regex over the JD. Free, instant, and NEVER drifts. Encodes the skip
     patterns already documented in profile/notes/market-insights.md (10+yr bars, clearance, heavy travel,
     .NET/Java-primary titles). This also fixes a real mis-rank: on 2026-07-13 a Dice role that stated
     "10+ Years of Experience" scored 83 and reached the apply list. It also carries the body-shop
     skip, which is the one rule here whose false-positive direction is expensive enough to be worth
     reading before editing — see `_SHOP_STRONG`.

  2. `cheap_screen` — one small Sonnet call. Kills the obvious out-of-lane remainder before Opus.
     Deliberately biased toward KEEP: a false kill costs Ben a job he never sees, a false keep costs
     one Opus call. Those are not symmetric, so the prompt says so explicitly.

Anything surviving both gates goes to Opus for the real judgment. Prefilter kills are still rendered in
the worklist's "Rejected / skipped" section with their reason, so nothing disappears silently.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from pydantic import BaseModel, Field

from . import config
from core import llm
from core.models import Analysis, Job

log = logging.getLogger("triage.prefilter")

# --- Gate 1: deterministic rules ------------------------------------------------------------------

# A stated seniority bar at or above this many years is a hard skip (Ben's documented pattern: 10+yr
# Staff bars, 12+yr Tech Lead, "12 Years of experience is required"). Below 10 is left to the models —
# 7-8yr asks are routinely stretchable and shouldn't be killed mechanically.
_YEARS_BAR = 10

# A year figure only counts as a REQUIREMENT when it sits next to the word "experience". Without that
# anchor the pattern happily matches company boilerplate — verified against the 2026-07-20 run, where
# bare matching read Darkroom's "operating for 10 years" (company age) as a 10-year bar.
# Two shapes, because JDs write it both ways:
#   "5+ years of professional experience"   -> number then experience
#   "Experience 5-10+ Years"                -> experience then number
_YRS = r"(\d{1,2})\s*(?:[-–—]\s*\d{1,2})?\s*\+?\s*years?"
_YEARS_AFTER = re.compile(_YRS + r"[^.;\n]{0,40}?experience", re.I)
_YEARS_BEFORE = re.compile(r"experience[^.;\n]{0,15}?" + _YRS, re.I)

# Active clearance is a hard gate Ben cannot pass. "Public Trust (or ability to obtain)" is NOT one —
# ArcheSys was a false positive until this exclusion was added.
_CLEARANCE = re.compile(
    r"\b(active\s+(?:ts/sci|top\s+secret|secret|security)\s+clearance"
    r"|ts/sci|top\s+secret\s+clearance|public\s+trust\s+clearance"
    r"|must\s+(?:have|possess|hold)\s+an?\s+active\s+clearance)\b", re.I)
_OBTAINABLE = re.compile(r"\b(?:ability|able|eligible)\s+to\s+obtain|or\s+obtain\b", re.I)

# Travel at or above this share kills the low-drain bridge (priority #1: energy).
_TRAVEL = re.compile(r"(\d{2})\s*%\s*(?:\+\s*)?travel|travel\s*(?:up\s*to\s*)?(\d{2})\s*%", re.I)
_TRAVEL_BAR = 50

# Stack rejection is TITLE-only on purpose. A JD that merely mentions Java in a nice-to-have list is
# still in-lane; a role *titled* "Sr. Java Full Stack Developer" is not.
_OFF_LANE_TITLE = re.compile(
    r"\b(java|\.net|c#|dotnet|salesforce|sap|abap|ios|android|swift|kotlin|golang|rust|php|drupal)\b", re.I)
_IN_LANE_RESCUE = re.compile(r"\b(javascript|java\s*script)\b", re.I)  # don't let "JavaScript" match "java"

# Body shop. The rule keys on the TELLS and never on "is this a staffing firm" — Ben's PRIMARY tier IS
# agencies (Motion, TEKsystems, Insight Global, Apex, Kore1) and agency reqs are his fastest fills, so a
# rule that cannot tell a body shop from an agency would cut his best supply. That is the expensive
# failure direction here, and it is the one every pattern below was narrowed against.
#
# Two strengths, because the tells are not equally load-bearing. Measured over the 1,134-job corpus
# (all six `data/corpus/state-*.json` runs, deduped by link): 6 jobs cut, 0 of the 41 postings from the
# 28 named staffing agencies in it (Genesis10, Kforce, Aditi, Mindlance, DKKD Staffing, Optomi, Proven
# Recruiting all survive).

# One of these is enough — nobody but a body shop writes them.
_SHOP_STRONG = {
    # "Visa: Any workable visa" (Enterprise Mobility), "Fulltime Any Visa" (Atem Corp).
    "any-visa": re.compile(r"\b(?:any|all)\s+(?:workable\s+)?visas?\b|\bvisas?\s*[:\-]\s*any\b", re.I),
    # A work-authorization line dealing in EAD categories: "US-Citizen, H-1B, OPT-EAD, GC-EAD" (Quantum
    # Technologies), "USC, GC, H4EAD, OPTEAD, GCEAD" (New York Technology Partners). Bare "H-1B" and
    # "OPT" are NOT tells — 44 corpus jobs mention them and nearly all are direct employers saying they
    # will not sponsor (Solventum, Jiffy, BNSF, KPMG). The concatenated EAD forms are the vocabulary of
    # a shop that places against every status, which is why the polarity doesn't matter: MPower Plus
    # excludes them ("no OPT, GC_EAD and CPT") and is still a body shop.
    "ead-categories": re.compile(r"\b(?:H4|L2|GC|OPT)\s*[_\- ]?\s*EAD\b|\bEAD\s*[_\- ]?\s*(?:GC|H4|L2|OPT)\b", re.I),
    # Local-driver's-licence-only, and the document demands that travel with it.
    "local-dl": re.compile(
        r"local\s+(?:valid\s+)?(?:DL\b|driver)"
        r"|\b(?:DL|driver'?s?\s+licen[cs]e)\s+(?:copy|is\s+a\s+must|mandatory)"
        r"|copy\s+of\s+(?:your\s+)?(?:DL\b|driver)", re.I),
    # A vendor that will not name the client AT ALL: "Client: To Be Discussed Later" (Quantum). This is
    # deliberately narrow. An agency describing the client generically is normal and must not match —
    # Genesis10's "a Major Financial Institution" is the calibration rubric's STRONG_FIT ~90 example.
    "client-withheld": re.compile(
        r"client\s*[:\-]\s*(?:to\s+be\s+(?:discussed|disclosed|shared)|confidential|tbd"
        r"|will\s+be\s+(?:disclosed|shared|discussed))", re.I),
}

# These need TWO to fire. Each one alone appears in postings from real employers, and the corpus proves
# it: "in-person interview" alone would have killed Versant Media, Acuity Insurance and Allocate, none
# of which is a body shop. The spec named in-person-only as a tell; the corpus narrowed it to a
# corroborating one, which is what acceptance criterion 5 asks for.
_SHOP_WEAK = {
    "req-boilerplate": re.compile(
        r"mode\s+of\s+interview|interview\s+mode\s*[:\-]"
        r"|share\s+your\s+(?:updated\s+)?resume|send\s+(?:me\s+)?your\s+updated\s+resume", re.I),
    "profile-policing": re.compile(
        r"linkedin\s+profile\s+is\s+a\s+must|profile\s+.{0,30}match\s+the\s+resume"
        r"|\bpassport\s+number\b|last\s*4\s+.{0,15}ssn", re.I),
    "bodies-not-people": re.compile(r"\b(?:senior\s+)?resource\s+with\s+\d|\bconsultants?\s+from\s+the\b", re.I),
    "in-person-only": re.compile(r"in[-\s]person\s+interview|face\s+to\s+face\s+interview|\bf2f\b", re.I),
    "local-only": re.compile(r"local\s+candidates?\s+only|only\s+local\s+candidates?", re.I),
}


def _body_shop_tells(jd: str) -> list[str]:
    """The tells present, or [] — a list rather than a bool so the skip reason can name them."""
    strong = [name for name, r in _SHOP_STRONG.items() if r.search(jd)]
    weak = [name for name, r in _SHOP_WEAK.items() if r.search(jd)]
    if strong:
        return strong + weak
    return weak if len(weak) >= 2 else []


def _entry_years(text: str) -> int:
    """The LOWEST stated experience bar — the real entry gate.

    Minimum, not maximum, and the low end of any range: a JD asking "4-8 years" in one bullet and
    "2+ years" of LLM work in another gates at 2, and "Experience 5-10+ Years" gates at 5. Taking the
    max here is what produced every false positive in the 2026-07-20 replay.
    """
    years = [int(m.group(1)) for r in (_YEARS_AFTER, _YEARS_BEFORE) for m in r.finditer(text)]
    years = [n for n in years if 0 < n <= 30]
    return min(years) if years else 0


def _max_travel(text: str) -> int:
    best = 0
    for m in _TRAVEL.finditer(text):
        n = int(m.group(1) or m.group(2) or 0)
        if 0 < n <= 100:
            best = max(best, n)
    return best


def hard_skip(job: Job) -> str | None:
    """Deterministic reject. Returns a human reason, or None to continue to the next gate."""
    if not config.prefilter_enabled():
        return None
    jd = job.jd_text or ""
    title = job.title or ""

    # Title-based off-lane stack. Strip "JavaScript" first so it can't trip the "java" alternative.
    if _OFF_LANE_TITLE.search(_IN_LANE_RESCUE.sub(" ", title)):
        return f"prefilter: off-lane primary stack in title ({title[:60]})"

    if jd:
        yrs = _entry_years(jd)
        if yrs >= _YEARS_BAR:
            return f"prefilter: stated {yrs}+ year entry bar (>= {_YEARS_BAR})"
        if _CLEARANCE.search(jd) and not _OBTAINABLE.search(jd):
            return "prefilter: requires an active security clearance"
        trav = _max_travel(jd)
        if trav >= _TRAVEL_BAR:
            return f"prefilter: {trav}% travel required (>= {_TRAVEL_BAR}%)"
        tells = _body_shop_tells(jd)
        if tells:
            return f"prefilter: body-shop tells ({', '.join(tells)})"
    return None


# --- Gate 2: cheap Sonnet screen ------------------------------------------------------------------

class _Screen(BaseModel):
    keep: bool = Field(description="True if this job deserves a full expensive analysis.")
    reason: str = Field(description="Under 15 words.")


_SCREEN_SYSTEM = (
    "You are a fast, cheap pre-screen deciding ONLY whether a job is worth a slower expensive analysis. "
    "You are NOT scoring fit.\n\n"
    "The candidate is a senior full-stack developer: React/TypeScript/Node, Python/FastAPI, GCP "
    "(Cloud Run/Firebase), Docker, and applied LLM/AI work (Anthropic API, Vertex AI/Gemini, prompt "
    "engineering, agentic tooling). He sells credibly into AWS-keyworded roles. He wants remote (or "
    "DFW-drivable) work, contract preferred but a strong remote perm counts.\n\n"
    "Answer keep=false ONLY when the job is CLEARLY out of his lane — e.g. a primarily .NET/Java/"
    "Salesforce/SAP/mobile-native role, a pure data-science/ML-research or MLOps-infra role with no "
    "application building, a non-engineering role, an onsite-only role far from Oklahoma, or a "
    "junior/intern posting.\n\n"
    "BIAS STRONGLY TOWARD keep=true. A wrong keep costs one extra analysis; a wrong reject means he "
    "never sees the job at all. If you are unsure, or the description is thin or vague, keep=true."
)

_MAX_JD = 2500  # a screen needs far less context than the full analysis

# 200 truncated the JSON on ~2% of calls (measured) -> a wasted screen.
_SCREEN_MAX_TOKENS = 400


@lru_cache(maxsize=1)
def _screen_model():
    """The screen's runnable, built once per process — what `config.client()` used to give it.

    `core.llm.structured` constructs a fresh chat model on every call, and this gate runs once per
    job across a thread pool (358 of them in the 2026-07-20 run). Caching keeps the client count at
    one, as it was on the native path. Built lazily, inside `cheap_screen`'s try, so a missing key
    surfaces as the same fail-open warning rather than at import.
    """
    return llm.structured(_Screen, config.model("prefilter"), max_tokens=_SCREEN_MAX_TOKENS)


def cheap_screen(job: Job) -> tuple[bool, str]:
    """One small Sonnet call. Returns (keep, reason). Fails OPEN — an API error keeps the job."""
    if not config.prefilter_enabled() or not config.prefilter_screen_enabled():
        return True, ""
    jd = (job.jd_text or "")[:_MAX_JD]
    if len(jd.strip()) < 80:
        return True, ""      # too little to judge — let Opus decide
    user = (f"TITLE: {job.title or 'unknown'}\nCOMPANY: {job.company or 'unknown'}\n\n"
            f"JOB DESCRIPTION:\n{jd}")
    try:
        # The system block stays a *list* with its `cache_control` marker: LangChain passes the
        # blocks through rather than flattening them, and flattening would silently drop the cache
        # hint on a prompt that is sent once per job.
        s = _screen_model().invoke([
            ("system", [{"type": "text", "text": _SCREEN_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}]),
            ("human", user),
        ])
        if s is None:   # belt and braces: the wrapper *raises* where `messages.parse` returned None
            log.warning("prefilter screen returned no parse for %s @ %s — keeping", job.title, job.company)
            return True, ""
        return s.keep, s.reason
    except Exception as e:  # noqa: BLE001 — never let the cheap gate drop a job
        # This now also catches `OutputParserException` (a refusal or unparseable output, ~2/350 on
        # the native path) and `core.llm.ConfigurationError` (a missing or wrong provider key).
        # Both keep the job, which is the same direction the native path failed in.
        log.warning("prefilter screen failed for %s @ %s: %s — keeping", job.title, job.company, e)
        return True, ""


def skip_analysis(reason: str) -> Analysis:
    """The Analysis stub a prefiltered job carries, so it still renders under 'Rejected / skipped'."""
    return Analysis(
        tier="OPPORTUNISTIC", fit_score=0, intensity=3, verdict="SKIP",
        why=reason, role_summary="", meets_goals="(screened out before full analysis)",
        red_flags=[reason], resume_keywords=[],
    )
