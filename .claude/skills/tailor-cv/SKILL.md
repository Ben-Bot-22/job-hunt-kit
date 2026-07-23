---
name: tailor-cv
description: Tailor Ben's CV to a specific job description — verified bullets from the bank, present options for approval, then generate docx + PDF into a per-application folder
---

Given a job description, produce a tailored version of Ben's CV. Adapt only as much as the JD needs
(Ben applies to roles that already fit), draw every claim from verified evidence, get Ben's approval on the
proposed changes, then render `docx + PDF` into a clean per-application folder.

**Inputs.** The user passes a JD as pasted text, a file path, or a URL. If a URL, fetch it (WebFetch); if it
needs a login/paywall, ask Ben to paste the text. If nothing was passed, ask for the JD (and the company +
role title, if not obvious from the JD).

**Sources of truth (read these first, every run):**
- Base CV: `profile/cv-base.docx` — never edited in place; it's the template.
- Bullet bank: `profile/bullet-bank.md` — the ONLY place claims may come from. Obey its DO-NOT-CLAIM list.
- **Playbook: `profile/notes/tailoring-playbook.md`** — reusable STRATEGY: general principles, the Founder-framing rule,
  and per-target playbooks (e.g. Braintrust). Read it and apply anything relevant to this target.
- Renderer: `cv/scripts/render_cv.py` — applies a JSON edit-plan to the base, preserving all formatting.

## 0. Identify the target & pull its context
Before touching the JD, classify what you're tailoring for:
- **A specific job/company** (normal case) → proceed to §1 with the JD.
- **A platform / talent marketplace** (Braintrust, Gun.io, Toptal, etc.) → there may be no single JD; it's a
  *positioning* résumé. Check `profile/notes/tailoring-playbook.md` for that target's section and apply it.
  - If the platform has **no playbook section yet**, do a quick research pass (WebSearch/agent: how the platform
    matches talent, client type, what a strong profile emphasizes) BEFORE drafting, then **append a new target
    section to `profile/notes/tailoring-playbook.md`** so it's reusable next time (the playbook grows, like the bank).
Apply the playbook's Founder-framing rule when setting the Reazy header (`experience[].title` override): drop
"(Founder)" for perm/big-co, add "Founder &" for startups/founding-eng, keep "(Founder)" for contract markets.

## 1. Understand the JD
Extract: role title, company, seniority, must-have skills/tech, nice-to-haves, domain, remote/cadence, and the
5–10 keywords an ATS/screener will look for. Note anything the JD stresses that the base CV buries or omits.

## 2. Decide tailoring depth (adaptive — default LIGHT/MODERATE)
- **Light** (JD closely matches the base): rewrite the summary to mirror the JD; reorder the skills lines so the
  most-relevant lead; light reword of a few bullets. Leave bullet *content/count* alone.
- **Moderate** (some emphasis shift): the above + reword bullets to echo JD language and reorder bullets within a
  section so the relevant ones lead.
- **Aggressive** (genuine stretch — different stack/domain): the above + swap in/out or add bullets, all sourced
  from `profile/bullet-bank.md`. Only escalate here when the gap is real; say why in the rationale.
Pick the lowest depth that makes the CV land. State which you chose and why.

