"""The legal furniture, asserted as files rather than as intentions.
Run:  .venv/bin/python -m pytest core/test_licensing.py -q

Three facts about this repo are decided by whether a file exists and what it names, and all three
fail silently — nothing in the pipeline reads any of them, so a wrong answer surfaces only when
somebody outside the project reads it, which is exactly too late.

The failure directions, in the order they cost something:

  * **A `CONTRIBUTING.md` appearing.** The contribution policy is three sentences in the README on
    purpose: a dedicated contribution file signals a maintained project taking submissions, which is
    the expectation the fork-first policy exists to avoid setting. It is the kind of file a helpful
    agent adds unprompted.
  * **`NOTICE` drifting behind `research/sources/`.** Attribution is a terms-of-use obligation, and
    a new source that stamps an `ATTRIBUTION` line onto its records incurs one. The code enforces
    the line on each *record*; nothing but this test connects that to the document a reader checks.
  * **`LICENSE` going missing or losing its grant.** MIT is the whole permission story; an
    unlicensed public repo is "all rights reserved" by default, which is the opposite of the point.

Pure file reads — no network, no key, no git. `research/sources/` is read as *text* rather than
imported, because `core/` may not import a leaf (`core/test_layering.py`).
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "Every attributed source reaches both the registry and `NOTICE`, and no `CONTRIBUTING.md` exists."
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSE = ROOT / "LICENSE"
NOTICE = ROOT / "NOTICE"
README = ROOT / "README.md"
SOURCES = ROOT / "research" / "sources"

#: A module-level `ATTRIBUTION = "..."` is how a source declares that its terms require naming it.
_ATTRIBUTION = re.compile(r"^ATTRIBUTION\s*=\s*\(?\s*[\"']", re.MULTILINE)


def _attribution_bearing_sources() -> set[str]:
    """Every module in `research/sources/` that declares an attribution obligation, by module name."""
    return {
        path.stem
        for path in sorted(SOURCES.glob("*.py"))
        if not path.stem.startswith("_") and _ATTRIBUTION.search(path.read_text(encoding="utf-8"))
    }


def test_the_licence_is_mit_and_grants_the_mit_rights() -> None:
    """A public repo with no licence grants nothing. The grant clause is the load-bearing sentence."""
    text = LICENSE.read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Permission is hereby granted, free of charge" in text
    assert "WITHOUT WARRANTY OF ANY KIND" in text


def test_notice_names_every_source_that_requires_attribution() -> None:
    """A new attributed source has to reach the document as well as the record it stamps.

    The enforcement lives in `research/sources/__init__.py`, which drops a record arriving without
    its line — so the *data* can never go out unattributed. This is the other half: the reader-facing
    inventory, which nothing drops and nothing notices going stale.
    """
    notice = NOTICE.read_text(encoding="utf-8").lower()
    missing = sorted(name for name in _attribution_bearing_sources() if name not in notice)
    assert not missing, (
        f"NOTICE does not name {missing} — each declares ATTRIBUTION in research/sources/ and its "
        f"terms require naming it wherever its data appears."
    )


def test_notice_states_the_per_user_key_rule() -> None:
    """Keys are the user's own, under the provider's terms. Nothing here ships, proxies or shares one."""
    notice = NOTICE.read_text(encoding="utf-8")
    assert "Per-user API keys only" in notice
    assert "gitignored" in notice


def test_there_is_no_contributing_file() -> None:
    """The policy is three sentences in the README, and the absence of this file is part of it."""
    assert not (ROOT / "CONTRIBUTING.md").exists(), (
        "CONTRIBUTING.md signals a maintained project taking submissions. The policy is fork-first, "
        "issues welcome, PRs by exception — stated in the README under 'Forks, issues and pull "
        "requests'. Edit that section instead."
    )
