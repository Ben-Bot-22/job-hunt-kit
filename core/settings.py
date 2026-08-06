"""`config/settings.yaml` — the operational half of the config, loaded in exactly one place.

Stage 4 · 06 split one 141-line `triage/config.yaml` three ways: identity to `profile/profile.yaml`,
the scoring rubric to `profile/rubric.md`, and everything operational here. Two packages now read this
file — `core/llm.py` for the provider, `triage/config.py` for the rest — and they read it through this
module rather than each opening it, so there is one parse, one cache, and one place for stage 4 · 07 to
hang a schema.

The rubric deliberately does **not** live in YAML any more, and does not pass through here. Prose in a
block scalar is the worst of both formats: it doesn't render, it diffs badly, and one bad indent takes
the whole config load down with it. The old file *had* one — six section headings were being folded
onto the following bullet, so the prompt Ben had written was not the prompt the model was reading.

Stage 4 · 07 put a Pydantic schema over this file and **only** this file. The failure it removes:
every accessor in `triage/config.py` carries an inline default, so `max_worker: 12` ran at 5 forever
and nothing said a word. `extra="forbid"` at every level turns that into an error naming the key.

**The rubric gets no schema, and that is the line.** Validating prose is a category error, and this
repo has the evidence: two rubrics existed, and the *structured* one was the dead one — the frozen
pipeline's schema-shaped `profile:` block said "cast a wide net, relocation OK" while the live prose
rubric said "remote only, contract first". `profile/profile.yaml` is unvalidated too: it is identity, not
operations, and the accessors that read it default to empty rather than to a number.

This module also resolves *where* a configuration lives. Normally two places — `profile/` and
`config/settings.yaml` — but `JOBSDB_CONFIG_HOME` collapses both onto one directory, which is what
lets `config/example/` be run against directly instead of copied over somebody's tuned profile.

The generated `config/settings.schema.json` is the same model as JSON Schema, written to disk so an
agent (or an editor's YAML language server) can read what it may edit without reading this file.
Regenerate it with `python -m core.settings`; `core/test_settings.py` fails if it drifts
(`test_the_published_schema_is_in_sync_with_the_model`).
"""
from __future__ import annotations

import json
import os
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "config" / "settings.schema.json"

# --------------------------------------------------------------------------------------------------
# Where a configuration lives
#
# Normally in two places, because the two halves are tracked and edited differently: identity in
# `profile/`, operations in `config/settings.yaml`. `JOBSDB_CONFIG_HOME` collapses both onto one
# directory holding `settings.yaml`, `profile.yaml`, `rubric.md`, `bullet-bank.md` and `skiplist.md`.
#
# `config/example/` is exactly such a directory, which is the point of the variable: a stranger runs
#
#     JOBSDB_CONFIG_HOME=config/example python -m triage --paste <url>
#
# and gets a real run against the shipped fictional seeker without touching — or having — a profile of
# their own. Read once, at import, like every other path constant in this repo. The failure direction
# it exists to prevent is the alternative: a demo that works by copying files over `profile/`, which on
# a configured clone overwrites the most-tuned files in the repo.
# --------------------------------------------------------------------------------------------------

CONFIG_HOME_ENV = "JOBSDB_CONFIG_HOME"


def config_home() -> Path | None:
    """The override directory, or `None` for the normal two-place layout."""
    raw = (os.environ.get(CONFIG_HOME_ENV) or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


CONFIG_HOME = config_home()
PROFILE_DIR = CONFIG_HOME or REPO_ROOT / "profile"
SETTINGS_PATH = (CONFIG_HOME / "settings.yaml") if CONFIG_HOME else REPO_ROOT / "config" / "settings.yaml"


class ConfigurationError(RuntimeError):
    """A problem with the user's config, phrased for the user.

    The failure direction this exists for: a stranger's first run ending in a traceback out of a
    library they've never heard of, which they cannot attribute to their own missing key or typo.
    """


def load(path: Path) -> dict:
    """A settings file, or `{}` when it isn't there.

    A missing file is not an error: a fresh clone with `ANTHROPIC_API_KEY` exported should run, and
    every accessor carries the default this repo has always used. A file that exists but is
    *malformed* does raise — a silent `{}` there would hand back defaults while the user stares at the
    values they wrote down.
    """
    if not path.exists():
        return {}
    import yaml
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigurationError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"{path} must contain a mapping, got {type(loaded).__name__}")
    return loaded


def profile_exists() -> bool:
    """True once a profile has been seeded — `python -m core.example` or `python -m core.setup`.

    A fresh clone has no `profile/` at all: it is the one directory the public tree omits, because it
    is the owner's. The suite ships, and several tests read `profile/profile.yaml` or `profile/rubric.md`
    directly — so on a clone nobody has seeded yet those tests have no subject to guard. They skip with
    an explanation rather than erroring with `FileNotFoundError`, which would tell a reader the project
    is broken when it isn't.
    """
    return (PROFILE_DIR / "profile.yaml").is_file()


