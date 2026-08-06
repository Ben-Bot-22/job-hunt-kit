"""Triage — a manually-run daily job-triage tool built alongside jobs-db (but separate from it).

Reads Ben's Gmail (via Apple Mail), follows the job links inside, scrapes each full job description,
analyzes it against Ben's goals with Claude (Opus 4.8), and writes a ranked markdown worklist.

Leaf package: it imports `core/` (the `Job` model, the JD-fetch chain) and nothing from another leaf —
see CLAUDE.md → Code layout. Entry point: `python -m triage`. See README.md and
docs/knowledge-base/plan-triage-build.md.
"""
__version__ = "0.1.0"
