"""The `gmail` channel — **a stub. Registered, disabled, and not built.**

This module exists so that the Gmail API is a *seam with a contract* rather than a README line. It is
deliberately not implemented: forcing a Google Cloud project and an OAuth consent screen on someone
who has not yet seen the tool produce anything is a worse first run than the platform limit it fixes,
so `mail` (macOS-only) handles the inbox and `paste` (any OS, no key) covers the cold start — `boards`
is keyless and any-OS too, but it is a watchlist that needs company tokens, not a cold-start answer.
This stub is here for whoever wants their inbox on Linux. The audience is a developer working with an agent; an honest stub
they can finish in one session beats a feature they would have to reverse-engineer.

**Everything below is the contract. Read it before writing code — three of these are things an
implementer gets wrong by default, and one of them archives a live email thread.**

### What `fetch` must return

    def fetch(days: int, sample: int | None = None) -> list[Job]

Every job found in the last `days` days, **PRE-dedup** — do not collapse duplicates here. The
registry (`channels/__init__.py:ingest`) does the collapse across all channels at once, because a
posting arriving on both `boards` and `mail` is only visible as a duplicate from above. `sample=N`
means N representative WHOLE messages (not N jobs), so that a `--sample` run is a small *end-to-end*
run in which every sampled message is fully processed and therefore archivable.

### `email_mid` MUST be the RFC822 `Message-ID`

Not Gmail's `id`, not its `threadId`. `Job.email_mid` is the handle the archive flow depends on:
`common.archive_list_lines` writes it into `data/runs/archive-<date>.txt`, and the Claude session that
does the archiving looks the message up with `rfc822msgid:<id>`. A Gmail-internal id there produces an
archive list where every lookup silently finds nothing — the run looks fine and the inbox never
empties. Take it from the parsed headers (`msg["Message-ID"]`), which you already have if you follow
the sketch below.

### `from_correspondence` MUST come from `common._is_correspondence` — do not re-derive it

Pass the parsed `In-Reply-To`/`References` signal through as `is_reply` and let
`common._is_correspondence` make the call. **Its failure mode is default-safe on purpose: a message is
a conversation unless it is provably automated.** That default was chosen after the 2026-07-20 run,
where three live threads — one of them Ben's College Board interview correspondence — were one step
from being archived. Gmail archives per *thread* while the archive list is per *message*, so one wrong
line pulls a whole conversation, replies and unread mail included, out of the inbox. A re-derivation
that looks more accurate (say, trusting a `CATEGORY_PROMOTIONS` label) fails in the direction that
costs real damage.

### Reuse these verbatim — this adapter replaces ONLY the transport

Everything in `channels/common.py` is about email and nothing in it is about *how the email was
fetched*. In particular:

  * `common._parse_source(raw)` — decoded text, job URLs, the is-reply flag and the unclassified URLs,
    straight from a raw RFC822 string. That is exactly what `users.messages.get(format='raw')` gives
    you, base64url-decoded.
  * `common.classify_urls(text)` — the three buckets: job hosts, junk, unclassified.
    (`common._job_urls(text)` is the first bucket alone, kept as a name for this seam.)
  * `common._extract_from_email(em)` — the Sonnet extraction, through `core/llm.py`, the single
    generation path. Never build a second model client. Note it RECONCILES: every job link becomes a
    job whether or not the model described it, so an adapter that drops the `urls` key from the email
    dict silently reintroduces the bug this seam exists to prevent.
  * `common.jobs_from_emails(emails, days, sample)` — the whole gate → sample → six-worker extract
    loop. If your transport produces the email dicts, this one call is the rest of the channel; see
    `channels/mail.py:fetch`, which is two lines.
  * `common.hydrate(jobs)` — NOT yours to call. `__main__` runs it after the seen/applied gate, on
    every channel's jobs at once, and calling it in a channel would re-fetch recovered links forever.

The email dict shape they all agree on is
`{subject, sender, date, mid, content, urls, is_reply}`.

### OAuth scopes

  * `https://www.googleapis.com/auth/gmail.readonly` — required, and enough for ingest.
  * `https://www.googleapis.com/auth/gmail.modify` — only if you also wire archiving. Ingest does not
    need it and asking for it makes the consent screen scarier than the feature.

Archiving is deliberately **out of scope for this module**: it is a different operation on a different
scope, and it stays on the existing agent-driven path (`archive_list_lines` → a Claude session with the
Gmail connector). Worth knowing for whoever picks it up, though — the Gmail API would be a strict
improvement there even if reading stayed on Apple Mail, because Apple Mail's AppleScript `move`
dual-labels a Gmail message and cannot actually archive it, which is the entire reason archiving is
outsourced today. At this volume the API is free: ~5 quota units per message against a daily 80M.

### Wiring it up

Set `channels: gmail: {enabled: true}` in `config/settings.yaml` once `fetch` returns jobs — the flag
ships **false** precisely because `channel_enabled` defaults to True for an unconfigured channel, and
an enabled stub would print `gmail CRASHED` on every run.
"""
from __future__ import annotations

