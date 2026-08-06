"""Grade a rendered CV against the posting's brief, as a screener would — blind to how it was made.

**The problem this solves.** The context that writes a CV is the worst possible judge of it: it knows
what every bullet was *meant* to convey, so a bullet that merely implies React reads as covering
React. On 2026-07-28 a CV answered the posting's second stated requirement on a skills line and in no
bullet, and the same context re-read it twice without noticing. Ben: *"we need you to be more
reliable with cv generation according to the jd. you often miss things."*

**So the reviewer is deliberately starved.** Its entire input is `jd.json` and the text of the
rendered PDF. It never sees the edit-plan, the bullet bank, the tailoring notes, or a word of the
reasoning that produced the document — because every one of those is a way to argue that a weak CV is
actually fine. A screener has none of them either. That is the point of the design, not a limitation
of it: **an independent grade is only worth anything if it cannot be talked to.**

**It reads the PDF, not the plan.** `pdftotext` on the rendered file, so what is graded is what a
recruiter opens. A plan can contain a term that the renderer drops or that lands in a section nobody
reads; the PDF cannot lie about that.

**What it will not do.** It never rewrites the CV. Grading is mechanical and belongs in code; fixing
means deciding what is true, which belongs to `profile/bullet-bank.md` and a human-supervised step.
A script that edits its own claims is how false claims get in. So this prints fixes and stops.

**Gaps are a passing answer.** A must-have keyword the candidate genuinely cannot back is reported as
`no_evidence`, and naming it in the cover letter is the correct outcome — `profile/bullet-bank.md`
says so for SQL, MCP and CI/CD. The failure mode this guards against is the *silent* miss, not the
honest gap. A CV is never blocked; it is only ever described accurately.

Usage:

    .venv/bin/python -m cv.review_cv applications/<folder>

Expects `jd.json` (write it with `python -m cv.jd_parse`) and a rendered `*_cv.pdf` in the folder.
Writes `review.json` beside them and prints the report.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from core import llm
from core.settings import model

_MAX_TOKENS = 8000

# Every dimension is scored 1-5 and every one must clear this to pass. A mean would let a strong
# keyword match paper over a CV that sells nothing, which is the exact failure being designed out.
PASS_BAR = 4
#: Was 3 until 2026-08-04. Measured over 19 documents built that day: the third pass changed nothing
#: on 8 of the 10 in the second wave, because nearly every agent stopped reporting "structural gap" —
#: the remaining misses were `absent` terms with no evidence behind them, and no number of passes
#: writes around a claim that isn't true. The third pass was also where the grader got most insistent
#: about the fixes that must be refused (SQL, CI/CD, invented metrics), so it cost tokens to generate
#: pressure the agent then had to resist. Two passes keep the one that reliably earns its place: pass
#: 1 finds real placement problems, pass 2 confirms the fix landed.
MAX_PASSES = 2


class KeywordVerdict(BaseModel):
    keyword: str
    status: str = Field(description="bullet | skills_only | absent — where the CV evidences this term. "
                                    "'bullet' means a line of experience demonstrates it. 'skills_only' "
                                    "means it appears in the skills block and nowhere else. 'absent' "
                                    "means it is not on the document at all.")
    note: str = Field(default="", description="One short clause: where you found it, or what is missing.")


class Dimension(BaseModel):
    score: int = Field(ge=1, le=5)
    why: str = Field(description="One sentence. Name the specific line, not a general impression.")
    fixes: list[str] = Field(default_factory=list,
                             description="Concrete, actionable edits. 'Add a bullet showing X' — not "
                                          "'strengthen the front-end story'. Empty if the score is 5.")


class Review(BaseModel):
    """A screener's grade. Every dimension is something the CV can be changed to improve."""

    keyword_coverage: Dimension = Field(description="Do the posting's must-have keywords appear at all?")
    evidence_depth: Dimension = Field(description="Are the important ones demonstrated by a BULLET, or "
                                                  "only listed on a skills line? A skills line gets a "
                                                  "document past a filter; a bullet convinces a human.")
    pitch_fit: Dimension = Field(description="Does the CV open with what this posting stresses, and does "
                                             "it speak to what this employer is worried about? A CV that "
                                             "matches every keyword and sells nothing scores low here.")
    readability: Dimension = Field(description="Would a non-technical screener understand each line on one "
                                               "read? Penalize jargon, filler, and any sentence that argues "
                                               "instead of stating a fact.")

    keywords: list[KeywordVerdict] = Field(description="One entry per must_have term in the brief.")
    strongest_line: str = Field(description="The single line most likely to win a callback, quoted.")
    weakest_line: str = Field(description="The line doing the least work, quoted. It is a cut candidate.")


