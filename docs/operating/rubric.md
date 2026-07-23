# The rubric — the one file that decides everything

`profile/rubric.md` is the tool's judgment. Every other file decides what gets fetched, how fast, and
where it lands; this one decides what is *good*. It is prose, nothing parses it, and it is handed to
the model whole on every single scored job.

It is also the file a new user understands least, because `/setup` writes one from an interview and
then hands it over without a manual. This is the manual: how it reaches the model, what each section
does to a score, the three tiers of "no" and how to tell them apart, and how to change it when you
disagree with a verdict.

Everything below is true of [`config/example/rubric.md`](../../config/example/rubric.md) — the
fictional seeker's rubric, which is what `python -m core.example` seeds and therefore the rubric you
have if you have not written one. Quotes are from that file. `core/test_rubric_guide.py` checks that
they still are.

---

## 1. The mechanics — how it reaches the model

`triage/config.py` · `goal_profile()` reads the file and returns it **whole and unparsed**. There is
no front matter and no header to strip, deliberately: the file's contents and the injected text are
the same string, so nobody has to remember which parts ship. Anything you add for your own benefit is
also read by the model.

`triage/analyze.py` wraps it in one sentence on each side and puts it in the **system block**:

```
===== GOAL PROFILE (the 10/10 anchor) =====
<the entire contents of profile/rubric.md>
===== END GOAL PROFILE =====
```

That block carries a `cache_control` marker, which is the whole reason the split exists. The system
block is identical for every job in a run, so the provider caches it and you are billed the full rate
for it once rather than ~350 times. **Everything job-specific stays out of it** — the JD, the title,
the company, and any retrieved precedent go in the user message. That is a hard rule in the code, not
a style preference: one job-varying character in the system block and the cache misses on every job.

Practical consequences of the caching, both of which surprise people:

* **The rubric's length is nearly free.** At ~6.6k characters (order of 1,600 tokens) the example
  rubric costs one cache write per run. Doubling it does not double your bill. Write the sentence
  rather than the abbreviation.
* **An edit takes effect on the next run, not mid-run.** `goal_profile()` is `lru_cache`d and
  `analyze._SYSTEM` is built once at import. A batch run reads the rubric once, at the start.

### It has no schema, on purpose

Nothing validates it. A stray tab, a rogue quote, an indent one space off — it is text, and it
reaches the analyzer unharmed. That is exactly why it left the old YAML config, where the rubric was
a folded block scalar and a typo in a *prompt* took the models, the window and the channel flags down
with it. **You cannot break the tool by editing this file.** That property is worth more than any
validation would be, because this is the file edited most.

*Missing* is a different failure and is loud on purpose: `goal_profile()` raises and names the path.
Scoring against an empty anchor would produce a full worklist of confidently wrong verdicts and
nothing would error, which is worse than not running.

### What the rubric does *not* control

Two things a reader reasonably expects to find here and will not:

* **The prefilter never sees it.** `triage/prefilter.py` runs first, on regex rules and a small model
  call, and it is what decides whether a job is worth an Opus call at all. A job it drops is never
  scored, so no rubric edit can rescue it — it appears in the worklist's `Rejected / skipped` section
  with a screen reason instead. If in-lane roles are landing there, the fix is in `prefilter.py`, not
  here. See [`tuning.md` §3](tuning.md).
* **The verdict bands and the score ranges are in `analyze.py`.** `STRONG_FIT = 80–95` and what each
  band means are hard-coded in the system prompt around your rubric, along with the channel tiers.
  The example rubric's `SCORING DISCIPLINE` section restates them so the two agree — if you redefine
  what a 90 means in your rubric and leave that prompt alone, you have two anchors disagreeing inside
  one system block, and the code's copy is the one you did not write.

---

## 2. The sections, and what each does to a score

The section vocabulary is a working structure, not an accident. Keep the order and the headings when
you edit: they are ALL-CAPS lines with no markdown, which is what makes them read as headings to a
model that is being handed 6.6k characters of prose.

