"""The repo's workflows, asserted as portable artifacts rather than as prose.
Run:  .venv/bin/python -m pytest core/test_portable_workflows.py -q

Five workflows here are documents an agent reads. Whether *your* agent can read them is decided by
three mechanical facts — the file format, the path, and the instruction file — and each one fails
silently, in a client nobody in this repo is running at the time.

The failure directions, in the order they cost something:

  * **A workflow reappearing as a slash command.** `.claude/commands/*.md` is readable by exactly one
    client and portable to none: every other agent's custom-prompt format is user-level and explicitly
    not shared through a repository. The conversion to skills was free and one convenient new file
    undoes it for that workflow only, which is the version nobody notices.
  * **`.agents/skills` stopping being a committed symlink.** Some clients read `.claude/skills/`, some
    read `.agents/skills/`, and the spec fixes neither. If it is not in git it closed the gap on one
    machine; if someone "fixes" it into a real directory, the five workflows exist twice and the copy
    is the one that rots.
  * **Instructions drifting back into `CLAUDE.md`.** `AGENTS.md` is the source of truth and Claude
    Code does **not** read it natively — the `@AGENTS.md` import is load-bearing, and prose written
    beside it is prose only one client sees.
  * **Own and vendored skills becoming indistinguishable.** `.claude/skills/` holds this repo's
    product *and* twenty vendored third-party skills. The extraction allowlist ships the first set and
    must redistribute none of the second, and it decides which is which by `skills-lock.json`. A
    vendored skill with no lock entry would ship; one of ours gaining an entry would be dropped from
    the public repo.

No network, no git required for anything but the one symlink-in-index check, which skips cleanly.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "Workflows are Agent Skills under `.claude/skills/`; no `.claude/commands/` directory exists."
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"
LOCK = ROOT / "skills-lock.json"
README = ROOT / "README.md"

#: This repo's own workflows — the product, as against the vendored engineering skills.
OWN = ("setup", "job-triage", "research-company", "sync-applied", "tailor-cv",
       "tailor-cv-batch", "publish", "cover-letter", "evaluate-role", "apply-form")


def _frontmatter(skill: Path) -> dict[str, str]:
    """The `key: value` lines of a SKILL.md's leading `---` block. Values are not parsed further."""
    lines = skill.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{skill.relative_to(ROOT)} has no frontmatter block"
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    raise AssertionError(f"{skill.relative_to(ROOT)} frontmatter is never closed")


def _vendored() -> set[str]:
    return set(json.loads(LOCK.read_text(encoding="utf-8"))["skills"])


def test_the_five_workflows_ship_as_skills() -> None:
    """A skill needs a `name` matching its directory, or `/<name>` invokes something else or nothing."""
    for name in OWN:
        skill = SKILLS / name / "SKILL.md"
        assert skill.is_file(), f"{name} is not a skill: {skill.relative_to(ROOT)} is missing"
        fields = _frontmatter(skill)
        assert fields.get("name") == name, f"{name}: frontmatter name is {fields.get('name')!r}"
        assert fields.get("description"), f"{name}: a skill with no description is never selected"


def test_no_workflow_is_a_slash_command() -> None:
    """Slash commands are the dead end — one client, and not shareable anywhere else."""
    commands = ROOT / ".claude" / "commands"
    stragglers = sorted(p.name for p in commands.glob("*.md")) if commands.is_dir() else []
    assert not stragglers, (
        f".claude/commands/ is a dead end; these belong in .claude/skills/<name>/SKILL.md: {stragglers}"
    )


def test_the_alternate_skills_path_is_a_symlink_to_the_real_one() -> None:
    """The whole cross-agent gap, and it is 17 bytes. A copied directory would be two of everything."""
    alt = ROOT / ".agents" / "skills"
    assert alt.is_symlink(), ".agents/skills must be a symlink, not a directory or a copy"
    assert alt.resolve() == SKILLS.resolve()
    assert (alt / "setup" / "SKILL.md").is_file(), "the symlink does not resolve to readable skills"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_symlink_is_committed_as_a_symlink() -> None:
    """Mode 120000 in the index. Anything else means the gap is closed on one machine only."""
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    entry = subprocess.run(
        ["git", "ls-files", "-s", ".agents/skills"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert entry.startswith("120000 "), f"expected a committed symlink, git says: {entry.strip()!r}"


def test_agents_md_is_the_source_of_truth_and_claude_md_is_a_stub() -> None:
    """Claude Code does not read AGENTS.md natively, so the import is the only thing joining them."""
    assert (ROOT / "AGENTS.md").is_file(), "AGENTS.md is the source of truth and it is missing"
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@AGENTS.md" in claude, "CLAUDE.md must import AGENTS.md — Claude Code will not find it otherwise"
    # Measured on the live content, not on file size: an HTML comment explaining the stub is fine,
    # a paragraph of instructions beside the import is the drift this test exists to catch.
    live = [ln for ln in re.sub(r"(?s)<!--.*?-->", "", claude).splitlines() if ln.strip()]
    assert len(live) <= 3, f"CLAUDE.md is growing instructions of its own: {live}"


@pytest.mark.skipif(
    not LOCK.exists(),
    reason="skills-lock.json is private (EXCLUDED from extraction); a clone has neither it nor the vendored skills")
def test_own_and_vendored_skills_are_told_apart_by_the_lock_file() -> None:
    """The rule the extraction allowlist uses: vendored iff the directory is a key in skills-lock.json."""
    present = {p.name for p in SKILLS.iterdir() if p.is_dir()}
    vendored = _vendored()
    assert set(OWN) <= present, f"missing skills: {sorted(set(OWN) - present)}"
    assert set(OWN).isdisjoint(vendored), (
        f"these are ours but are locked as vendored, so extraction would drop them: "
        f"{sorted(set(OWN) & vendored)}"
    )
    assert present - vendored == set(OWN), (
        f"unclassifiable skills — neither ours nor locked as vendored: {sorted(present - vendored - set(OWN))}"
    )
