# Running it on a schedule

> The daily run is useful daily, and remembering to run it is not a plan. This is how to make it
> unattended on your own machine — and, more usefully, where the unattended part stops.

## The split: what can run without you, and what cannot

`python -m triage` — Phase 1, the whole Python pipeline — runs unattended with no input. It reads its
channels, dedupes, fetches every JD it can, screens, scores against your rubric, and writes:

| file | what it is |
|---|---|
| `data/runs/worklist-<run_id>.md` | the ranked output — the thing you read |
| `data/runs/latest-run.txt` | the pointer `--merge` uses to find this run's files |
| `data/corpus/state-<run_id>.json`, `seen.json` | the judgments, and the dedup memory |
| `data/runs/browser-queue-<run_id>.json` | JDs that need a logged-in browser |
| `data/runs/archive-<date>.txt` | the messages a mail step would archive |

`python -m research.market` (monthly) and `python -m research "<Company>"` are unattended too.

**Everything after Phase 1 in the `/job-triage` workflow needs a human or a human's session.** Walled
JDs need a logged-in browser and sometimes a CAPTCHA click. Archiving processed mail drives a Gmail
connector in your agent, not Python. The apply document, the carryover re-check and the tailored
résumés are judgment. None of that is an oversight waiting to be automated — it is the same rule as
everywhere else here: *the irreversible or the arguable step is a human's*.

So the honest ceiling is: **a schedule produces a worklist waiting for you, not a finished morning.**
That is still most of the value — the ~9–10 minutes of network-bound work for a ~350-job window has
already happened by the time you sit down.

For a scheduled run, `--no-browser` keeps it from queueing fetches nobody will perform. Leave it off
if you would rather sit down to a queue and run `--merge` yourself; the queue file persists and
`--merge` finds it through `latest-run.txt`.

## Size the window wider than the interval

The one setting a schedule reliably gets wrong. `window_days: 3` in `config/settings.yaml`, or
`--days N` for one run, is both how far back the mailbox is read and how fresh a posting must be.

**Over-wide is nearly free; under-wide loses jobs permanently.** Everything already judged is in
`seen.json` and is blocked before any fetch or model call, so a re-read costs a few seconds of
listing. Nothing ever goes back for a day the window missed. A laptop that was shut on Tuesday is a
hole, and the fix is a margin: on a weekday schedule, pass `--days 7`.

## macOS — a launchd agent

The only platform where every channel works, because `mail` drives Apple Mail. That also fixes *how*
it must be scheduled: a **LaunchAgent** in `~/Library/LaunchAgents/`, which runs as your logged-in
user, not a LaunchDaemon.

`~/Library/LaunchAgents/dev.jobhuntkit.triage.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.jobhuntkit.triage</string>
  <key>ProgramArguments</key><array>
    <string>/Users/you/dev/job-hunt-kit/.venv/bin/python</string>
    <string>-m</string><string>triage</string>
    <string>--days</string><string>7</string>
    <string>--no-browser</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/Users/you/dev/job-hunt-kit/data/runs/schedule.log</string>
  <key>StandardErrorPath</key><string>/Users/you/dev/job-hunt-kit/data/runs/schedule.log</string>
</dict></plist>
```

`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.jobhuntkit.triage.plist`, and
`launchctl kickstart -p gui/$(id -u)/dev.jobhuntkit.triage` to test it once without waiting.

Two things specific to this platform. **launchd runs a missed job when the machine wakes; cron does
not** — which on a laptop is the difference between a schedule and a suggestion. And the first run
that touches Apple Mail raises a macOS Automation permission dialog. **A scheduled job cannot answer
a permission dialog**, so run `python -m triage` by hand once and approve it before scheduling
anything.

## Linux — a systemd user timer

No `mail` channel here: `paste`, `boards` and `agencies` are the keyless, any-OS way in, and `gmail`
is an unbuilt stub that raises rather than pretending. Set `channels.mail.enabled: false` in
`config/settings.yaml`: `mail` is the one file in the repo that shells out to `osascript`, so off a
Mac it contributes nothing but a warning in every morning's log.

