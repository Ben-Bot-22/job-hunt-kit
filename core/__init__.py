"""Core — the shared layer every leaf package stands on.

`core/` holds what more than one tool needs: the `Job` model, the JD-fetching chain, and the
retrieval core over the scored corpus. It is the bottom of the stack, so the rule is one-directional:

    leaves (`triage/`, `research/`, `cv/`) may import `core/`;
    leaves never import each other; `core/` imports nothing local.

That rule is enforced by `core/test_layering.py`, not by good intentions — a leaf that needs a
sibling's code is telling you that code belongs here.
"""
__version__ = "0.1.0"
