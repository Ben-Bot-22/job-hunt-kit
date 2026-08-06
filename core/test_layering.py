"""The layering rule, as a test rather than a comment.

    leaves may import `core/`; leaves never import each other; `core/` imports nothing local.

Parsed with `ast` rather than by importing anything, so the check costs nothing, needs no
dependencies installed, and reports every violation at once instead of dying on the first.

Failure direction that costs something: `research/` growing a second `triage/` import is how the
daily pipeline quietly becomes a library the monthly report depends on. That was the whole reason
`core/` exists, and it is undone by one convenient import line nobody notices in review.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "A leaf may import `core/`; a leaf never imports another leaf; `core/` imports nothing local."
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = "core"
LEAVES = ("triage", "research", "cv")
LOCAL = (CORE,) + LEAVES


def _local_imports(path: Path) -> set[str]:
    """Top-level local package names imported by `path` — absolute and relative alike."""
    source = path.read_text(encoding="utf-8")
    return _local_imports_in(source, path.relative_to(ROOT).parts[0], filename=str(path))


def _local_imports_in(source: str, own_package: str, filename: str = "<test>") -> set[str]:
    """The parse itself, split out so the detector can be exercised on a source string.

    A relative import resolves against the file's own package, so `from .models import Job` inside
    `core/` counts as an import of `core` (self, therefore allowed) rather than of nothing.
    """
    tree = ast.parse(source, filename=filename)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # `from . import x` / `from .models import Job`
                found.add(own_package)
            elif node.module:
                found.add(node.module.split(".")[0])
    return {name for name in found if name in LOCAL}


def _modules(package: str) -> list[Path]:
    return sorted(p for p in (ROOT / package).rglob("*.py") if "__pycache__" not in p.parts)


def test_core_imports_nothing_local() -> None:
    """`core/` is the bottom of the stack: it may import itself and third-party code, nothing else."""
    violations = [
        f"{module.relative_to(ROOT)} imports {sorted(bad)}"
        for module in _modules(CORE)
        for bad in [_local_imports(module) - {CORE}]
        if bad
    ]
    assert not violations, "core/ must import no leaf package:\n" + "\n".join(violations)


def test_no_leaf_imports_another_leaf() -> None:
    """A leaf that needs a sibling's code is telling you that code belongs in `core/`."""
    violations = []
    for leaf in LEAVES:
        for module in _modules(leaf):
            siblings = _local_imports(module) - {CORE, leaf}
            if siblings:
                violations.append(f"{module.relative_to(ROOT)} imports {sorted(siblings)}")
    assert not violations, "leaves must not import each other:\n" + "\n".join(violations)


def test_the_detector_sees_the_violations_it_is_looking_for() -> None:
    """Guard the guard — a checker that can only pass is not a checker.

    The three import spellings a real violation would arrive as: absolute, dotted, and relative.
    """
    source = "import triage\nfrom cv.bullets import pick\nfrom . import cache\nimport httpx\n"
    assert _local_imports_in(source, own_package="research") == {"triage", "cv", "research"}