def is_example_profile() -> bool:
    """True when the active `profile/` is the shipped fictional-seeker example, not a real owner's.

    Used by the suite, which ships. On a stranger's cold clone `profile/` is seeded from
    `config/example/`, so the tests that pin the OWNER's rubric text or identity values — they guard
    corrections Ben made after a specific mis-score, and are meaningless against Robin Doe — skip
    rather than fail. On the owner's own checkout the same tests run and do their job.

    Detected by the reserved `@example.invalid` inbox address: RFC 2606 guarantees no real person can
    own one, and it is the marker the example is already built around (`core/test_example.py`). Keyed
    on `PROFILE_DIR`, so running the demo via `JOBSDB_CONFIG_HOME=config/example` also reads as example.
    """
    prof = load(PROFILE_DIR / "profile.yaml")
    account = str((prof.get("inbox") or {}).get("account", ""))
    return account.endswith("@example.invalid")


# --------------------------------------------------------------------------------------------------
# The schema
#
# Every field is OPTIONAL and none of them restates a default. That is deliberate: `triage/config.py`
# has carried `cfg().get("max_workers", 5)` since the tool was written, and a default repeated here
# would be a second source of truth that drifts silently — which is the same class of bug as the
# silent-default one this schema exists to kill. What the schema owns is *spelling, shape and range*;
# what the accessors own is what a missing key means. The bounds are the ones where a value outside
# them is a mistake rather than a preference (see each `description`).
# --------------------------------------------------------------------------------------------------

class _Section(BaseModel):
    """A settings block. `extra="forbid"` is the whole point of the file — see the module docstring."""
    model_config = ConfigDict(extra="forbid")


class LLMSettings(_Section):
    provider: str | None = Field(
        default=None,
        description="Vendor every model call goes to: anthropic (tested), openai, google, ollama. "
                    "Deliberately a free string here — core/llm.py owns the registry and its error "
                    "already names the providers and their tiers.")
    base_url: str | None = Field(
        default=None, description="Local / self-hosted / proxy endpoint. Omit for the provider's own.")
    cli_roles: list[str] | None = Field(
        default=None,
        description="Model roles (the keys under `models:`) routed through the Claude Code CLI "
                    "instead of `provider`, so they bill to a Claude subscription rather than an API "
                    "key. Empty or unset = every role uses `provider`. Per-role rather than global "
                    "because cost is concentrated in `analyze` while call VOLUME is not, and a "
                    "subscription has a rate limit where an API key has a bill.")
    structured_method: str | None = Field(
        default=None,
        description="How the response schema is bound. Leave unset on Anthropic: `json_schema` is what "
                    "makes the request byte-identical to the native call it replaced.")
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = Field(
        default=None,
        description="How hard the model thinks, and the dominant cost lever: billing is output-token "
                    "dominated and effort is what sets output length. Unset = the provider's own "
                    "default (`high` on Anthropic). Dropped with a warning on a provider that does "
                    "not declare support, the same way `thinking` is.")


class ModelSettings(_Section):
    analyze: str | None = Field(default=None, description="Judgment: fit + ranking per JD. The expensive one.")
    extract: str | None = Field(default=None, description="Mechanical: job links out of an email.")
    prefilter: str | None = Field(default=None, description="Cheap screen: is this worth an analyze call?")
    cv_parse: str | None = Field(default=None, description="Mechanical: a posting into the keyword/pitch "
                                                           "brief a tailored CV is written against.")
    cv_review: str | None = Field(default=None, description="Judgment: grades a rendered CV against that "
                                                            "brief as a screener would. Sees only the two.")


class PrefilterSettings(_Section):
    enabled: bool | None = Field(default=None, description="Master switch for both cheap gates.")
    screen: bool | None = Field(default=None, description="The model gate specifically; the regex rules stay.")


class PrecedentSettings(_Section):
    enabled: bool | None = Field(default=None, description="Inject similar past decisions when scoring.")
    k: int | None = Field(default=None, ge=0, le=20,
                          description="How many past decisions are injected. This is the per-job token "
                                      "bill, so the ceiling is low on purpose.")


class DedupSettings(_Section):
    enabled: bool | None = None
    similarity: float | None = Field(default=None, ge=0.0, le=1.0,
                                     description="Cosine floor. A cosine is bounded; anything outside "
                                                 "0–1 is a typo that would collapse every job or none.")
    overlap: float | None = Field(default=None, ge=0.0, le=1.0,
                                  description="Word-5-gram Jaccard floor on the JD text — the safety gate.")
    min_jd_chars: int | None = Field(default=None, ge=0,
                                     description="Below this there is too little text to compare.")


