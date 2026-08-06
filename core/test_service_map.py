"""The two orientation pages, checked against the tree they claim to describe.
Run:  .venv/bin/python -m pytest core/test_service_map.py -q

`docs/operating/services.md` and `docs/operating/data-map.md` exist so a reader does not have to read
the source to learn what this tool talks to and what it writes. That only holds while they are true,
and both fail in a way nobody sees: a channel is added and the services table still lists four, a
market source is renamed and the page names a module that is gone, `data/` grows a fifth
subdirectory and the delete advice quietly stops covering it. Nothing in the pipeline reads either
file, so a wrong answer surfaces when a stranger deletes the wrong directory.

**The check runs in both directions on purpose.** A page missing a real channel is the dangerous
direction (a reader concludes it does not exist); a page naming a channel that is gone is the
embarrassing one. Either fails here.

What this deliberately does not check: prose, costs, timings, or the failure descriptions — those are
judgments and a test over them would be satisfied by filler. It checks *inventories*, which are facts.

Read as text and filesystem listings rather than by importing `triage`/`research`, because `core/`
may not import a leaf (`core/test_layering.py`). No network, no key.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "`systems.md`, `services.md` and `data-map.md` name every system, workflow, channel, source, scraper, provider and directory the tool actually has."
import re
from pathlib import Path

from core.llm import PROVIDERS

ROOT = Path(__file__).resolve().parent.parent
SYSTEMS = ROOT / "docs" / "operating" / "systems.md"
SERVICES = ROOT / "docs" / "operating" / "services.md"
DATA_MAP = ROOT / "docs" / "operating" / "data-map.md"
README = ROOT / "README.md"

#: `data/corpus/...` in the doc, and `DATA_DIR / "corpus"` in `triage/config.py`.
_DATA_SUBDIR_IN_DOC = re.compile(r"`data/([a-z_]+)/")
_DATA_SUBDIR_IN_CODE = re.compile(r"DATA_DIR\s*/\s*\"([a-z_]+)\"")


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([^`\n]+)`", text))


def test_every_input_channel_is_in_the_services_table() -> None:
    """Both directions over `triage/channels/`. A new channel that reaches jobs without reaching this
    page is the failure that matters: a reader concludes the tool cannot read that source at all."""
    modules = {p.stem for p in (ROOT / "triage" / "channels").glob("*.py")}
    modules -= {"__init__", "common"}
    # The registered name is `gmail`; the module is `gmail_api` because `gmail.py` beside a `gmail`
    # config key invited exactly the confusion the stub exists to avoid.
    documented = {c for c in ("paste", "boards", "agencies", "mail", "gmail")
                  if f"`{c}`" in SERVICES.read_text(encoding="utf-8")}
    assert documented == {m.removesuffix("_api") for m in modules}, (
        "docs/operating/services.md §3 and triage/channels/ disagree about which channels exist"
    )


def test_every_market_source_and_scraper_is_named() -> None:
    """`research/sources/` and `core/scrapers/` against the services page.

    The scrapers are named in both files' terms — they are market supply *and* job input — so a
    rename has two documents to break, and this is the one that says so."""
    text = SERVICES.read_text(encoding="utf-8").lower()
    sources = {p.stem for p in (ROOT / "research" / "sources").glob("*.py")
               if not p.stem.startswith("_")}
    scrapers = {p.stem for p in (ROOT / "core" / "scrapers").glob("*.py")
                if p.stem not in {"__init__", "jsonld", "posting"}}
    # Module stems are one word; the page names them as a reader would ("GSA CALC+", "Insight
    # Global"), so the check is on the stem's letters with separators removed.
    for name in sorted(sources | scrapers):
        assert name in text.replace(" ", "").replace("+", "").replace("-", ""), (
            f"{name} is a live source/scraper and docs/operating/services.md does not name it"
        )
    assert len(scrapers) == 7, "the rot baseline in services.md §3 is written for seven scrapers"


def test_every_registered_provider_is_tiered_on_the_page() -> None:
    """A provider added to `core/llm.py` without a row here makes an untested tier look tested."""
    text = SERVICES.read_text(encoding="utf-8")
    for name in sorted(PROVIDERS):
        assert f"`{name}`" in text, f"{name} is registered in core/llm.py and is not in services.md §1"
    assert "tested" in text and "untested" in text, "the honest tiering is the point of §1"


def test_every_entry_point_in_the_run_table_exists() -> None:
    """`python -m X` in §7 must name a module with a `__main__`, and a script path must be a file.

    Failure direction: a page telling a stranger to run something that is not there — the single
    thing the cold-clone check exists to catch, made cheap and offline for the common case."""
    text = SERVICES.read_text(encoding="utf-8")
    for module in sorted(set(re.findall(r"python -m ([a-z_.]+)", text))):
        parts = module.split(".")
        target = ROOT.joinpath(*parts)
        assert (target.with_suffix(".py").exists() or (target / "__main__.py").exists()), (
            f"services.md §7 names `python -m {module}` and no such entry point exists"
        )
    for script in sorted(s for s in _backticked(text) if s.startswith("python cv/")):
        path = ROOT / script.split()[1]
        assert path.exists(), f"services.md §7 names {path} and it does not exist"


def test_the_data_map_covers_every_directory_the_tool_creates() -> None:
    """`triage/config.py` makes its directories on import; the map must account for all of them.

    The corpus-survives-cleanup rule is only safe advice while the list is complete — a fifth
    subdirectory under `data/` that nobody documented is one a reader will delete or preserve by
    guesswork."""
    doc = DATA_MAP.read_text(encoding="utf-8")
    code = (ROOT / "triage" / "config.py").read_text(encoding="utf-8")
    created = set(_DATA_SUBDIR_IN_CODE.findall(code))
    assert created, "triage/config.py no longer derives its data directories from DATA_DIR"
    assert created <= set(_DATA_SUBDIR_IN_DOC.findall(doc)), (
        f"docs/operating/data-map.md does not cover data/{sorted(created - set(_DATA_SUBDIR_IN_DOC.findall(doc)))}"
    )
    for path in ("matches/", "applications/", "profile/", "config/settings.yaml", ".env"):
        assert path in doc, f"data-map.md must say what {path} is and whether losing it costs anything"
    # The one rule the page exists to make unmissable.
    assert "disposable" in doc and "data/corpus/" in doc


def test_the_systems_map_names_every_package_and_every_workflow() -> None:
    """`systems.md` is loaded every session (`CLAUDE.md` imports it), so a gap in it misdirects work.

    It answers "which system am I in, and what is its anchor?" — the question the other two pages do
    not. That only holds while it is complete: a package it does not name is a capability an agent
    concludes does not exist, and a workflow it omits is one that gets rebuilt beside itself. Both
    have happened here.

    Inventories only. The prose, the diagram and the seams are judgments and a test over them would
    be satisfied by filler.
    """
    from core.test_portable_workflows import OWN  # the single list of this repo's own workflows

    text = SYSTEMS.read_text(encoding="utf-8")
    ticks = _backticked(text)

    packages = sorted(
        p.name for p in ROOT.iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and not p.name.startswith(".")
    )
    assert packages, "no Python packages found at the repo root — has the layout changed?"
    for pkg in packages:
        assert any(t == pkg or t.startswith(f"{pkg}/") for t in ticks), (
            f"docs/operating/systems.md never names the `{pkg}/` package. Every system and the shared "
            f"floor under them belong on the map — see its §1 table."
        )

    for skill in OWN:
        assert f"/{skill}" in text, (
            f"docs/operating/systems.md does not name the /{skill} workflow. A workflow missing from "
            f"the map is one an agent rebuilds beside itself."
        )

    for anchor in ("profile/rubric.md", "profile/bullet-bank.md", "config/settings.yaml"):
        assert anchor in text, f"systems.md must name {anchor} as the anchor of the system that reads it"


def test_all_three_pages_are_reachable_from_the_readme() -> None:
    """A doc nobody links is a doc nobody reads; the README is the only front door a stranger has."""
    readme = README.read_text(encoding="utf-8")
    for page in ("docs/operating/systems.md", "docs/operating/services.md", "docs/operating/data-map.md"):
        assert page in readme, f"{page} is not linked from the README"
