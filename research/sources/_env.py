"""The three key-gated sources' credentials, read from the repo-root `.env`.

Read at **call** time, not at import, which is the difference that matters: the old pipeline resolved
`ADZUNA_APP_ID` into a module constant the first time its config was imported, so a test could not
exercise the no-key path without reloading a module, and a key exported after the process started was
invisible. `key("ADZUNA_APP_ID")` is a function for that reason.

`.env` is loaded the way `core/llm.py` and `triage/config.py` load it — explicitly from the repo root,
so the answer doesn't depend on which directory the command was run from.
"""
from __future__ import annotations

import os

from core.settings import REPO_ROOT


def key(name: str) -> str:
    """A credential, or `""` when it isn't set. Never raises — an absent key is a skipped source."""
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    return (os.getenv(name) or "").strip()
