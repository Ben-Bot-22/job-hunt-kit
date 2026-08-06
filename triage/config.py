"""Config for the triage tool — the accessors, not the values.

**There is no `config.yaml` in this package any more.** Stage 4 · 06 split its 141 lines three ways, because
54% of them were a prompt rather than settings:

  * `profile/profile.yaml`  — identity. Your inbox, your applied sheet, the agencies you rate.
  * `profile/rubric.md`     — the scoring rubric, in prose, because it *is* prose. Read by
                              `goal_profile()` and injected whole into the analyzer's system block.
  * `config/settings.yaml`  — operations. Models, window, prefilter, dedup, concurrency, channels.
  * `.env`                  — secrets, and nothing else lives there.

The rubric left YAML for a reason with teeth: it was a `>` folded block scalar, and folding was
gluing six section headings onto the bullet below them, so the anchor Ben had written was not the
anchor Opus was reading. As a markdown file it renders, it diffs a line at a time, and — the point of
the move — **no edit to it can stop the tool loading its config**, because nothing parses it.

No model client is built here. Stage 3 moved all three of this tool's LLM calls onto `core/llm.py`,
the single generation path, and took `client()` out with the last of them — see `core/llm.py` and
`core/test_single_path.py`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from core.settings import PROFILE_DIR, ConfigurationError, load as _load_yaml, model as _model, settings

TRIAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = TRIAGE_DIR.parent

# The four content-named directories (see CLAUDE.md → Where things live), all repo-root-relative —
# except `PROFILE_DIR`, which `core/settings.py` resolves, because `JOBSDB_CONFIG_HOME` moves the
# identity half and the operational half together or not at all. It is `profile/` unless that
# variable is set; `config/example/` is the directory it is set to for the shipped demo.
DATA_DIR = REPO_ROOT / "data"              # the tool's working memory — git-ignored
CORPUS_DIR = DATA_DIR / "corpus"           # state-*.json, seen.json, applied.json — a month of decisions
RUNS_DIR = DATA_DIR / "runs"               # worklists, archives, browser queues, fetch logs — disposable
RESEARCH_DIR = DATA_DIR / "research"       # cached company briefs
REPORTS_DIR = DATA_DIR / "reports"         # market-numbers-*.json
MATCHES_DIR = REPO_ROOT / "matches"        # the curated apply doc, one per run
APPLICATIONS_DIR = REPO_ROOT / "applications"   # one folder per job applied to

# Made on import so a fresh clone works — all four are git-ignored, so none arrive with the checkout, and
# a Claude session writing an apply doc or a tailored CV would otherwise hit a missing directory.
for _d in (CORPUS_DIR, RUNS_DIR, RESEARCH_DIR, REPORTS_DIR, MATCHES_DIR, APPLICATIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SKIPLIST = PROFILE_DIR / "skiplist.md"
PROFILE_PATH = PROFILE_DIR / "profile.yaml"     # identity — tracked in git
RUBRIC_PATH = PROFILE_DIR / "rubric.md"         # the scoring anchor — tracked in git

# jobs-db keeps its secrets in the repo-root .env; reuse it (read-only) so there's one key to manage.
# Which key that is depends on `llm.provider` in config/settings.yaml — `core/llm.py` reads it, and
# this module no longer names a vendor.
load_dotenv(REPO_ROOT / ".env")


def cfg() -> dict:
    """The operational half — `config/settings.yaml`, parsed once by `core.settings`.

    Shared with `core/llm.py` rather than opened a second time here: two loaders would be two caches
    and, after stage 4 · 07, two places a schema could be enforced from.
    """
    return settings()


@lru_cache(maxsize=1)
def profile() -> dict:
    """The identity half — `profile/profile.yaml`.

    Missing is tolerated the same way a missing settings file is: every accessor below carries its own
    default, and a stranger who has not run `/setup` yet gets an empty inbox account rather than an
    import-time crash.
    """
    return _load_yaml(PROFILE_PATH)


def window_days(override: int | None = None) -> int:
    return int(override) if override else int(cfg().get("window_days", 3))


def model(role: str) -> str:
    """role = 'analyze' | 'extract' | 'prefilter'. Delegates: `core.settings` owns the defaults.

    Kept as a re-export because this module is where the rest of the package reads its config, and
    `cv/` calls `core.settings.model()` directly — one definition, two leaves, no duplicate list.
    """
    return _model(role)


def prefilter_enabled() -> bool:
    """Master switch for both cheap gates. False => Opus judges every job (the pre-2026-07-20 behaviour)."""
    return bool(cfg().get("prefilter", {}).get("enabled", True))


def prefilter_screen_enabled() -> bool:
    """The Sonnet gate specifically. False => keep the free regex rules, drop the extra API call."""
    return bool(cfg().get("prefilter", {}).get("screen", True))


def max_workers() -> int:
    """Concurrency for the fetch+analyze pool. Network-bound, so this is the main runtime lever."""
    return max(1, int(cfg().get("max_workers", 5)))


def _liveness() -> dict:
    return cfg().get("liveness", {}) or {}


def liveness_enabled() -> bool:
    """Post-ranking check of whether each ranked req is still open. See triage/liveness.py."""
    return bool(_liveness().get("enabled", True))


def liveness_max_check() -> int:
    """Cap on how many ranked jobs get an availability request (highest-ranked first)."""
    return max(0, int(_liveness().get("max_check", 60)))


def liveness_workers() -> int:
    return max(1, int(_liveness().get("workers", 16)))


def _precedent() -> dict:
    return cfg().get("precedent", {}) or {}


def precedent_enabled() -> bool:
    """Retrieval-augmented scoring. False => the analyzer sees the JD alone, as it did before stage 2."""
    return bool(_precedent().get("enabled", True))


def precedent_k() -> int:
    """How many past decisions are injected. This is the per-scored-job token cost, so it is small."""
    return max(0, int(_precedent().get("k", 3)))


def _dedup() -> dict:
    return cfg().get("dedup", {}) or {}


def dedup_enabled() -> bool:
    """Semantic dedup before scoring. False => every posting reaches the analyzer, as before stage 2."""
    return bool(_dedup().get("enabled", True))


def dedup_similarity() -> float:
    """Cosine floor. Lowering it risks a wrong collapse, which loses a job — see triage/dedup.py."""
    return float(_dedup().get("similarity", 0.95))


def dedup_overlap() -> float:
    """Word-5-gram Jaccard floor on the JD text — the signal that separates 'same req' from
    'same boilerplate'. This is the one doing the real work; treat it as the safety gate."""
    return float(_dedup().get("overlap", 0.80))


def dedup_min_jd_chars() -> int:
    """Below this, two postings have too little text to be compared and are never collapsed."""
    return max(0, int(_dedup().get("min_jd_chars", 500)))


@lru_cache(maxsize=1)
def goal_profile() -> str:
    """`profile/rubric.md`, whole and unparsed — the "10/10" anchor every job is scored against.

    The entire file is the prompt. There is no front matter and no header to strip, deliberately:
    anything added to the file for a human's benefit is also read by the model, so the file's contents
    and the injected text are the same string and nobody has to remember which parts ship.

    Nothing here validates or parses. A rubric that would be unloadable YAML — a stray tab, a rogue
    quote, an indent one space off — is simply text, and reaches the analyzer unharmed. That is the
    whole reason it left the old `config.yaml`, where a bad indent took the models, the window, the
    channel flags and the run down with it.

    *Missing* is a different failure and is loud on purpose: scoring against an empty anchor would
    produce a full worklist of confidently wrong verdicts, which is worse than not running.
    """
    try:
        return RUBRIC_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ConfigurationError(
            f"The scoring rubric {RUBRIC_PATH} is missing — every job is scored against it.\n"
            f"  Restore it from git, or run the `/setup` skill to write one."
        ) from e


def inbox() -> dict:
    return profile().get("inbox", {}) or {}


def channel_enabled(name: str) -> bool:
    """Is this job-input channel switched on? See triage/channels/.

    Defaults to True for a channel with no config block, which is the opposite of what the frozen
    pipeline's `source_enabled` did: config there could pre-enable sources that weren't built yet, so
    absence had to mean off. Here `ALL` *is* the built set, so absence means "nobody has configured it" and the
    honest answer is to run it and let it report. A channel that silently never runs looks exactly
    like a channel supplying no jobs, which is the confusion the health line exists to remove — a
    channel that shouldn't run gets `enabled: false` in writing.
    """
    return bool((cfg().get("channels", {}) or {}).get(name, {}).get("enabled", True))


def board_tokens() -> dict[str, list[str]]:
    """The `boards` watchlist — `{"greenhouse": [...], "lever": [...]}` of board tokens.

    Empty lists are the honest default: the channel runs, costs nothing, and reports `boards 0`, which
    reads as "nobody has named a board yet" rather than as a channel that is quietly off. `/setup`
    seeds real tokens. Unknown ATS keys are ignored here and warned about by the channel, so a typo'd
    `greenouse:` is visible in the log rather than silently dropping a board list.
    """
    b = (cfg().get("channels", {}) or {}).get("boards", {}) or {}
    return {ats: [str(t).strip() for t in (b.get(ats) or []) if str(t).strip()]
            for ats in ("greenhouse", "lever")}


def agency_sources() -> list[str]:
    """Which agency scrapers the `agencies` channel reads. Empty = the channel's own default four.

    Unlike `board_tokens()`, an empty list here is NOT "you have named nothing": the sources are the
    tool's, not the user's, so the honest default is the set measured healthy rather than silence.
    `triage/channels/agencies.py:DEFAULT_SOURCES` owns that list, because the reason a source is in or
    out is a live count and it belongs next to the code that measured it.
    """
    a = (cfg().get("channels", {}) or {}).get("agencies", {}) or {}
    return [str(s).strip() for s in (a.get("sources") or []) if str(s).strip()]


def archive_mailbox() -> str:
    """Gmail label to move processed job emails into after a run. Empty = archiving off.

    Identity rather than operations: it names a label in *your* Gmail, and it is meaningless without
    the `inbox:` block it sits beside.
    """
    return str(profile().get("archive_mailbox", "") or "").strip()


def applied_sheet() -> str:
    """The applied-jobs Google Sheet id. Read in-session by `/sync-applied`, never by the Python."""
    return str(profile().get("applied_sheet", "") or "").strip()


def primary_agencies() -> list[str]:
    return [s.lower() for s in profile().get("primary_agencies", []) or []]


def secondary_platforms() -> list[str]:
    return [s.lower() for s in profile().get("secondary_platforms", []) or []]