## 3. Draft the edit-plan (truthful, evidence-backed)
Build the changes, each traceable to a bank entry:
- **Summary** — one rewrite tuned to the JD (offer a 2nd variant if it's a close call). Keep ~2–4 sentences.
- **Skills** — reorder lines and reorder terms within a line to front-load JD keywords Ben actually has. You may
  add a term ONLY if a bank entry backs it (e.g. surface `Vertex AI / Gemini / Genkit` or `FastAPI` for an AI
  role). Never drop a whole line without saying so.
- **Bullets per experience section** — reword/reorder/(if aggressive) swap. Every bullet must map to a bank
  entry; keep Ben-asserted numbers only if already in the base or bank, never invent numbers.
- Respect **DO-NOT-CLAIM**: Reazy AI = Gemini not Anthropic; CI/CD = jobs-db not Reazy; no undocumented metrics;
  reazy-inference is CPU; nvidia-* architectures aren't Ben's; etc.

## 4. Present options for approval — BEFORE generating anything
Show Ben, in chat, a tight preview he can approve or adjust:
- chosen **depth** + one-line why, and the target **folder name** (see §6).
- the **new summary** (and alt, if any).
- the **skills** block, in the new order (mark what moved / was added).
- a **bullets diff** per changed section: `old → new`, each with a 2–4 word rationale (e.g. "echoes JD 'event-driven'").
- any **flags**: keywords in the JD that Ben has NO evidence for (list them honestly — do not paper over gaps),
  and a note if it's at risk of running >1 page.
Use AskUserQuestion for real either/or choices (e.g. two summary directions); otherwise just lay it out and ask
"approve / tweak?". **Do not render the document until Ben approves.**

## 5. Render (only after approval)
Write the approved plan to the app folder as `plan.json`, then:
```bash
.venv/bin/python cv/scripts/render_cv.py \
  --base profile/cv-base.docx \
  --plan <folder>/plan.json \
  --out  <folder>/<name>_cv.docx --pdf
```
`<name>` is the seeker's own name from `profile/profile.yaml → identity.name`, lowercased and
underscored (`Robin Doe` → `robin_doe`) — the filename a recruiter sees, so it is theirs and not a
literal in this file.
Then **one-page check**: `pdfinfo <folder>/<name>_cv.pdf | grep Pages`. If >1 page, tell Ben and propose
specific trims (usually drop/merge the weakest 1–2 bullets), re-render after he picks. Optionally render a
preview PNG for a visual check: `pdftoppm -png -r 110 -f 1 -l 1 <pdf> <folder>/preview` then view it.

## 6. Naming & storage (folder per application)
Create `applications/<YYYY-MM-DD>_<company-slug>_<role-slug>/` (date = today from context; slugs = lowercase,
hyphenated, e.g. `2026-07-06_acme_senior-fullstack`). Write into it:
- `<name>_cv.docx` and `<name>_cv.pdf` — the deliverables (see the naming rule in step 5).
- `plan.json` — the exact edit-plan used (so a re-render is reproducible).
- `jd.txt` — the job description (or its URL + fetched text).
- `README.md` — company, role, JD link, chosen depth, and a short "why these changes" so the folder is
  self-explanatory months later. This is how Ben remembers why each CV exists.
`applications/` is gitignored — these are local per-application artifacts.

## 7. Feed the knowledge back
If tailoring required a genuinely NEW bullet (not just a reword of an existing one), append it to
`profile/bullet-bank.md` under the right project with its evidence + confidence, so it's reusable and never rewritten.
If you discovered a new verified fact about a repo, add it too. Keep the bank truthful.
**Also feed the playbook:** if you learned something *reusable about a target or about positioning strategy*
(a new platform's playbook, a framing rule, what a client type rewards), add it to `profile/notes/tailoring-playbook.md`.
Rule of thumb: per-application specifics → the app's `README.md`; anything reusable next time → the playbook.

## 8. Report
Tell Ben: folder path, page count, depth used, the headline changes, and any honest gaps (JD keywords with no
evidence) he may want to address in a cover letter. Mention the docx + PDF are ready.

## Rules
- **Truthful only.** Every claim traces to `profile/bullet-bank.md`. Never invent tech, metrics, or ownership. When
  the JD wants something Ben lacks, surface the gap — don't fabricate to fill it.
- **Approval gate is mandatory** — never generate the document before Ben approves the changes (§4).
- **Never edit the base** (`profile/cv-base.docx`) or overwrite another application's folder.
- Refresh the bank (re-mine the repos) if a project changed materially since `bullet-bank.md`'s last-refreshed
  date — note jobs-db's RAG extension is expected to land and should be added when it does.
- Keep to one page unless Ben says otherwise.