_SYSTEM = """You are a technical recruiter screening one résumé against one job posting. You have the
posting's parsed brief and the text of the résumé. You have nothing else — no notes on how the résumé
was written and no argument for why any line was chosen. Grade only what is on the page.

You are grading two different things and must not confuse them:
  * KEYWORD COVERAGE and EVIDENCE DEPTH — will this document survive a filter and a skim.
  * PITCH FIT — will a hiring manager want this person for THIS role.
A résumé can be perfect on the first and useless on the second.

RULES:
1. A term counts as `bullet` ONLY if a line of experience actually demonstrates it. A bullet that
   makes the term plausible does not count. Be strict: this grade exists because a previous reviewer
   was generous here.
2. `absent` is a legitimate finding, not an error. Some requirements cannot be truthfully claimed by
   this candidate. Report it plainly and move on — do NOT suggest inventing evidence, and do NOT
   suggest wording that implies experience the document does not show.
3. Ignore years-of-experience and degree requirements entirely. They are not in the brief and are not
   something this résumé answers.
4. Fixes must be specific and actionable — name the bullet to add, move, or cut. A fix that cannot be
   acted on without more information is not a fix.
5. Score 5 only when you would not change the dimension. Score 3 or below when a hiring manager would
   plausibly pass. Do not cluster everything at 4.
6. For readability: penalize marketing register (leverage, robust, seamless, spearheaded, results-driven),
   sentences that defend rather than state, and any clause that adds a stance instead of a fact.
"""


def _client():
    return llm.structured(Review, model("cv_review"), max_tokens=_MAX_TOKENS,
                          role="cv_review")


def cv_text(folder: Path) -> str:
    """The rendered PDF as plain text — what a screener actually reads.

    The PDF rather than the docx or the plan: the renderer is the last thing that can change the
    document, so anything earlier is a claim about the output rather than the output.
    """
    pdfs = sorted(folder.glob("*_cv.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"no rendered *_cv.pdf in {folder} — render before reviewing")
    out = subprocess.run(["pdftotext", "-layout", str(pdfs[0]), "-"],
                         capture_output=True, text=True, check=True)
    return re.sub(r"\n{3,}", "\n\n", out.stdout).strip()


def review(brief: dict, cv: str) -> Review:
    return _client().invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"POSTING BRIEF (json):\n{json.dumps(brief, indent=2, ensure_ascii=False)}\n\n"
            f"RÉSUMÉ AS RENDERED:\n{cv}"
        )},
    ])


def _dimensions(r: Review) -> list[tuple[str, Dimension]]:
    return [("keyword coverage", r.keyword_coverage), ("evidence depth", r.evidence_depth),
            ("pitch fit", r.pitch_fit), ("readability", r.readability)]


def passes(r: Review) -> bool:
    """Every dimension at or above the bar. Not a mean — a strong keyword match must not carry a weak pitch."""
    return all(d.score >= PASS_BAR for _, d in _dimensions(r))


def report(r: Review) -> str:
    lines: list[str] = []
    verdict = "PASSES" if passes(r) else "BELOW BAR"
    lines.append(f"{verdict}  (bar: every dimension >= {PASS_BAR})")
    lines.append("")
    for name, d in _dimensions(r):
        lines.append(f"  {d.score}/5  {name:<18} {d.why}")
        for f in d.fixes:
            lines.append(f"           FIX: {f}")
    absent = [k for k in r.keywords if k.status == "absent"]
    skills_only = [k for k in r.keywords if k.status == "skills_only"]
    lines.append("")
    lines.append(f"  keywords: {len(r.keywords) - len(absent) - len(skills_only)} in a bullet · "
                 f"{len(skills_only)} skills-line only · {len(absent)} absent")
    for k in skills_only:
        lines.append(f"    skills-only: {k.keyword}" + (f" — {k.note}" if k.note else ""))
    for k in absent:
        lines.append(f"    ABSENT:      {k.keyword}" + (f" — {k.note}" if k.note else ""))
    if absent:
        lines.append("    (an absent term with no evidence is a cover-letter gap — name it, never invent it)")
    lines.append("")
    lines.append(f"  strongest: {r.strongest_line}")
    lines.append(f"  weakest:   {r.weakest_line}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m cv.review_cv <applications/folder>", file=sys.stderr)
        return 2
    folder = Path(argv[0])
    brief_path = folder / "jd.json"
    if not brief_path.exists():
        print(f"no jd.json in {folder} — run `python -m cv.jd_parse {folder}/jd.txt` first", file=sys.stderr)
        return 1
    try:
        text = cv_text(folder)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    r = review(json.loads(brief_path.read_text()), text)
    (folder / "review.json").write_text(json.dumps(r.model_dump(), indent=2, ensure_ascii=False) + "\n")
    print(report(r))
    print(f"\nwrote {folder / 'review.json'}")
    return 0 if passes(r) else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
