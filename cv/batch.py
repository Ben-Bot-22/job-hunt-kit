"""The mechanical half of tailoring many CVs at once.

**Why this file exists.** `/tailor-cv` is prose, and prose is followed by one agent, one job at a
time. Everything expensive in it — parsing the posting, drafting the plan, rendering, grading, fixing
— is *per-job and independent*, so a run with seven picks paid seven serial round-trips through the
same loop for no reason. On 2026-07-28 that was the whole wait: six résumés, one after another, while
the only genuinely shared input (`profile/bullet-bank.md`) was a read.

The fan-out itself belongs in a skill, because deciding what a bullet may claim is judgement. What
belongs *here* is everything that is not judgement and was being re-derived in an agent's head every
run:

* **`worklist()`** — which jobs a dated apply doc is actually asking for. Hand-assembling this list
  is what made the batch need a human in the first place.
* **`fit_one_page()`** — render, and if it spills, tighten and re-render until it doesn't. Four
  hand-driven render cycles went into one CV on 2026-07-28; the loop is deterministic, so it is code.
* **`degloss()`** — the substitutions from the AI-gloss pass that are pure string work. The
  *judgement* half of that pass (does this sentence add a fact or a stance?) stays in the skill,
  deliberately: a style ban enforced by a word list is dodgeable by substitution, and this repo
  already reversed one such test. These are only the phrases with no honest rewrite.

**What this module will not do: touch `profile/bullet-bank.md`.** Step 7 of `/tailor-cv` feeds new
bullets back into the bank, and N agents doing that concurrently is how a corrupted bank ships to
every application in the run. Batch agents are read-only on the bank and *propose* additions in their
return value; the accepted ones are applied once, serially, afterwards — **and "accepted" means Ben
said yes, not that the orchestrator liked it. The bank is protected: a line in it becomes a factual
claim about him in a sent document, so he approves every write.** Same precedence shape as the
grader that reports fixes and never applies them (`cv/review_cv.py`), and for the same reason — the
machine proposes, the step with a human in it disposes.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core.settings import PROFILE_DIR, load as _load_yaml

#: Repo root, so a folder path out of an apply doc resolves the same from anywhere.
ROOT = Path(__file__).resolve().parent.parent

#: Where a tailored CV lands. The top level is the live set; `archive/` is one-way.
APPLICATIONS = ROOT / "applications"

BASE_CV = PROFILE_DIR / "cv-base.docx"

#: Escalating tighten steps, tried in order when a render spills onto a second page. Line spacing
#: first because it costs the reader nothing; margins last because they are the most visible.
_TIGHTEN_LADDER = (
    {"line_spacing": 0.96},
    {"line_spacing": 0.94},
    {"line_spacing": 0.94, "margin_tb_in": 0.08},
)

#: Phrases with no honest rewrite — each one is a *stance* whose deletion loses no fact and no
#: keyword, which is the bar `/tailor-cv` §5b sets before a cut. Every entry here was found on a real
#: rendered CV on 2026-07-28 and cut by hand; the hand is the part being removed.
#:
#: This list stays SHORT on purpose. It is not a style filter — a style filter makes substitution the
#: cheapest way to pass, which is exactly how `int8-quantized, TorchScript-compiled` once became the
#: vaguer `size-optimized`. Anything needing a judgement call about the surrounding sentence belongs
#: in the skill, where a reader can make it.
GLOSS: tuple[tuple[str, str], ...] = (
    # Defensiveness: a reply to an objection nobody raised on the page.
    (" — GCP experience maps directly to AWS and Azure", ""),
    (" — GCP experience maps directly to Azure and AWS", ""),
    (" — GCP experience maps directly to AWS", ""),
    (" — GCP experience maps directly to Azure", ""),
    # Negative parallelism: the negated half carries no fact.
    ("grounded in the user's own file rather than the model's memory", "grounded in the user's own file"),
    ("so it judges consistently instead of starting fresh every time", "so it judges consistently across runs"),
)


@dataclass
class Pick:
    """One job a batch run should tailor a CV for."""

    company: str
    role: str
    folder: Path
    link: str = ""
    #: True when the folder already holds a rendered CV — a rebuild, not a first build.
    existing: bool = False
    #: The `fit N` the apply doc printed on the checkbox line, or None when it printed none (a
    #: carryover from an earlier run usually has its score in that run's doc, not this one's).
    fit: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def jd(self) -> Path:
        return self.folder / "jd.txt"

    @property
    def brief(self) -> Path:
        return self.folder / "jd.json"

    @property
    def plan(self) -> Path:
        return self.folder / "plan.json"

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "role": self.role,
            "folder": str(self.folder.relative_to(ROOT)) if self.folder.is_relative_to(ROOT) else str(self.folder),
            "link": self.link,
            "existing": self.existing,
            "fit": self.fit,
            "has_jd": self.jd.exists(),
            "notes": self.notes,
        }


def name_slug() -> str:
    """The filename a recruiter sees, from `profile/profile.yaml → identity.name`.

    Read rather than spelled for the same reason `cv/scripts/make_cover_letter.py` reads it: the
    owner's name is identity, it lives in `profile/`, and `scripts/test_leaks.py` asserts no tracked
    file outside the personal directories carries it.
    """
    identity = (_load_yaml(PROFILE_DIR / "profile.yaml").get("identity") or {})
    name = str(identity.get("name") or "").strip()
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "cv"


# --------------------------------------------------------------------------------------- work list

#: A `- [ ] **Role @ Company**` checkbox. Struck-through entries (`~~...~~`) are already-applied
#: markers and must never become work.
_CHECKBOX = re.compile(r"^\s*-\s*\[(?P<done>[ xX])\]\s*(?P<body>.+)$")
_TITLE = re.compile(r"\*\*(?P<title>[^*]+)\*\*")
_FOLDER = re.compile(r"`(?P<folder>applications/[^`]+?)/?`")
_LINK = re.compile(r"(?P<link>https?://\S+?)(?=[\s)\]]|$)")

#: The score the apply doc prints on every checkbox line — `· fit 78 ·`. Read rather than recomputed
#: because the doc IS the decision record: a score edited by hand during Step 8 is the one that should
#: govern, and re-deriving from `data/corpus/` would silently overrule it. 2026-08-04.
#: Emphasis is allowed between the word and the number because the doc bolds a score it wants read —
#: `fit **85**` is the standard way a standout gets written, and a regex that misses it silently reads
#: the run's best job as unscored. Found immediately on the first real run of this flag.
_FIT = re.compile(r"\bfit\s*[*_]{0,2}\s*(?P<fit>\d{1,3})\b", re.I)

#: A markdown heading. The apply doc's sections carry meaning, and most of them are full of `- [ ]`
#: lines that are not work: `/job-triage` Step 6 requires an audit block for the mail it touched, one
#: for the JDs it could not fetch, and one for roles a human emailed about. A reader can see at a
#: glance which section they are in; a line-at-a-time parser cannot, which is why this exists.
#: `##` and deeper only. A single `#` is the document's title, not a section — a checkbox under it
#: belongs to no section and is treated as work, same as one written before any heading at all.
_HEADING = re.compile(r"^(?P<hashes>#{2,6})\s+(?P<text>.+?)\s*$")

#: Headings whose checkboxes ARE the apply set, in document order — Step 6 writes them strongest
#: first. A carryover that survived Step 4's liveness re-check is a live pick like any other.
_APPLY_HEADING = re.compile(
    r"tier|carryover|focus|primary|submit today|\bcore\b|backup|recommended|\bapply\b",
    re.I,
)

#: Headings whose checkboxes are deliberately not work, checked FIRST so a qualifier wins over the
#: section it qualifies (`### Confirmed dead` under `## Carryover`). `📬 Reply, don't cold-apply` is
#: the one that costs something real: those are processes already in motion, and a cold application
#: against one cuts across a live conversation.
_SKIP_HEADING = re.compile(
    r"reply|already applied|do not re-apply|check by hand|manual check|"
    r"could ?n[o']?t fetch|could not fetch|couldn't resolve|could not resolve|"
    r"\bmail\b|archiv|held back|every job|\bdead\b|killed|rejected|dropped|"
    r"not spend|reference|links \+ ids|config note|timing note",
    re.I,
)


def _split_title(title: str) -> tuple[str, str]:
    """`Role @ Company` -> (company, role). Falls back to the whole string as the role."""
    if "@" in title:
        role, company = title.rsplit("@", 1)
        return company.strip(), role.strip()
    return "", title.strip()


def worklist(apply_doc: Path, include_done: bool = False, top: int | None = None,
             min_fit: int | None = None) -> list[Pick]:
    """Every job a dated apply doc asks for artifacts for, in document order.

    The doc is markdown written for a human, so this reads what is actually there rather than a
    schema: a checkbox line, a bolded `Role @ Company`, an optional `Résumé:` folder in backticks,
    and the first link. Ticked boxes are skipped (they are applications already sent) unless
    `include_done`, and struck-through lines are skipped always — the apply doc uses `~~...~~` for
    "the run resurfaced this under another name," which is the one thing a batch must not rebuild.

    **An entry is a block, not a line.** The apply doc writes the link, the résumé folder and the
    note as indented sub-bullets under the checkbox, so a line-at-a-time reader finds the title and
    none of the things that make the title actionable. Everything up to the next checkbox belongs to
    the entry.

    **Only the apply sections are work, and an unrecognized section is an error rather than a
    guess.** Most of the doc is checkboxes that are not jobs to apply to: the mail audit, the JDs
    that could not be fetched, and `📬 Reply, don't cold-apply` — roles a human emailed about, where
    a cold application cuts across a conversation already running. Returning those was survivable
    while a human picked three to five off the list by eye; it stops being survivable the moment the
    batch takes the top ten as given. So a heading matching neither list raises, on the same
    reasoning as `scripts/extract.py`: an unclassified section aborts rather than being guessed,
    because both guesses are wrong — build the wrong CVs, or silently build none.

    `top` caps the result at the strongest N (document order is rank order). It is a ceiling and not
    a quota: a run that recommends four jobs returns four.

    `min_fit` filters on the score the doc printed rather than on position, and is the better knob of
    the two (2026-08-04). A positional cap truncates a ranked list, so the job at N+1 loses its
    documents for being eleventh rather than for being weak; a score gate keeps every role worth the
    tokens and drops only the ones that were not. Ben: *"for good fits (>70) you should probably
    build anyway."* Measured over 19 run-files, `>= 70` is ~14 roles per run. **An entry whose line
    printed no score is KEPT** — absence of a number is not evidence of a low one, and the carryovers
    are exactly that case.

    A pick with no folder in the doc still comes back, with `folder` derived from the date in the
    filename plus the company and role slugs, because a first build has nowhere to point yet.
    """
    date = _doc_date(apply_doc)
    picks: list[Pick] = []
    seen: set[Path] = set()

    for done, body, is_apply in _entries(apply_doc.read_text(encoding="utf-8"), apply_doc):
        if not is_apply:
            continue
        if "~~" in body:
            continue
        if done and not include_done:
            continue
        t = _TITLE.search(body)
        if not t:
            continue
        company, role = _split_title(t.group("title"))
        if not role:
            continue

        f = _FOLDER.search(body)
        folder = (ROOT / f.group("folder")) if f else (APPLICATIONS / f"{date}_{_slug(company)}_{_slug(role)}")
        if folder in seen:
            continue
        seen.add(folder)

        link = _LINK.search(body)
        fit_m = _FIT.search(body)
        fit = int(fit_m.group("fit")) if fit_m else None
        # Unscored entries survive the gate on purpose — see the `min_fit` note in the docstring.
        if min_fit is not None and fit is not None and fit < min_fit:
            continue
        picks.append(
            Pick(
                company=company,
                role=role,
                folder=folder,
                link=link.group("link") if link else "",
                existing=(folder / f"{name_slug()}_cv.pdf").exists(),
                fit=fit,
            )
        )
        if top is not None and len(picks) >= top:
            break
    return picks


def _classify(text: str, inherited: bool | None, apply_doc: Path) -> bool:
    """Is a section named `text` the apply set? Skip-list first, then apply-list, then inherit.

    **Inheritance is what makes this survivable.** The apply doc is prose written fresh each run and
    its subsection names are invented on the spot — `### Strong, but each needs a move` appeared once
    under `## Tier 2` and means nothing to a word list, but its parent already answered the question.
    So a deeper heading that matches neither list takes its parent's answer, and only a *top-level*
    section nobody can classify raises.
    """
    if _SKIP_HEADING.search(text):
        return False
    if _APPLY_HEADING.search(text):
        return True
    if inherited is not None:
        return inherited
    raise ValueError(
        f"{apply_doc}: unrecognized section {text!r} contains checkboxes, and guessing wrong "
        f"either builds documents for jobs Ben must not cold-apply to or silently builds none. "
        f"Use one of the section headings /job-triage Step 6 names, or add this one to "
        f"_APPLY_HEADING / _SKIP_HEADING in cv/batch.py."
    )


def _entries(text: str, apply_doc: Path):
    """Yield `(done, body, is_apply)` per checkbox — body being the checkbox line plus its
    sub-bullets, and `is_apply` whether the section it sits under is the apply set.

    A new checkbox, or any un-indented line, ends the current entry — headings and prose between
    sections must not leak their links into the entry above them.

    Headings are kept as a stack so a subsection can inherit from the section containing it; a
    heading at level L closes every open heading at L or deeper, which is what `##` following `###`
    means in markdown.
    """
    done: bool | None = None
    buf: list[str] = []
    #: `(level, is_apply)`, outermost first. Empty means no section — a checkbox there is work.
    stack: list[tuple[int, bool]] = []
    entry_apply = True

    for line in text.splitlines():
        m = _CHECKBOX.match(line)
        if m:
            if done is not None:
                yield done, "\n".join(buf), entry_apply
            done = bool(m.group("done").strip())
            buf = [m.group("body")]
            entry_apply = stack[-1][1] if stack else True
        elif line.strip() and not line[:1].isspace():
            if done is not None:
                yield done, "\n".join(buf), entry_apply
                done, buf = None, []
            h = _HEADING.match(line)
            if h:
                level = len(h.group("hashes"))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                inherited = stack[-1][1] if stack else None
                stack.append((level, _classify(h.group("text"), inherited, apply_doc)))
        elif done is not None:
            buf.append(line)

    if done is not None:
        yield done, "\n".join(buf), entry_apply


def _doc_date(apply_doc: Path) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", apply_doc.name)
    return m.group(1) if m else "undated"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


# ------------------------------------------------------------------------------------- gloss cuts

def degloss(value):
    """Apply the mechanical AI-gloss substitutions to any string, list or dict, in place of nothing.

    Returns a new structure; the caller decides whether to write it back. Deliberately narrow — see
    `GLOSS`.
    """
    if isinstance(value, str):
        for old, new in GLOSS:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [degloss(v) for v in value]
    if isinstance(value, dict):
        return {k: degloss(v) for k, v in value.items()}
    return value


def _strings(value):
    """Every string anywhere in a plan, so a phrase is looked for in the data and not in its encoding.

    The obvious version of this searched the raw file text, which finds nothing the moment
    `json.dump` escapes a character — an em-dash is written `\\u2014`, and every gloss phrase here
    starts with one.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)


