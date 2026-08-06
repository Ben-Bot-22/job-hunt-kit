"""The tuning reference, checked against the code it describes.
Run:  .venv/bin/python -m pytest core/test_tuning.py -q

`docs/operating/tuning.md` is the only place the *reasoning* behind ~70 measured constants survives —
what each one trades, and what you would see in the output if it were wrong. A document like that has
exactly one failure mode, and it is silent: the code moves, the page does not, and a reader tunes a
number that no longer exists or trusts a value the code stopped using. Nothing in the pipeline reads
the page, so nothing else would ever notice.

So the page carries its own machine-readable spine. Every knob is written as `` `file` · `NAME` = value ``
and this test resolves each one:

  * **a module constant must still exist in the file the page names.** Failure direction: a rename or a
    deletion leaves the page describing a knob nobody can find, which is worse than no page at all
    because it reads as current.
  * **a code-side value must still match the code.** Failure direction: a constant is retuned in a
    commit that does not touch the page, and the measurement recorded beside it — "4 workers got 12 of
    25 pages 403'd; 3 at 1.0 s got 0" — silently becomes a claim about a value nobody is running.
    Retuning is therefore a two-file change on purpose.
  * **a `config/settings.yaml` key must still be declared in the settings model.** Values there are
    *not* pinned: that file is the documented configuration surface and editing it is the normal case,
    so pinning it would fail the suite on legitimate config work.

Read as text, never imported — `core/` may not import a leaf (`core/test_layering.py`), and half the
knobs live in `triage/` and `research/`. Pure file reads: no network, no key, no model.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "`tuning.md` still describes the numbers the code actually uses."
import re
from pathlib import Path

from pydantic import BaseModel

from .settings import Settings

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "operating" / "tuning.md"
README = ROOT / "README.md"

#: `` `research/sources/adzuna.py` · `DETAIL_WORKERS` = 3 `` — the page's own notation, wherever it
#: appears: a heading, a table cell or a sentence. The value is optional and only pinned when numeric.
_KNOB = re.compile(
    r"`(?P<file>[A-Za-z0-9_./]+\.(?:py|yaml))`\s*·\s*`(?P<name>[A-Za-z_][A-Za-z0-9_.]*)`"
    r"(?:\s*=\s*(?P<value>[^\s|`]+))?"
)

SETTINGS_FILE = "config/settings.yaml"


def _knobs() -> list[re.Match]:
    text = DOC.read_text(encoding="utf-8")
    found = list(_KNOB.finditer(text))
    assert found, f"{DOC} names no knobs in the `file` · `NAME` form — the page or the notation moved."
    return found


def _field_type(model: type[BaseModel], name: str) -> type[BaseModel] | None:
    """The nested settings model behind `name`, unwrapping `X | None`. `None` if it isn't one."""
    field = model.model_fields.get(name)
    if field is None:
        return None
    candidates = getattr(field.annotation, "__args__", (field.annotation,))
    return next((a for a in candidates if isinstance(a, type) and issubclass(a, BaseModel)), None)


def _settings_key_exists(dotted: str) -> bool:
    model: type[BaseModel] | None = Settings
    steps = dotted.split(".")
    for step in steps[:-1]:
        model = _field_type(model, step) if model else None
        if model is None:
            return False
    return bool(model and steps[-1] in model.model_fields)


def test_every_documented_constant_still_exists() -> None:
    """A knob named on the page must be findable in the file the page sends you to."""
    missing = []
    for m in _knobs():
        path, name = ROOT / m["file"], m["name"]
        if m["file"] == SETTINGS_FILE:
            if not _settings_key_exists(name):
                missing.append(f"{m['file']} · {name} — not a field in core/settings.py:Settings")
            continue
        if not path.exists():
            missing.append(f"{m['file']} — no such file")
        elif not re.search(rf"\b{re.escape(name)}\b", path.read_text(encoding="utf-8")):
            missing.append(f"{m['file']} · {name} — not in the file")
    assert not missing, (
        "docs/operating/tuning.md describes knobs the code no longer has:\n  "
        + "\n  ".join(missing)
        + "\nFix the page — a tuning reference that names a constant nobody can find reads as current "
          "and is not."
    )


def test_every_documented_code_value_still_matches_the_code() -> None:
    """The measurement beside a number is only true of that number. Retuning includes the page.

    Only code-side knobs, and only where the page states a numeric value: `config/settings.yaml` is the
    configuration surface and its values are meant to be edited without a code change.
    """
    drifted = []
    for m in _knobs():
        value = m["value"]
        if m["file"] == SETTINGS_FILE or not value:
            continue
        try:
            float(value)
        except ValueError:
            continue        # `3days`, `claude-opus-4-8` — a choice, not a measured threshold
        text = (ROOT / m["file"]).read_text(encoding="utf-8")
        # Word-start anchored so `THROTTLE = 1.0` cannot be satisfied by `DETAIL_THROTTLE = 1.0`, and
        # annotation-tolerant so a keyword-only default (`*, timeout: float = 15.0`) matches too.
        assign = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(m['name'])}\s*(?::[^=\n]*)?=\s*"
                            rf"{re.escape(value)}\b")
        if not assign.search(text):
            drifted.append(f"{m['file']} · {m['name']} — the page says {value}, the code does not")
    assert not drifted, (
        "docs/operating/tuning.md quotes values the code has moved past:\n  "
        + "\n  ".join(drifted)
        + "\nRetuning a constant is a two-file change: the number, and the row that says what it "
          "trades and how you would know it is wrong."
    )


def test_the_readme_reaches_the_tuning_page() -> None:
    """It is a reference nobody goes looking for. If it isn't linked, it isn't read."""
    assert "docs/operating/tuning.md" in README.read_text(encoding="utf-8")