`~/.config/systemd/user/triage.service` runs
`/home/you/job-hunt-kit/.venv/bin/python -m triage --days 7 --no-browser`; the paired `triage.timer`
wants `OnCalendar=Mon..Fri 07:00` and — the line that matters — **`Persistent=true`**, which is
systemd's equivalent of launchd catching up after a sleep. `systemctl --user enable --now
triage.timer`, and `journalctl --user -u triage` for the output.

Windows Task Scheduler is the same shape with the same channel set; *Run whether user is logged on or
not* plus *Run task as soon as possible after a scheduled start is missed* are the two boxes.

## Plain cron, and the three things that bite

```cron
0 7 * * 1-5 /home/you/job-hunt-kit/.venv/bin/python -m triage --days 7 --no-browser \
  >> /home/you/job-hunt-kit/data/runs/schedule.log 2>&1
```

1. **cron has almost no environment.** Use the absolute path to `.venv/bin/python` — there is no
   activated virtualenv and often no useful `PATH`. You do *not* need to `cd`: every path constant in
   this repo is resolved from the package's own location, so `.env`, `profile/`, `config/` and
   `data/` are found wherever cron starts you. The one exception is **`JOBSDB_CONFIG_HOME`, which is
   resolved against the current directory** — if you use it in a scheduled job, give it an absolute
   path or it will silently resolve somewhere else.
2. **cron does not catch up.** A missed slot is simply missed, which is what the `--days` margin
   above is for.
3. **Output goes nowhere unless you send it somewhere.** `data/runs/` is the right destination — it
   is gitignored and documented as disposable, unlike `data/corpus/`, which is a month of judgments.

**Do not schedule runs closer together than a run takes.** Nothing locks `data/corpus/`; two
overlapping runs both write `seen.json` and the loser's judgments are lost. A ~350-job window takes
~9–10 minutes at the shipped `max_workers: 12`, and it is network-bound, so it gets slower on a
wider window rather than faster on a bigger machine.

## CI — possible, and it costs both properties the tool is built on

GitHub Actions is the option that looks obvious and mostly isn't, for four reasons worth stating
rather than hand-waving:

- **There is no memory between runs.** `data/` is gitignored, so `seen.json`, `applied.json` and the
  retrieval index do not survive a job. Every run re-scores everything it already judged, and
  precedent — the thing that makes the second run better than the first — is empty forever. The fixes
  are `actions/cache` (workable) or committing the corpus (your scored opinion of every company you
  have considered, in a repo — precisely what this repo's extraction guard exists to prevent).
- **Your provider key becomes a repository secret**, on somebody else's runner, which is the opposite
  of the per-user-key rule in `NOTICE`.
- **There is no mailbox.** `mail` needs Apple Mail; `gmail` is unbuilt. You get `boards` and `paste`.
- **The output lands where you are not.** A worklist in an artifact is a worklist you do not read.

If you want it anyway, the defensible shape is narrow: the keyless `boards` channel, `actions/cache`
over `data/corpus/`, and the worklist posted somewhere you actually look. Local scheduling is the
recommendation, and it is not close.

## Scheduling your agent instead

If your client can run a skill on a schedule, it can in principle drive more of `/job-triage` than
Python can — it owns the browser and the mail connector. Three limits before you try:

- **It cannot click a CAPTCHA**, and the browser step is explicitly written to stop and ask.
- **It cannot answer the workflow's own questions** — step 0 asks whether to sync your applied sheet
  first, and an unattended agent will either guess or stall.
- **An agent that skips a step still reports success.** The Python pipeline fails loudly; a prose
  workflow degrades quietly, which is the wrong failure direction for something nobody is watching.

The shape that works: schedule the Python, keep the agent interactive. If you do schedule an agent,
scope it to Phase 1 plus a digest and let it stop there.

## What never goes on a schedule

`scripts/extract.py`, in the private repo this was extracted from. Publishing is the one irreversible
outward-facing act in the whole design and it is deliberately a human's — see
[`docs/philosophy.md`](../philosophy.md#nothing-publishes-on-a-trigger).