### IDEAL ROLE

The 10/10. This is the positive anchor everything else is measured against, and it is the only
section that can *raise* a score. Location and remote posture, permanent-or-contract and which one
loses a tie, the hard money floor stated the way you think about money, intensity on a 1–5 scale and
what time is protected, the in-lane stack.

Two line shapes here do specific work. A **tailorable** line stops a near-miss being downranked for
the wrong reason:

> - TAILORABLE, treat as IN-LANE (do NOT downrank): roles keyworded GCP or Azure, or Vue/Svelte instead of

And a **bonus edge** line is explicitly a plus rather than a requirement — which only works because
`SCORING DISCIPLINE` says when it is applied:

> - BONUS EDGE (a plus, not required): products where one person carries a feature from the UI through the

### DOWNRANK

Shown, ranked lower, never skipped. This is where most of your real opinions live: what makes a
posting worth seeing but not worth wanting. A hybrid role that would need a move, a 4–5 intensity
signal, a contract with no stated conversion.

Some entries in this section also carry `CAP AT LOW_FIT`, which is a different and stronger thing —
see §3.

### SCORING DISCIPLINE

The ordering rule, and the highest-leverage four lines in the file. **Score the role first, add
bonuses second:**

> - Score the ROLE first — shape (is it an engineering IC role that ships product?), seniority bar,

Without this, keyword overlap does the scoring. A React-heavy JD reads as a perfect match to a
front-end-capable rubric even when its title is Product Owner, its years bar is 8+, and its band tops out below
the floor. The section exists to make the model apply the gates before it notices the overlap.

### CALIBRATION

Worked cases: real jobs with the score they should have. This is the feedback loop and it gets its
own section below (§4).

### HARD FILTERS

`verdict = SKIP`. Facts you can check and be right about — not preferences. In the example: non-US,
a posted band clearly below the floor, a primary stack that is not the candidate's, a required
clearance.

### BODY SHOP

A hard filter with enough nuance to need its own block, and worth keeping in whatever you write. It
keys on **tells, never on "is this a staffing firm"** — for many job seekers agencies are the fastest
supply channel there is, and skipping them wholesale removes the best lane on the board:

> BODY SHOP (verdict = SKIP) — key on the TELLS, NEVER on "is this a staffing firm". A recruiter or

The tells are things like concatenated work-authorization categories, a demand for identity documents
up front, or a vendor that will not name the client at all. Note the two-strength design: some tells
skip alone, and a set of **weak** tells skip only in combination — an in-person-only interview by
itself is a plain onsite employer.

### CANDIDATE

Who is being scored, in a short paragraph, **including the real gaps**. This is what lets the model
apply a mandatory-tech gap correctly instead of guessing at it from the in-lane list. The example
names them outright — never led a team, has used Kubernetes as a consumer rather than run one — and
those two sentences are what make the `Staff Platform Engineer` calibration case below decidable.

---

## 3. The three tiers of "no", and why they are not one tier

This is the whole craft of writing a rubric, and getting a rule into the wrong tier is the most
common way one goes wrong — in **both** directions.

| tier | what it means | what happens to the job | when to use it |
|---|---|---|---|
| **downrank** | a preference | scored, ranked lower, still in the list | you would take it on a bad month |
| **cap** (`CAP AT LOW_FIT`) | an inferred disqualifier | scored, visible, out of the apply set | you are confident it is wrong for you, but the judgment is a reading of the JD |
| **hard filter** | a factual disqualifier | `verdict = SKIP` | you can check it and be right |

**Downrank — a preference.** Nothing about the role is wrong; you would just rather have something
else. From the example:

> - Intensity 4-5 (early-stage crunch, primary on-call, "we ship on weekends") -> downrank.