class LivenessSettings(_Section):
    enabled: bool | None = None
    max_check: int | None = Field(default=None, ge=0,
                                  description="How many ranked jobs get an availability request. 0 = none.")
    workers: int | None = Field(default=None, ge=1, le=64,
                                description="Parallel network waits. Above ~64 you are DoSing a job board.")


class ChannelSettings(_Section):
    enabled: bool | None = Field(default=None, description="Omitted means ON — see triage/config.py.")


class BoardsChannelSettings(ChannelSettings):
    greenhouse: list[str] | None = Field(
        default=None, description="Greenhouse board tokens — the slug in job-boards.greenhouse.io/<token>.")
    lever: list[str] | None = Field(
        default=None, description="Lever board tokens — the slug in jobs.lever.co/<token>.")


class AgenciesChannelSettings(ChannelSettings):
    sources: list[str] | None = Field(
        default=None,
        description="Which agency scrapers to read, from core/scrapers/AGENCIES: insightglobal, "
                    "teksystems, motion, mondo, apex, kore1. Omitted or empty means the four measured "
                    "healthy on 2026-07-22 (triage/channels/agencies.py:DEFAULT_SOURCES) — apex and "
                    "kore1 are out because they return single digits with no error, which is this "
                    "family's silent-zero failure. An unknown name is warned about, not fatal, "
                    "because a scraper can be retired between releases.")


# An OEWS area: `N` + seven zeroes for the nation, `M` + a 7-digit CBSA code for a metro. Validated
# here because a typo produces no error at BLS — the series id simply matches nothing and the metro
# anchor vanishes from the report, which reads as "BLS returned nothing" rather than as a bad code.
BLSArea = Annotated[str, Field(pattern=r"^[NMS][0-9]{7}$")]


class ReportSettings(_Section):
    """The market report (`python -m research.market`) — a monthly command, not part of the daily run."""
    external: bool | None = Field(
        default=None,
        description="Pull the keyless external baselines (GSA CALC+, BLS OEWS). False makes the run "
                    "first-party only, with no network at all — the external half then renders as a "
                    "labelled gap rather than silently shrinking the report.")
    supply: bool | None = Field(
        default=None,
        description="Also pull the third-party job feeds for per-source counts. Off by default "
                    "because it is minutes rather than seconds: Adzuna alone fetches a detail page "
                    "per posting, and Himalayas pages 50 times for ~100 developer rows.")
    top_terms: int | None = Field(
        default=None, ge=0, le=200,
        description="How many clustered ideas each free-text section lists. The report is already "
                    "~230 lines at 30; this is the knob that makes it longer or shorter.")
    top_employers: int | None = Field(
        default=None, ge=0, le=200, description="How many employers the who's-hiring tables list.")
    bls_areas: dict[str, BLSArea] | None = Field(
        default=None,
        description="OEWS areas the wage baseline is drawn for, as name -> area code (`N0000000` is "
                    "the nation, `M0019100` is Dallas-Fort Worth). The default ships national + DFW "
                    "because this repo's profile is written around remote/DFW; a stranger's metro is "
                    "an edit here rather than a patch to research/sources/bls.py.")


class ChannelsSettings(_Section):
    """The five registered job-input channels, named.

    Naming them here means a misspelled `mial:` fails rather than switching nothing, which is the same
    silent failure as a misspelled scalar key. The cost is that registering a fifth channel is an edit
    in two places — `triage/channels.ALL` and here — and `triage/test_channels.py` asserts the two
    agree, so the drift fails a test in the package that owns the registry rather than passing review.
    """
    mail: ChannelSettings | None = None
    boards: BoardsChannelSettings | None = None
    agencies: AgenciesChannelSettings | None = None
    paste: ChannelSettings | None = None
    gmail: ChannelSettings | None = None


class Settings(_Section):
    """`config/settings.yaml` — how the tool runs. Identity is in `profile/`, secrets are in `.env`."""
    llm: LLMSettings | None = None
    models: ModelSettings | None = None
    window_days: int | None = Field(default=None, ge=1, le=365,
                                    description="How far back to read the inbox / how fresh a posting "
                                                "must be. Days, so 0 would mean no jobs at all.")
    prefilter: PrefilterSettings | None = None
    precedent: PrecedentSettings | None = None
    dedup: DedupSettings | None = None
    max_workers: int | None = Field(default=None, ge=1, le=64,
                                    description="Fetch+analyze concurrency. Network-bound, so this is "
                                                "the dominant runtime lever; too high earns 429s.")
    liveness: LivenessSettings | None = None
    channels: ChannelsSettings | None = None
    report: ReportSettings | None = None


