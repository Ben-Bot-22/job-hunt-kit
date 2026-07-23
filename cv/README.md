# cv/ — résumé tailoring

Generate a CV tailored to a specific job description, from a verified evidence base, with an approval gate.

## Use it
Run **`/tailor-cv`** and pass a JD (pasted text, a file path, or a URL). It: reads the base + bullet bank →
decides how much to tailor (light by default) → shows you the proposed changes to approve → renders
`docx + PDF` into a per-application folder. Full workflow: `.claude/skills/tailor-cv/SKILL.md`.

## Layout

This directory holds only the *machinery*. The inputs are yours, so they live in `profile/`, and the
outputs are your decisions, so they live in `applications/`.

```
cv/scripts/render_cv.py           # applies a JSON edit-plan to the base, preserving formatting; --pdf to export.
cv/scripts/make_cover_letter.py   # lays out a cover letter to match the résumé. Holds no content:
                                  # header from profile.yaml -> identity, body from --letter JSON.

profile/profile.yaml              # identity: the name, title and contact line on every document.
profile/cover-letter.json         # your standing cover letter (date/salutation/body/closing).
profile/cv-base.docx              # source of truth: YOUR résumé, edited in place. Bring your own —
                                  # /setup copies it here from the résumé you hand it; render_cv errors
                                  # with instructions if it is missing. NOT seeded (a CV is too personal
                                  # to fake). config/example/cv-base.docx is a worked example of the
                                  # structure render_cv anchors on — copy it over to try the demo.
profile/bullet-bank.md            # verified, evidence-backed bullets — the ONLY source for claims.
                                  # Superset of the base docx + prior PDFs + code-mined accomplishments.
profile/notes/tailoring-playbook.md  # reusable STRATEGY: what to emphasize, per-target playbooks (e.g.
                                  # Braintrust), general principles, the Founder-framing rule. Read first.

applications/                     # per-application outputs (gitignored):
  <date>_<company>_<role>/  ->  <name>_cv.{docx,pdf}, plan.json, jd.txt, README.md
                                  # <name> = profile.yaml identity.name, lowercased + underscored.
```

## Principles
- **Truthful only** — every claim traces to `profile/bullet-bank.md`; obey its DO-NOT-CLAIM list.
- **Approve before generate** — the skill shows changes and waits for the OK.
- **The bank grows** — a genuinely new bullet gets saved back so it's never rewritten.

## Deps
`python-docx` — declared in `cv/requirements.txt` (pulled in by the root `requirements.txt`).
LibreOffice (`soffice`, docx→PDF) and poppler (`pdftoppm`/`pdfinfo`, preview/page-count) are not
pip-installable and only needed for `--pdf` and previews; install them from your package manager.