def degloss_plan(plan_path: Path) -> list[str]:
    """Deglossed in place. Returns the phrases that were actually cut, for the run report."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    present = set()
    for s in _strings(plan):
        present.update(old for old, _ in GLOSS if old in s)

    cut = [old for old, _ in GLOSS if old in present]
    if cut:
        plan_path.write_text(
            json.dumps(degloss(plan), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return cut


# ------------------------------------------------------------------------------------- render loop

def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    if not m:
        raise RuntimeError(f"pdfinfo gave no page count for {pdf}")
    return int(m.group(1))


def render(plan_path: Path, out_docx: Path) -> Path:
    """Render a plan to docx + PDF via the one renderer. Returns the PDF path."""
    subprocess.run(
        [sys.executable, str(ROOT / "cv" / "scripts" / "render_cv.py"),
         "--base", str(BASE_CV), "--plan", str(plan_path), "--out", str(out_docx), "--pdf"],
        check=True, capture_output=True, text=True,
    )
    return out_docx.with_suffix(".pdf")


def fit_one_page(folder: Path, plan_path: Path | None = None) -> dict:
    """Render, and if it spills to a second page, tighten and re-render until it fits.

    Only ever changes the plan's `tighten` block — **never a bullet**. Dropping a bullet to win a
    page is a claim decision, and a claim decision belongs to whoever can weigh what is lost; this
    returns `fits: False` and says how many pages instead, so the skill can pick the trim.

    Returns `{pages, fits, steps, pdf}` where `steps` is what was tried, for the run report.
    """
    plan_path = plan_path or (folder / "plan.json")
    out = folder / f"{name_slug()}_cv.docx"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    original = dict(plan.get("tighten") or {})
    steps: list[str] = []

    pdf = render(plan_path, out)
    pages = page_count(pdf)
    if pages <= 1:
        return {"pages": pages, "fits": True, "steps": steps, "pdf": pdf}

    for step in _TIGHTEN_LADDER:
        plan["tighten"] = {**original, **step}
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        steps.append(", ".join(f"{k}={v}" for k, v in step.items()))
        pdf = render(plan_path, out)
        pages = page_count(pdf)
        if pages <= 1:
            return {"pages": pages, "fits": True, "steps": steps, "pdf": pdf}

    # Out of mechanical room. Put the plan back the way it came and hand the trim to the caller,
    # who is the only one allowed to decide which claim leaves the page.
    plan["tighten"] = original
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pdf = render(plan_path, out)
    return {"pages": page_count(pdf), "fits": False, "steps": steps, "pdf": pdf}


# --------------------------------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m cv.batch", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worklist", help="the jobs a dated apply doc asks for a résumé for, as JSON")
    w.add_argument("apply_doc", type=Path)
    w.add_argument("--include-done", action="store_true", help="also list ticked (already-applied) boxes")
    w.add_argument("--min-fit", type=int, default=None, metavar="N",
                   help="only jobs whose line printed `fit >= N`; entries with no score are kept")
    w.add_argument("--top", type=int, default=None, metavar="N",
                   help="cap at the strongest N (document order is rank order); a ceiling, not a quota")

    f = sub.add_parser("fit", help="render one application folder and tighten until it is one page")
    f.add_argument("folder", type=Path)

    g = sub.add_parser("degloss", help="apply the mechanical gloss cuts to a folder's plan.json")
    g.add_argument("folder", type=Path)

    a = ap.parse_args(argv)

    if a.cmd == "worklist":
        picks = worklist(a.apply_doc, include_done=a.include_done, top=a.top, min_fit=a.min_fit)
        print(json.dumps([p.to_dict() for p in picks], indent=2, ensure_ascii=False))
        return 0

    if a.cmd == "degloss":
        cut = degloss_plan(a.folder / "plan.json")
        print(json.dumps({"cut": cut}, indent=2, ensure_ascii=False))
        return 0

    result = fit_one_page(a.folder)
    print(json.dumps({**result, "pdf": str(result["pdf"])}, indent=2, ensure_ascii=False))
    return 0 if result["fits"] else 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