**Cap — an inferred disqualifier.** Still scored, still shown, but it cannot reach the apply set no
matter how well the rest of it reads. The judgment requires *reading* the JD, so it belongs where you
can audit it rather than where it disappears:

> - NON-ENGINEERING ROLE SHAPE -> downrank hard, CAP AT LOW_FIT. Product Owner / Business Analyst /

The mechanism is stated in `SCORING DISCIPLINE` — a fired gate caps the verdict and names itself in
`red_flags`, so the job appears in the list *with the reason it was capped attached*. That is what
you read to find out the rule is too aggressive.

**Hard filter — a factual disqualifier.** A `SKIP` is out of the ranked list. Only put a rule here
when a wrong call is nearly impossible: nationality, a posted number below a floor, a clearance.

**The two failure directions, both real:**

* **A preference written as a hard filter** silently deletes a lane. You do not see what you lost —
  a `SKIP` does not argue with you — so a too-aggressive filter looks exactly like a quiet market.
  The example's `EXCESSIVE SENIORITY BAR` rule is careful about precisely this: 8+ years is a
  standing skip pattern, *"5-6 years is a caution, not a cut."*
* **A disqualifier written as a downrank** puts jobs you will never apply to at the top of a good
  week's list, because a strong keyword match outscores a soft penalty. That is what `CAP AT LOW_FIT`
  is for: it is the tier for "I am sure, but I want to see it anyway".

When in doubt, **cap rather than filter**. A cap that is wrong costs you one visible line you
disagree with; a filter that is wrong costs you a job you never learn existed.

---

## 4. CALIBRATION is the feedback loop

**When you disagree with a score, the fix is usually a new worked case — not a new rule.**

This is the single thing a stranger will not guess, and it is how the tool learns your judgment. A
rule is an abstraction you are asking the model to apply; a worked case is a demonstration, and it
disambiguates the rules you already wrote by showing which one wins on a real job.

The form is a job, the score it should have, and one sentence of why. The example carries three, and
they do three different jobs:

* **The bar.** `Northwind Analytics, "Backend Engineer, Data Platform"` → `STRONG_FIT ~90`, ending
  *"THIS is the bar for 80+."* Without one of these, 80+ means whatever the model thinks it means.
* **The recorded mistake.** `Harborview Logistics, "Senior Data Analyst — Python & SQL"` → `LOW_FIT`,
  because the keywords match almost perfectly and the role shape does not. It closes with *"This is
  the mistake this list exists to stop."*
* **The compound case.** `Tessellate Labs, "Staff Platform Engineer"` → `LOW_FIT/SKIP`, where two
  gates fire at once and the write-up says explicitly that strong overlap does not rescue it.

This repo's own `profile/rubric.md` has the same three shapes, and two of its cases are recorded
mistakes carrying the score the tool actually gave — *"(was WRONGLY scored 82)"* — next to the score
it should have given. That is not an embarrassment left in the file by accident; it is the most
useful line in it, because it names the exact confusion the model fell into.

**Write the case when you notice the bad score, not later.** You need the title, the company, the one
detail that decided it and the score you would have given. All four are in the worklist entry you are
already annoyed at. Adding one takes a minute and it is the highest-value minute available in this
repo.

---

## 5. The rubric outranks every precedent

Since the retrieval work, the user message also carries **precedent**: the most similar past
judgments, pulled from your corpus by `triage/precedent.py`. It is genuinely useful — it is what
keeps the same kind of role scoring the same way across runs — and it is also the mechanism by which
a past mistake would perpetuate itself, because the corpus contains the very mis-scores your
CALIBRATION cases were written to correct.

So the injected block says the precedence rule out loud rather than leaving it to be inferred:

> The GOAL PROFILE ABOVE OUTRANKS EVERY PRECEDENT. It is read in full on every call and is the
> rubric; these are retrieved and merely probable. Where a precedent conflicts with a rule, a hard
> gate or a calibration case in the goal profile, THE RULE WINS and the precedent is simply a past
> mistake — some of these ARE past mistakes, which is why those rules exist.

