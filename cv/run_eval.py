"""Score a frozen set of résumés the same way every time, so a change to the generator is measurable.

**What was missing.** `cv/review_cv.py` grades one résumé against one posting. That is a scorer, and a
scorer alone answers *"is this document good"* but never *"did my change make things better."* Three
things turn a scorer into an evaluation: a **fixed set of cases**, a **score**, and a **re-run you can
compare with the last one**. The scorer shipped first; this adds the other two.

**Two cases, and they are chosen rather than sampled.** `cv/eval_set.json` holds one current tailored
résumé that went through the review loop, and one résumé that was really sent to a real client before
any of the current rules existed — it still carries two claims since retracted. A set of two good
documents would tell us almost nothing. **The weak anchor is what makes a movement in the score
legible**, because a change that helps the good case and breaks the weak one is the failure worth
catching, and an average over similar cases hides exactly that.

**The noise floor is the whole reason a later number can be trusted.** The grader is a model, so it
does not return the same score twice on the same input. Run it twice over unchanged résumés and the
spread between those two runs is the amount the grader disagrees with *itself*. **A later change means
something only if it moves scores by more than that.** Skip this and every rerun produces a figure that
looks like a result and is not one. `scripts/before_after.py` learned this on the scoring pipeline; the
rule transfers unchanged.

**What this is NOT.** Two cases is a small test set, and it is honest to say so. It does not measure
whether the grader itself is any good — that would need labels it does not have. See the bullet-bank
entry that governs how this may be described.

Usage:

    .venv/bin/python -m cv.run_eval                    # score every case, save as a new run
    .venv/bin/python -m cv.run_eval baseline           # ...under a name you choose
    .venv/bin/python -m cv.run_eval --compare          # every saved run side by side

Runs land in `data/reports/cv-eval-<label>.json`. `data/` is the tool's working memory and is never
hand-edited; `--compare` reads those files rather than any summary of them.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from core.settings import REPO_ROOT

from . import jd_parse, review_cv

CASES_PATH = Path(__file__).with_name("eval_set.json")
RESULTS_DIR = REPO_ROOT / "data" / "reports"
DIMENSIONS = ["keyword_coverage", "evidence_depth", "pitch_fit", "readability"]


def cases() -> list[Path]:
    """The frozen set, read from `cv/eval_set.json`."""
    return [REPO_ROOT / c for c in json.loads(CASES_PATH.read_text())["cases"]]


def score_case(folder: Path) -> dict:
    """One case: parse the posting if it has not been parsed yet, then grade the rendered PDF.

    The brief is cached on disk deliberately. Re-parsing per run would put a second non-deterministic
    step in front of the one being measured, so a score change could come from the brief moving rather
    than the résumé — two moving parts and no way to tell which moved.
    """
    brief_path = folder / "jd.json"
    if not brief_path.exists():
        jd_parse.parse_file(folder / "jd.txt")
    r = review_cv.review(json.loads(brief_path.read_text()), review_cv.cv_text(folder))
    absent = [k.keyword for k in r.keywords if k.status == "absent"]
    return {
        "case": folder.name,
        "scores": {d: getattr(r, d).score for d in DIMENSIONS},
        "mean": round(sum(getattr(r, d).score for d in DIMENSIONS) / len(DIMENSIONS), 2),
        "passes": review_cv.passes(r),
        "keywords_total": len(r.keywords),
        "keywords_absent": len(absent),
        "absent": absent,
    }


def run(label: str) -> Path:
    results = [score_case(c) for c in cases()]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"cv-eval-{label}.json"
    out.write_text(json.dumps({"run": label, "results": results}, indent=2, ensure_ascii=False) + "\n")
    return out


def compare() -> str:
    """Every saved run side by side, with the spread per case and the largest spread overall.

    Read the spread first. On runs where nothing changed it IS the noise floor, and any later movement
    smaller than it is not evidence of anything.
    """
    runs = [json.loads(p.read_text()) for p in sorted(RESULTS_DIR.glob("cv-eval-*.json"))]
    if not runs:
        return "no runs yet — `.venv/bin/python -m cv.run_eval`"

    names = [r["run"] for r in runs]
    lines = [f"{'case':<46}" + "".join(f"{n[-14:]:>16}" for n in names) + f"{'spread':>9}"]
    spreads = []
    for case in [r["case"] for r in runs[0]["results"]]:
        means = []
        for r in runs:
            hit = [x for x in r["results"] if x["case"] == case]
            means.append(hit[0]["mean"] if hit else None)
        got = [m for m in means if m is not None]
        spread = round(max(got) - min(got), 2) if len(got) > 1 else 0.0
        spreads.append(spread)
        lines.append(f"{case[:46]:<46}"
                     + "".join(f"{m if m is not None else '-':>16}" for m in means)
                     + f"{spread:>9}")
    if len(runs) > 1 and spreads:
        lines += ["",
                  f"largest spread across runs: {max(spreads)} mean points.",
                  "On runs where nothing changed, that IS the grader disagreeing with itself.",
                  "A later change must move a score by MORE than that to mean anything."]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if "--compare" in argv:
        print(compare())
        return 0
    label = next((a for a in argv if not a.startswith("-")), datetime.now().strftime("%Y-%m-%d-%H%M%S"))
    out = run(label)
    for r in json.loads(out.read_text())["results"]:
        verdict = "PASS " if r["passes"] else "below"
        lines = "  ".join(f"{d[:4]}{r['scores'][d]}" for d in DIMENSIONS)
        print(f"  {r['mean']:>4}  {verdict}  {lines}   {r['keywords_absent']:>2}/{r['keywords_total']:>2} absent"
              f"   {r['case'][:44]}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
