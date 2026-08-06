"""A posting, turned into the brief a tailored CV is written against.

**Why this file exists.** Before it, there was no artifact between the job description and the
résumé. The JD was read, held in working memory, turned into an edit-plan, and the only check on the
result was the same context re-reading its own work. Nothing was comparable, so nothing could be
verified — and on 2026-07-28 a CV shipped that answered the posting's second stated requirement
("consuming REST/GraphQL APIs") on a skills line and in no bullet at all. The JD had been read in
full. Reading it was never the missing step; **having something to check against** was.

So the parse writes `jd.json` next to `jd.txt` in the application folder, and `cv/review_cv.py`
grades the rendered document against it. The artifact is the point: two passes over the same posting
by the same context agree with each other by construction, which is worth nothing.

**Keywords, not requirement bars.** This deliberately does NOT extract years-of-experience lines, and
the prompt says so twice. Ben's direction (2026-07-28): *"I don't want you to answer years for
experience - it is mainly about keyword filters and selling myself for the role."* A years bar is not
something a résumé can answer — `profile/bullet-bank.md` forbids stating a number at all — so
carrying one into the brief creates a row that can only ever be failed or fudged. What a résumé can
answer is a keyword and a pitch, and those are what this extracts.

**Two halves, and the second is the one people forget.** `must_have`/`nice_to_have` cover *keyword
matching*, which is what gets a document past a screen. `stresses`/`worries`/`lead_with` cover the
*pitch* — what this employer keeps returning to, what they are afraid of hiring, and which project
should therefore open the document. A CV can match every keyword and still read as generic; the
second half is what stops that.

Run it directly, or import `parse`:

    .venv/bin/python -m cv.jd_parse applications/<folder>/jd.txt

Written to be usable outside `/tailor-cv` on purpose — a fixed prompt in a file produces the same
brief every time, which is the whole reason this is code rather than an instruction to read carefully.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from core import llm
from core.settings import model

_MAX_TOKENS = 4000
_MAX_JD = 24000


class Brief(BaseModel):
    """The parsed posting. Every field is something a résumé can act on."""

    company: str = Field(description="Employer name. If an agency posts for an unnamed client, the agency.")
    title: str = Field(description="Role title exactly as posted.")
    employment_type: str = Field(description="contract | contract-to-hire | permanent | unknown")
    cadence: str = Field(description="remote | hybrid | onsite | unknown — what the POSTING says, not what a "
                                     "summary said. Quote the location if one is named.")
    comp: str = Field(default="", description="Posted rate or salary band, verbatim. Empty if undisclosed.")
    role_shape: str = Field(description="One line: what the day job actually is. e.g. 'front-end-primary "
                                        "full-stack IC on an internal platform'. Read the DUTIES, not the title.")

    must_have: list[str] = Field(
        description="Screenable keywords the posting requires: languages, frameworks, tools, platforms, "
                    "practices. NEVER a years-of-experience bar. NEVER a degree. One term per entry, "
                    "written the way the posting writes it so it can be matched.")
    nice_to_have: list[str] = Field(
        description="Same, for preferred/desired/bonus items. If the posting labels its AI or cloud items "
                    "'preferred', they belong HERE — mis-filing them as required makes a role look harder "
                    "than it is.")

    stresses: list[str] = Field(
        description="What the posting keeps returning to, in plain words. The thing mentioned three times, "
                    "or given its own paragraph, or written with unusual specificity.")
    worries: list[str] = Field(
        description="What this employer is plainly anxious about, inferred from the posting's own emphasis "
                    "— 'shifting priorities across business units' means they fear someone who needs "
                    "hand-holding. Say what the anxiety is, not what to write about it.")
    lead_with: list[str] = Field(
        description="Two or three things this CV should open with to sell for THIS role, in priority order.")
    screening_notes: list[str] = Field(
        default_factory=list,
        description="Anything about how this posting is screened: a stated AI recruiter, a portfolio ask, a "
                    "hard authorization line, an assessment before contact, an in-person stage.")


_SYSTEM = """You are parsing a job posting into a brief that a résumé will be written against and then
graded against. Accuracy matters more than completeness: a wrong entry sends the résumé the wrong way.

RULES:
1. NEVER emit a years-of-experience requirement, in any field. Not "3+ years React", just "React".
   The candidate does not state years on his résumé, so a years row is a row that can only be failed.
   Extract the SKILL the years attach to and drop the number.
2. NEVER emit a degree requirement. Same reason.
3. must_have is what the posting marks required/must-have/minimum. nice_to_have is what it marks
   preferred/desired/bonus/plus. If the posting is not explicit, judge by where the item sits. Do not
   promote a preferred item to required — that misrepresents how hard the role is.
4. Keywords are single terms as the posting writes them ("React", "SCSS", "Redux", "Kubernetes"),
   not sentences. They will be string-matched against a résumé.
5. cadence and comp come from the posting's own words. If it says onsite, it is onsite, whatever any
   summary claims.
6. worries are inferred; keep them to what the posting's own emphasis supports. Do not invent a
   psychology for the employer.
"""


def _client():
    return llm.structured(Brief, model("cv_parse"), max_tokens=_MAX_TOKENS,
                          role="cv_parse")


def parse(jd_text: str) -> Brief:
    """Parse posting text into a `Brief`. Raises on model or configuration failure — the caller decides."""
    return _client().invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"JOB POSTING:\n\n{jd_text[:_MAX_JD]}"},
    ])


def parse_file(jd_path: Path) -> Path:
    """Parse `jd.txt` and write `jd.json` beside it. Returns the path written."""
    brief = parse(jd_path.read_text())
    out = jd_path.with_name("jd.json")
    out.write_text(json.dumps(brief.model_dump(), indent=2, ensure_ascii=False) + "\n")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: python -m cv.jd_parse <path/to/jd.txt>", file=sys.stderr)
        return 2
    jd = Path(argv[0])
    if not jd.exists():
        print(f"no such file: {jd}", file=sys.stderr)
        return 1
    out = parse_file(jd)
    brief = json.loads(out.read_text())
    print(f"wrote {out}")
    print(f"  {brief['company']} — {brief['title']}")
    print(f"  {brief['employment_type']} · {brief['cadence']}" + (f" · {brief['comp']}" if brief["comp"] else ""))
    print(f"  must-have ({len(brief['must_have'])}): {', '.join(brief['must_have'])}")
    print(f"  nice-to-have ({len(brief['nice_to_have'])}): {', '.join(brief['nice_to_have'])}")
    print(f"  lead with: {'; '.join(brief['lead_with'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
