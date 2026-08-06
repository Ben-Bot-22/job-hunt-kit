"""The docs layout, asserted as directories rather than as a convention.
Run:  .venv/bin/python -m pytest core/test_docs_layout.py -q

There is exactly one place reasoning is written down — `docs/knowledge-base/` — and the failure mode
is not that someone deletes it. It is that a *second* place quietly reappears and the answer to "where
does the why go?" becomes "three places, pick one", which is the state this folder replaced on
2026-07-30.

The two directions this fails in, in the order they have actually happened:

  * **`docs/adr/` or `docs/research/` coming back.** Both existed until 2026-07-30 and both were
    folded into the knowledge base. `.claude/skills/domain-modeling/` is a vendored third-party skill
    that creates `docs/adr/` lazily when it writes its first decision record — it has never run here
    (there is no root `CONTEXT.md`), but it is one invocation away, and it cannot be edited without
    drifting from the upstream copy `skills-lock.json` pins. So the split is prevented here instead.
  * **A file landing in the knowledge base whose name says nothing.** The folder is deliberately flat,
    which only works while the filename carries the kind. Four prefixes, no numbering, no acronyms.

What this test deliberately does NOT check: whether a `.scratch/` ticket is secretly documentation.
That is the other half of the same rule and it is not mechanically detectable — it stays a written
rule in `AGENTS.md` and the knowledge base README rather than being pretended into a test.

Pure file reads — no network, no key, no git.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "Reasoning has one home, `docs/knowledge-base/`; it is flat apart from `personal/`, and the filename prefix carries the kind."
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "docs" / "knowledge-base"

#: The only filename shapes allowed in the knowledge base. The prefix IS the taxonomy — it is what a
#: subfolder would otherwise have told you, in a folder that is flat on purpose.
_PREFIXES = ("decision-", "research-", "plan-")
_EXACT = {"README.md", "log.md"}


def test_the_knowledge_base_exists_and_explains_itself() -> None:
    """The folder, its rule, and the running log. Without the README it becomes a junk drawer."""
    assert KB.is_dir(), "docs/knowledge-base/ is where notes, findings and decisions live"
    assert (KB / "README.md").is_file(), "the knowledge base must state its own rule at the door"
    assert (KB / "log.md").is_file(), "log.md is the running record of what changed and why"


def test_no_second_home_for_reasoning_has_reappeared() -> None:
    """`docs/adr/` and `docs/research/` were folded in on 2026-07-30 and must not come back.

    If this fails: move the file into `docs/knowledge-base/` with a `decision-` or `research-` prefix
    and delete the directory. Do not delete this test — the split it prevents is the whole reason the
    knowledge base exists.
    """
    for gone in ("adr", "research"):
        stray = ROOT / "docs" / gone
        assert not stray.exists(), (
            f"docs/{gone}/ is back. Reasoning lives in docs/knowledge-base/ only — move the "
            f"file there (decision-<slug>.md or research-<slug>.md) and remove the directory."
        )


def test_every_knowledge_base_file_says_what_it_is() -> None:
    """A flat folder only stays navigable while the filename carries the kind."""
    stray = [
        p.name for p in KB.glob("*.md")
        if p.name not in _EXACT and not p.name.startswith(_PREFIXES)
    ]
    assert not stray, (
        f"{stray} do not name their kind. Knowledge-base files are README.md, log.md, or start with "
        f"{', '.join(_PREFIXES)} — see docs/knowledge-base/README.md."
    )


#: The one subfolder the knowledge base is allowed. It holds the owner's decision-support material —
#: job-search strategy, market positioning, call prep — which is documentation and belongs with the
#: documentation, but is personal and must never ship. `scripts/extract.py` excludes it by name
#: (`PERSONAL_SUBTREES`) and `scripts/test_leaks.py` reads that same definition.
_PERSONAL_SUBDIR = "personal"


def test_the_knowledge_base_is_flat_apart_from_the_personal_subtree() -> None:
    """Flat on purpose: one place to look, and the prefix does the sorting a folder would.

    The single exception is `personal/`, which is not a category — it is the privacy seam. Its
    contents are the owner's and are pruned from the public snapshot; everything else here ships.
    A second subfolder means the prefix convention has been abandoned, so it still fails.
    """
    subdirs = [p.name for p in KB.iterdir() if p.is_dir() and p.name != _PERSONAL_SUBDIR]
    assert not subdirs, (
        f"docs/knowledge-base/ is flat by design; found subfolder(s) {subdirs}. Use a filename "
        f"prefix instead — `personal/` is the one exception and it is the privacy seam, not a topic."
    )
