"""The rubric guide, checked against the rubric it explains.
Run:  .venv/bin/python -m pytest core/test_rubric_guide.py -q

`docs/operating/rubric.md` explains `profile/rubric.md` — the file that is the tool's entire
judgment. It cannot be checked against *Ben's* rubric, because that one does not ship and is edited
weekly. It is written instead against `config/example/rubric.md`, which is the rubric a reader
actually has after `python -m core.example`, and that one is a fixture (`triage/test_example.py`)
rather than a working file.

Two failure directions, both silent, because nothing in the pipeline reads the page:

  * **the guide explains a section the example rubric no longer has, or misses one it grew.** The
    section vocabulary is the guide's main claim — that the ALL-CAPS headings are a working structure
    and not an accident — so a drift in either direction makes the page describe a shape nobody is
    running. Checked in both directions on purpose.
  * **a quoted line stops being a quote.** The guide argues from verbatim excerpts (a `CAP AT
    LOW_FIT` entry, the body-shop tell rule, the precedence sentence the retrieval preamble states).
    Reworded upstream, they become the page's own words wearing quotation marks, which is worse than
    a paraphrase because it reads as evidence.

Every `>` blockquote line in the page must therefore still appear in one of the two files it quotes:
`config/example/rubric.md` or `triage/precedent.py`. Both are read as **text** — `core/` may not
import a leaf (`core/test_layering.py`) and the preamble lives in one. Comparison strips `"` and
collapses whitespace, because the preamble is assembled from adjacent string literals and a
line-wrapped quote of it is one continuous sentence on the page and four fragments in the source.

Pure file reads: no network, no key, no model.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "operating" / "rubric.md"
EXAMPLE_RUBRIC = ROOT / "config" / "example" / "rubric.md"
PREAMBLE_SOURCE = ROOT / "triage" / "precedent.py"
README = ROOT / "README.md"
SETUP_SKILL = ROOT / ".claude" / "skills" / "setup" / "SKILL.md"

#: An ALL-CAPS line at the start of a line — how the rubric marks a section, since it carries no
#: markdown at all (it is a prompt, and a `##` would be one more thing for the model to interpret).
_SECTION = re.compile(r"^([A-Z][A-Z ]{2,}[A-Z])", re.M)

#: The guide gives each of those sections an `###` heading of exactly the same name.
_GUIDE_SECTION = re.compile(r"^### ([A-Z][A-Z ]{2,}[A-Z])\s*$", re.M)


def _flat(text: str) -> str:
    return " ".join(text.replace('"', "").split())


def test_the_guide_explains_every_section_of_the_example_rubric():
    """Both directions. A section the guide invented is as bad as one it missed: the first tells a
    reader to write a heading the model was never handed, the second leaves the highest-leverage
    file in the repo with an unexplained block in the middle of it."""
    in_rubric = {m.group(1).strip() for m in _SECTION.finditer(EXAMPLE_RUBRIC.read_text(encoding="utf-8"))}
    in_guide = {m.group(1).strip() for m in _GUIDE_SECTION.finditer(DOC.read_text(encoding="utf-8"))}
    assert in_rubric, f"{EXAMPLE_RUBRIC} has no ALL-CAPS section headings — the rubric's shape moved."
    assert in_rubric == in_guide, (
        f"{DOC} and {EXAMPLE_RUBRIC} disagree about the sections.\n"
        f"  unexplained by the guide: {sorted(in_rubric - in_guide) or 'none'}\n"
        f"  explained but not in the rubric: {sorted(in_guide - in_rubric) or 'none'}"
    )


def test_every_quoted_line_is_still_a_quote():
    """The page's evidence. Failure direction: a rule is reworded in the example rubric or in the
    precedent preamble, and the guide keeps quoting the old wording as if it were current."""
    sources = _flat(EXAMPLE_RUBRIC.read_text(encoding="utf-8") + "\n"
                    + PREAMBLE_SOURCE.read_text(encoding="utf-8"))
    quoted = [ln[2:].strip() for ln in DOC.read_text(encoding="utf-8").splitlines() if ln.startswith("> ")]
    assert quoted, f"{DOC} quotes nothing — the page stopped arguing from the rubric's own words."
    missing = [q for q in quoted if _flat(q) not in sources]
    assert not missing, (
        f"{DOC} quotes lines that no longer appear in {EXAMPLE_RUBRIC.name} or {PREAMBLE_SOURCE.name}:\n  "
        + "\n  ".join(missing)
    )


def test_the_guide_is_reachable_from_the_two_places_a_reader_starts():
    """A doc nobody links is a doc nobody reads, and this one has exactly two entry points: the
    README, for someone evaluating the repo, and `/setup` step 6, which writes a rubric and until now
    handed the user no way to understand it afterwards."""
    for entry in (README, SETUP_SKILL):
        assert "docs/operating/rubric.md" in entry.read_text(encoding="utf-8"), (
            f"{entry.relative_to(ROOT)} no longer links the rubric guide."
        )
