"""The `mail` channel — read Gmail through Apple Mail (AppleScript), macOS only.

This is the original ingest path, unchanged: everything that isn't the transport now lives in
`common.py`, and what remains here is the one file in the repo that shells out to `osascript`. That
is the whole reason the tool is macOS-only, and quarantining it in a single channel is what lets a
stranger on Linux run everything else.

We read each message's raw `source` and parse it with Python's `email` module — because Apple Mail's
plain-text `content` drops the anchored URLs in HTML alert emails (LinkedIn/Dice job links live in the
HTML part). Parsing the source also decodes quoted-printable/base64, so the real job URLs come through
intact and are handed to the extractor. AppleScript reading is the pattern proven in
../freelance-automation (Proton Bridge's programmatic IMAP was broken on this Mac; Apple Mail handles
Gmail's OAuth and we just read).
"""
from __future__ import annotations

import logging
import subprocess

from .. import config
from . import common
from core.models import Job

log = logging.getLogger("triage.channels.mail")

_MAX_EMAILS = 250          # safety cap on a single run

_APPLESCRIPT = '''
on run
  set AppleScript's text item delimiters to ""
  set out to ""
  set cutoff to (current date) - ({days} * 86400)
  tell application "Mail"
    set acct to (first account whose name is "{account}")
    set mbox to (mailbox "{mailbox}" of acct)
    set msgs to (every message of mbox whose date received > cutoff)
    repeat with m in msgs
      try
        set out to out & "<<S>>" & (subject of m) & "<<F>>" & (sender of m) & ¬
          "<<D>>" & ((date received of m) as string) & "<<M>>" & (message id of m) & ¬
          "<<B>>" & (source of m) & "<<E>>"
      end try
    end repeat
  end tell
  return out
end run
'''


def read_emails(days: int) -> list[dict]:
    """Return recent emails: {subject, sender, date, mid, content, urls, is_reply}."""
    inbox = config.inbox()
    script = _APPLESCRIPT.format(days=days, account=inbox["account"], mailbox=inbox.get("mailbox", "INBOX"))
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                             timeout=240).stdout
    except subprocess.TimeoutExpired:
        log.warning("osascript timed out reading mail"); return []
    emails = []
    for block in out.split("<<S>>"):
        if "<<E>>" not in block:
            continue
        block = block.split("<<E>>")[0]
        try:
            subj, rest = block.split("<<F>>", 1)
            sender, rest = rest.split("<<D>>", 1)
            date, rest = rest.split("<<M>>", 1)
            mid, source = rest.split("<<B>>", 1)
        except ValueError:
            continue
        content, urls, is_reply, unknown = common._parse_source(source)
        emails.append({"subject": subj.strip(), "sender": sender.strip(), "date": date.strip(),
                       "mid": mid.strip(), "content": content, "urls": urls, "is_reply": is_reply,
                       "unclassified": unknown})
    return emails[:_MAX_EMAILS]


def fetch(days: int, sample: int | None = None) -> list[Job]:
    """The channel contract: every job the inbox yielded in the window, PRE-dedup.

    Pre-dedup because the archive check needs the full extraction — an email whose only jobs are
    duplicates of jobs seen elsewhere must still archive — and because only the registry can see a
    posting that arrived on two channels. `sample=N` picks N representative WHOLE emails.
    """
    return common.jobs_from_emails(read_emails(days), days, sample)
