# The test suite, and who it is for

> Why the suite ships in the public snapshot, why some of it skips on a clone that is not the owner's,
> and the one rule that keeps a skip from being a quiet loss of coverage.

## The suite ships, deliberately

`job-hunt-kit` is a point-in-time snapshot of a private working repo, published as a demo — nobody is
maintaining it as a shared codebase. That makes the test suite one of the more valuable things in it,
for two readers who never run the tool:

- **Someone judging the project.** The tests are the evidence of how it was built. Their docstrings
  carry the reasoning — *"gmail stays off, the stub raises, and an enabled stub prints `gmail CRASHED`
  every morning"* — which is the part a reader cannot reconstruct from the code.
- **Someone forking it.** The README's advice is *fork it and make it yours*. The suite is what tells
  them whether their edit broke something, and it is the only safety net they get.

So `pytest -q` on a fresh clone has to read **`passed` and `skipped`, never `failed`.** A stranger who
clones this, runs the suite because the README suggested it, and sees fourteen red lines concludes the
project does not work — which is a worse outcome than shipping no tests at all.

## Two kinds of test, and the seam between them

Everything here is one of two things:

**Rules about the code.** True for every user, every config, every clone. `gmail` is off because the
stub raises. The prompt keeps its `cache_control` marker. A refusal lands the job in "Rejected /
skipped". These carry no marker and run everywhere, always.

**Values the owner tuned.** The `$50/hr HARD FLOOR` line in the rubric, named mis-scores, a real inbox,
a 3-day window, 12 workers. These guard real regressions on the owner's own checkout — the `max_worker`
typo that silently ran at 5 for weeks is exactly what they exist to catch. On any other clone they are
not merely untrue, they have **no subject**: there is no owner profile to read, and `profile/` is the
one directory the public tree omits.

The second kind carries a marker and skips when its subject is absent:

| marker | skips when | defined in |
|---|---|---|
| `needs_profile` / `needs_owner_profile` / `needs_rubric` | nothing has been seeded — `profile/` does not exist | `core.settings.profile_exists()` |
| `owner_only` | this is not the owner's checkout — no profile, or the profile is the example seeker | `profile_exists()` + `is_example_profile()` |

## The rules

1. **A skip must say what is missing, what it is for, and how to get it.** The reason string is read by
   someone who has just cloned the repo and has no idea what `profile/rubric.md` is. *"no profile/ yet —
   profile.yaml is your identity and rubric.md is the prose rubric every job is scored against. Seed
   them with `python -m core.example`."* A bare `reason="needs profile"` fails this.
2. **Skip, do not delete.** These tests are worth their keep on the owner's checkout, which is a live
   daily-use repo. The public snapshot does not get to decide what the working repo keeps.
3. **Do not pin config values that are not rules.** A test asserting `mail` is on and `boards` has no
   companies states nothing and breaks the moment anybody configures anything — which is the first
   thing a new user does. If an assertion has no reason in its docstring, it is a photograph, not a
   test. The one exception is the owner's tuned numbers, which are real regression guards and are
   therefore `owner_only`.
4. **A test must not depend on the machine.** The provider-key check reads the environment, so
   `triage/test_preflight.py` neutralises it in an autouse fixture: a developer with a key in `.env` and
   a stranger without one must get the same result from the same config.

## What a clean cold clone looks like

```
$ python -m core.example      # seeds profile/ with the fictional seeker
$ python -m pytest -q
592 passed, 10 skipped
```

and before seeding anything at all, still no failures — the profile-dependent tests skip and say why.
If either produces a `failed`, fix it here in `jobs-db` and re-extract; never patch the public clone,
which the next extraction overwrites.