**That is the reason to write a calibration case rather than to wait for the corpus to correct
itself.** A precedent is retrieved sometimes, for jobs that happen to be similar, and it carries no
authority. A calibration case is read in full on every single job and outranks the precedents by
construction. One is evidence, the other is law — and only one of them is a file you control.

---

## 6. How to tell an edit worked

**Honestly: not by looking at one score.** The scoring call is non-deterministic. Running the *same
code* against the *same twenty jobs* twice moved `fit_score` on **10 of 20 rows, mean ±1.4**, with
`tier` moving on 2 of 20 — that is the noise floor, measured, with nothing changed at all. A single
job moving by two points after a rubric edit is not evidence of anything.

What to do instead, cheapest first:

1. **Read the `red_flags` and the `why`.** A working gate names itself. If you added a cap and the
   job you added it for still ranks high with no mention of the rule, the model did not apply it —
   the rule is ambiguous, not too weak, and the fix is usually a calibration case rather than louder
   wording.
2. **Check you are looking at the right stage.** A job missing entirely is a prefilter result, not a
   rubric result. Look in `Rejected / skipped` before editing anything here.
3. **Run `scripts/before_after.py`** when the change is big enough to be worth twenty Opus calls. It
   re-scores a fixed, deterministic sample of twenty stored JDs — the same twenty both times, in id
   order — and diffs the ranking fields strictly while merely counting the prose. Record before the
   edit, record after, read the diff:

   ```
   .venv/bin/python scripts/before_after.py analyze record before
   # …edit profile/rubric.md…
   .venv/bin/python scripts/before_after.py analyze record after
   .venv/bin/python scripts/before_after.py diff data/reports/ba-analyze-before.json \
                                                 data/reports/ba-analyze-after.json
   ```

   Read the result against the floor above. **A movement smaller than the noise floor is not a
   finding**, and the one signal worth trusting is a `verdict` or `tier` crossing on the specific
   jobs your edit was about. It is an instrument for a human to read, not a test — it has no pass
   condition and it must never grow one.

(`before_after.py` lives in `scripts/`, which is private-side tooling and is not part of the public
snapshot. If you do not have it, the loop is the same one without the sampler: score, read, add a
calibration case, score again next run.)

---

## 7. What does not belong in it

The configuration is split three ways on purpose, and the rubric is the part that is *judgment*:

| goes in | example |
|---|---|
| `profile/rubric.md` | what a good job looks like, what disqualifies one, worked cases |
| `profile/profile.yaml` | **identity** — your inbox, your applied-jobs sheet, the agencies you rate |
| `config/settings.yaml` | **operations** — provider, models, window, prefilter, dedup, concurrency, channel enables |

The split is by *reason to change*, not by tidiness. Operations change when the tool's behaviour
needs tuning and are validated on load against `config/settings.schema.json`; identity changes when
your accounts do; the rubric changes when you learn something about what you want, which is far more
often than either. Keeping prose out of YAML is what makes the rubric un-breakable, and keeping
settings out of the rubric is what keeps them checkable.

Two concrete things that reach for this file and belong elsewhere: **a channel you want switched off**
is `channels.<name>.enabled` in settings, not a rule telling the model to ignore that source — the
model never sees the source and by the time it is scoring you have already paid for the fetch. And
**a company you never want to see again** belongs in `profile/skiplist.md`, which is applied before
scoring, rather than as a named exception in the rubric that costs an Opus call to enforce.

---

## See also

* [`triage-operating.md`](triage-operating.md) — the daily run end to end, and where the score lands.
* [`tuning.md`](tuning.md) — every other tuned number, including the prefilter's own hard-coded bars.
* [`workflows.md`](workflows.md) — the five skills, and which of their assumptions are one person's.
* [`../philosophy.md`](../philosophy.md) — why the tool refuses to apply on your behalf, which is
  ultimately a statement about this file.
