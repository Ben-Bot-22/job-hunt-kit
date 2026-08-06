"""`/setup` — the front door, asserted as an artifact rather than as a conversation.
Run:  .venv/bin/python -m pytest triage/ -q

The skill is prose, and most of what it says can only be checked by reading it. Three of its claims
are not prose, though, and each of them is a promise made to someone who has not yet decided whether
to trust this tool. Those get tests.

The failure directions, in the order they cost something:

  * **A fetch before the user has chosen.** The ordering of the steps IS the guarantee — there is no
    code gate behind it — so a later edit that moves the first `python -m triage` above the channel
    menu silently breaks the constraint the ticket was written around. Nothing else would notice.
  * **A channel that exists in the registry and not in the menu.** `channels.ALL` is the truth about
    what can run; a menu missing one of them hides a channel that is on by default (an unconfigured
    channel defaults to ON), and a menu naming one that no longer exists sends someone to write a
    settings key that fails validation.
  * **`mail` presented without its platform limit, or `gmail` presented as a channel.** Both are the
    "discover the limitation after choosing" failure the requirements table exists to prevent, and
    `gmail` raises when enabled rather than returning nothing.

This file lives in `triage/` rather than `core/` because `channels.ALL` is the anchor and `core/` may
not import a leaf.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "`/setup` shows the channel menu before anything is fetched."
import re
from pathlib import Path

from . import channels
from .channels.boards import _ATS

SKILL_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "setup"
SKILL = SKILL_DIR / "SKILL.md"
STARTER_BOARDS = SKILL_DIR / "starter-boards.md"


def _text() -> str:
    return SKILL.read_text()


def _table_rows(text: str) -> list[list[str]]:
    """Markdown table rows as trimmed cell lists, header and separator rows dropped."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def _channel_row(name: str) -> list[str]:
    """The menu row for one channel, found by its backticked name in the first cell."""
    for cells in _table_rows(_text()):
        if cells and re.fullmatch(rf"\**`{name}`\**", cells[0]):
            return cells
    raise AssertionError(f"the channel menu has no row for `{name}`")


def test_it_is_a_skill_and_not_a_slash_command() -> None:
    """Box 9. A slash command only exists inside one agent; the audience uses several."""
    assert SKILL.is_file()
    assert not (SKILL.parent.parent.parent / "commands" / "setup.md").exists()
    head = _text().split("---")[1]
    assert re.search(r"^name:\s*setup\s*$", head, re.M)
    assert re.search(r"^description:\s*\S", head, re.M)


def test_nothing_is_fetched_before_the_channel_menu() -> None:
    """The hard constraint, enforced as document order because that is all that enforces it.

    A `python -m triage` invocation is the first thing in this skill that reaches the network on the
    user's behalf. It must appear after the menu that lets them say no.
    """
    text = _text()
    menu = text.index("## 7. The channel menu")
    first_run = text.index("-m triage")
    assert first_run > menu, "a triage run is documented before the user has been shown the menu"


def test_the_menu_names_every_registered_channel_and_no_others() -> None:
    """Drift in either direction is a channel the user cannot see or a setting that will not validate."""
    named = {cells[0].strip("* `") for cells in _table_rows(_text())
             if re.fullmatch(r"\**`[a-z-]+`\**", cells[0])}
    assert named == set(channels.ALL)


def test_mail_is_marked_macos_only_and_gmail_is_marked_unbuilt() -> None:
    """The two limits a user must know BEFORE choosing, not after."""
    mail = " ".join(_channel_row("mail")).lower()
    assert "macos only" in mail
    gmail = " ".join(_channel_row("gmail")).lower()
    assert "not built" in gmail
    assert "raises" in _text().lower()


def test_paste_needs_nothing_and_is_always_on() -> None:
    """Box 8: every channel is skippable and paste still works, so "none of them" is a real answer."""
    paste = " ".join(_channel_row("paste")).lower()
    assert "nothing" in paste and "none" in paste and "on, always" in paste
    assert "every channel is skippable" in _text().lower()


def test_no_oauth_is_asked_for_anywhere() -> None:
    """Box 7. OAuth may be *described* (the gmail row says what the stub would need) but never
    instructed — a Google Cloud project before the first result is the first run this stage refuses."""
    text = _text().lower()
    for forbidden in ("console.cloud.google.com", "credentials.json", "client_secret", "oauth consent"):
        assert forbidden not in text


def test_the_starter_board_list_is_not_empty_and_names_known_ats() -> None:
    """Box 5. `boards 0` on day one reads as a broken channel rather than a quiet week, so the skill
    has to be able to hand someone a list. An ATS this repo cannot fetch would be worse than none."""
    tokens = [(cells[0], cells[1].strip("`")) for cells in _table_rows(STARTER_BOARDS.read_text())
              if len(cells) >= 2 and cells[0] in _ATS]
    assert len(tokens) >= 3
    assert {ats for ats, _ in tokens} == set(_ATS)
    for _, token in tokens:
        assert re.fullmatch(r"[a-z0-9-]+", token), token
    assert SKILL.read_text().count("starter-boards.md") >= 1


def test_setup_seeds_from_the_shipped_example_rather_than_writing_config_by_hand() -> None:
    """Box 3, and the reason it matters is `core.example.seed`'s refusal to overwrite: a hand-written
    config from an agent has no such guard, and `profile/rubric.md` on a used clone has no undo."""
    text = _text()
    assert "-m core.example" in text
    assert "never overwrites" in text.lower()