CHANNEL_NAMES = tuple(ChannelsSettings.model_fields)


def _known_siblings(loc: tuple) -> list[str]:
    """The field names valid at `loc`'s level, for the did-you-mean line. `[]` if the path isn't a model."""
    model: type[BaseModel] | None = Settings
    for step in loc[:-1]:
        if model is None or not isinstance(step, str):
            return []
        field = model.model_fields.get(step)
        model = next((a for a in getattr(field.annotation, "__args__", (field.annotation,))
                      if isinstance(a, type) and issubclass(a, BaseModel)), None) if field else None
    return list(model.model_fields) if model else []


def validate(data: dict, path: Path = SETTINGS_PATH) -> dict:
    """`data` back unchanged, or a `ConfigurationError` naming every key that is wrong and why.

    Returns the plain dict rather than the model. The accessors in `triage/config.py` and the reader in
    `core/llm.py` have always spoken dict-with-a-default, and swapping them for attribute access would
    be a rewrite of 20 call sites to gain nothing — the validation has already happened by then.

    The message is the deliverable. A stranger's typo has to read as *their* typo, at a line they can
    find, not as a KeyError three frames into a package they didn't install.
    """
    try:
        Settings.model_validate(data)
    except ValidationError as e:
        lines = []
        for err in e.errors():
            loc = err["loc"]
            dotted = ".".join(str(p) for p in loc)
            if err["type"] == "extra_forbidden":
                near = get_close_matches(str(loc[-1]), _known_siblings(loc), n=1, cutoff=0.6)
                hint = f" Did you mean `{near[0]}`?" if near else ""
                lines.append(f"  {dotted} — unknown setting.{hint}")
            else:
                lines.append(f"  {dotted} — {err['msg']} (got {err.get('input')!r})")
        raise ConfigurationError(
            f"{path} is not valid:\n" + "\n".join(lines)
            + f"\nThe full list of settings, machine-readable, is {SCHEMA_PATH}."
        ) from e
    return data


@lru_cache(maxsize=1)
def settings() -> dict:
    return validate(load(SETTINGS_PATH))


#: WHICH MODEL EACH ROLE RUNS ON, when the settings file does not say. This is the tool's
#: recommendation, and it is a fact about the code rather than a preference of whoever is using it —
#: so it lives here, once, and not in any settings file.
#:
#: It used to live in the settings file only: `model()` was the ONE accessor with no fallback, so
#: every settings file had to spell all five ids out, which meant `config/example/settings.yaml`
#: carried a second copy of them. The two drifted (2026-07-29: the owner moved `analyze` to Sonnet on
#: cost and the example stayed on an older Opus, shipping every new user an expensive default nobody
#: had chosen) and the only thing watching for it was a manual "diff these two files" step in the
#: publish checklist. `core/test_settings.py` now asserts the example states no model ids at all.
#:
#: Sonnet for the four cheap/mechanical roles; Opus for `cv_review` alone, which grades a rendered CV
#: the way a screener would and is the one judgement call worth the money on a first run.
DEFAULT_MODELS = {
    "analyze": "claude-sonnet-5",
    "extract": "claude-sonnet-5",
    "prefilter": "claude-sonnet-5",
    "cv_parse": "claude-sonnet-5",
    "cv_review": "claude-opus-5",
}


#: Top-level settings the shipped example must NOT name, because the code owns them. Asserted by
#: `core/test_example.py`; it lives here rather than in a test so both tests import it from the module
#: that owns the fact, rather than one test importing another.
OWNED_BY_CODE = frozenset({"models"})


def model(role: str) -> str:
    """The model id for one role — the settings file if it names one, otherwise `DEFAULT_MODELS`.

    Every caller in both leaves goes through here, so a provider switch or a new default is one edit.
    An unknown role is a programming error and says so: the roles are a fixed set, not user input.
    """
    if role not in DEFAULT_MODELS:
        raise KeyError(f"unknown model role {role!r} — known roles: {', '.join(sorted(DEFAULT_MODELS))}")
    configured = (settings().get("models") or {}).get(role)
    return str(configured) if configured else DEFAULT_MODELS[role]


def schema_json() -> str:
    """The model as JSON Schema — `config/settings.schema.json`'s exact contents."""
    schema = Settings.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "jobs-db settings (config/settings.yaml)"
    schema["description"] = (
        "How the tool runs. Generated from core/settings.py by `python -m core.settings` — edit the "
        "model, not this file. This and profile/ are the agent-editable surface of the repo; "
        "everything else is code. The scoring rubric (profile/rubric.md) is prose and has no schema."
    )
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":   # pragma: no cover - the regenerate command, also exercised by the test
    SCHEMA_PATH.write_text(schema_json(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