from core.models import Job

# `google-api-python-client` and `google-auth-oauthlib` are NOT in core/requirements.txt. Adding a
# dependency for a module that raises would make every user pay for a channel nobody has built.

_CONTRACT = (
    "The `gmail` channel is a documented stub, not a working channel: it is registered so the seam is "
    "visible and disabled so it never runs. Read the contract in triage/channels/gmail_api.py's module "
    "docstring before implementing it — it names the three things that are wrong by default "
    "(the message identifier must be the RFC822 Message-ID, `from_correspondence` must come from "
    "common._is_correspondence, and jobs are returned pre-dedup), and the helpers in "
    "channels/common.py that should be reused verbatim. Until then use the `mail` channel (macOS), "
    "or `boards` / `paste`, which need no key on any OS."
)


def fetch(days: int, sample: int | None = None) -> list[Job]:
    """Not implemented. Raises, pointing at this module's docstring.

    It raises rather than returning `[]` on purpose, and that asymmetry is the whole point of shipping
    a stub at all: an empty list is indistinguishable from a working channel whose window happened to
    be quiet, so a user who enabled Gmail would watch `gmail 0` scroll past every morning and conclude
    their inbox had no jobs in it. A crash line in the run summary is the honest reading.
    """
    raise NotImplementedError(_CONTRACT)


# AGENT: the whole channel, once the OAuth dance is done. `service` is a built Gmail resource
# (`googleapiclient.discovery.build("gmail", "v1", credentials=creds)`); get `creds` from
# `google_auth_oauthlib.flow.InstalledAppFlow` with the readonly scope above and cache the token
# somewhere gitignored — `data/runs/` is disposable, so it does not belong there.
#
#     import base64
#     from . import common
#
#     def fetch(days, sample=None):
#         q = f"newer_than:{days}d -in:chats"
#         ids = service.users().messages().list(userId="me", q=q, maxResults=250).execute()
#         emails = []
#         for ref in ids.get("messages", []):
#             raw = service.users().messages().get(
#                 userId="me", id=ref["id"], format="raw").execute()["raw"]
#             source = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
#             # `_parse_source` takes the raw RFC822 string — the same thing Apple Mail's `source`
#             # gives the mail channel, which is why nothing below this line has to be new code.
#             content, urls, is_reply, unknown = common._parse_source(source)
#             msg = email.message_from_string(source, policy=policy.default)
#             emails.append({
#                 "subject": msg.get("Subject", ""),
#                 "sender": msg.get("From", ""),
#                 "date": msg.get("Date", ""),
#                 "mid": msg.get("Message-ID", ""),   # RFC822, NOT ref["id"] — see the docstring
#                 "content": content, "urls": urls, "is_reply": is_reply,
#             })
#         return common.jobs_from_emails(emails, days, sample)
#
# Then: flip `channels: gmail: {enabled: true}` in config/settings.yaml, update the channel table in
# README.md, and delete this comment along with `_CONTRACT`. The tests to write are the ones
# `triage/test_gmail_stub.py` cannot: that `mid` is the RFC822 header and that a reply comes back
# `from_correspondence=True`, both against a stored raw message fixture rather than a live account.
