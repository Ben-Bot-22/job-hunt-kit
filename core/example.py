"""`config/example/` — the shipped fictional job seeker, and the one way to copy it into place.

A stranger who has just cloned this repo has no profile, no rubric, no settings and no reason to
believe any of it works. `config/example/` is a complete configuration for someone who does not exist
(Robin Doe — see its README), so the first run can be a real run:

    JOBSDB_CONFIG_HOME=config/example python -m triage --paste <a job URL>

**It earns its place twice.** It is also the fixture the test suite uses, so it is exercised on every
run and cannot quietly rot into a configuration that no longer loads. That is the whole argument for
one directory rather than two: a demo and a fixture that are separate files agree right up until
somebody edits one of them, and the day they stop agreeing is the day the demo breaks for a stranger
and nothing here goes red.

This module is the *seeding* half — what `/setup` calls to turn the example into the user's own
config. It copies rather than symlinks, and **it never overwrites a file that already exists**. The
failure direction that matters is not a stranger's empty clone; it is a configured one, where
`profile/rubric.md` is the most-tuned file in the repo and a helpful `cp -r` is unrecoverable.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .settings import REPO_ROOT

EXAMPLE_DIR = REPO_ROOT / "config" / "example"

# example filename -> where it belongs in a normal (non-`JOBSDB_CONFIG_HOME`) layout. The example holds
# both halves of the config flat in one directory because that is what the env-var override needs; a
# real installation splits them, identity to `profile/` and operations to `config/`.
DESTINATIONS: dict[str, Path] = {
    "profile.yaml": REPO_ROOT / "profile" / "profile.yaml",
    "rubric.md": REPO_ROOT / "profile" / "rubric.md",
    "bullet-bank.md": REPO_ROOT / "profile" / "bullet-bank.md",
    "skiplist.md": REPO_ROOT / "profile" / "skiplist.md",
    "cover-letter.json": REPO_ROOT / "profile" / "cover-letter.json",
    "settings.yaml": REPO_ROOT / "config" / "settings.yaml",
}


def seed(*, example_dir: Path = EXAMPLE_DIR,
         destinations: dict[str, Path] | None = None,
         force: bool = False) -> tuple[list[Path], list[Path]]:
    """Copy the example into place. Returns `(written, skipped)`.

    `skipped` is every destination that already had a file, and skipping is the default: a second run
    of `/setup` on a configured clone must be a no-op that says so, not a restore-to-factory. `force`
    is there for the one caller who has already asked the user and been told yes.

    `example_dir` and `destinations` are injection points for the tests, which seed into `tmp_path`
    rather than over the repo's own tracked profile.
    """
    dest = destinations if destinations is not None else DESTINATIONS
    written: list[Path] = []
    skipped: list[Path] = []
    for name, target in dest.items():
        source = example_dir / name
        if not source.exists():
            raise FileNotFoundError(f"the shipped example is missing {source}")
        if target.exists() and not force:
            skipped.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)
    return written, skipped


def _report(written: list[Path], skipped: list[Path]) -> str:
    lines = [f"  wrote  {p.relative_to(REPO_ROOT)}" for p in written]
    lines += [f"  kept   {p.relative_to(REPO_ROOT)} (already there — not overwritten)" for p in skipped]
    if skipped:
        lines.append("\nNothing existing was touched. Delete a file above and re-run to replace it,"
                     "\nor read config/example/ and edit your own copy by hand.")
    return "\n".join(lines)


if __name__ == "__main__":   # pragma: no cover - the seeding command; `seed()` itself is tested
    print(f"Seeding your config from {EXAMPLE_DIR.relative_to(REPO_ROOT)} (a fictional job seeker):\n")
    print(_report(*seed()))
