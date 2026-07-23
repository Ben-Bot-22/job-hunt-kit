# The shipped example — a fictional job seeker

This directory is a **complete, working configuration** for someone who does not exist. It is what a
stranger runs the tool against before they have written a line of their own config, and it is what
the test suite uses as its fixture — so it is exercised on every test run and cannot quietly rot into
something that no longer works.

The seeker is **Robin Doe**, a mid-level full-stack developer in Chicago looking for remote permanent
React and TypeScript work at $130k or better. Robin is unmistakably fictional: the surname is a placeholder, the
email is at `example.invalid` (a TLD reserved by RFC 2606 that can never be registered), there is no
applied-sheet id, and every company named in the rubric — Northwind Analytics, Harborview Logistics,
Tessellate Labs — is invented. Robin is deliberately *not* a sanitised copy of the repo owner: he is
optimizing for permanent over contract, a salary rather than an hourly rate, and a stack that is not
the same one. The point is to show that the rubric is a genuine prose slot rather than a template
with the names filed off.

## Run the tool against it

    JOBSDB_CONFIG_HOME=config/example .venv/bin/python -m triage --paste <a job URL>

`JOBSDB_CONFIG_HOME` points the whole tool — settings *and* identity — at one directory. Nothing here
is fetched from a mailbox, nothing asks for OAuth, and nothing reads or writes a real person's data:
`mail` is off (it is macOS-only and wants an Apple Mail account), `gmail` is off (it is an unbuilt
stub), and what is left is `paste` and `boards`, both of which need no key at all. You still need a
model-provider key in `.env` for the scoring itself — that is the tool, not the example.

Take the `boards` tokens as read: `anthropic` on Greenhouse and `leverdemo` on Lever are real, public,
keyless boards that return real postings. They are there so a first run produces something even if
you have no URL to paste.

## Seed your own config from it

    .venv/bin/python -m core.example

Copies `profile.yaml`, `rubric.md`, `bullet-bank.md`, `skiplist.md` and `cover-letter.json` into
`profile/`, and
`settings.yaml` into `config/`. **It never overwrites a file that already exists** — it says what it
skipped and stops there. That is what the `/setup` skill calls, and it is safe to run on a clone that
already has a configured profile.

## The one rule for editing this directory

Change it the way you would change your own config, then run the suite. If a file here stops being a
valid configuration, tests fail — which is the whole reason the demo and the fixture are the same
files rather than two things that agree until one of them is edited.
