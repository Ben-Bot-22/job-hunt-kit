"""What `cv/batch.py` must get right, and every case is one a real apply doc produced.

The parser reads a document written for a human, so the risk is not that it crashes — it is that it
quietly returns the wrong work: an already-applied job rebuilt, a struck-through duplicate rebuilt,
or a job whose link and folder were on the sub-bullets the reader never looked at.
"""
from __future__ import annotations

import json

import pytest

from cv import batch


DOC = """
## Tier 1 — contract (lead here)
- [x] **Software Developer @ Apex Systems** — LIVE · fit 76
\t- Link: https://www.apexsystems.com/job/3042486_usa/software-developer
\t- Résumé: `applications/2026-07-28_apex-systems_software-developer/`

- [ ] **Lead Engineer @ Motion Recruitment** — LIVE · fit 66
\t- Link: https://motionrecruitment.com/tech-jobs/reston/contract/lead/883467
\t- Résumé: on request

## Tier 2
- [ ] **Agentic AI Engineer @ Motion Recruitment** — fit 77
\t- Link: https://motionrecruitment.com/tech-jobs/charlotte/direct-hire/agentic/883541
\t- Résumé: `applications/2026-07-28_motion-recruitment_agentic-ai-engineer/`

**Also ranked, lower:**
- [ ] **Full-Stack Engineer @ Kivo Health** — fit 63 https://www.linkedin.com/jobs/view/4444699628 — startup.

## Already applied — do NOT re-apply
- ~~**Fullstack Software Engineer @ DATAMARK Technologies** — fit 86~~ — same req as Michael Baker.

## 📬 Reply, don't cold-apply
- [ ] **Senior Engineer @ Insight Global** — a recruiter emailed about this one.
\t- Link: https://example.com/insight-global/senior-engineer

## ⚠ Check by hand — could not fetch automatically
- [ ] **Platform Engineer @ Unknown Co** — linkedin guest fetch exhausted
\t- Link: https://www.linkedin.com/jobs/view/4444000000
"""


@pytest.fixture()
def doc(tmp_path):
    p = tmp_path / "2026-07-28.md"
    p.write_text(DOC, encoding="utf-8")
    return p


def test_skips_applied_and_struck_through(doc):
    """A ticked box is an application already sent; `~~...~~` is a duplicate the run resurfaced.

    Rebuilding either is the one thing a batch must never do — it burns a slot and, for the
    struck-through case, risks a second application to a req Ben is already in.
    """
    roles = {p.role for p in batch.worklist(doc)}
    assert "Software Developer" not in roles
    assert "Fullstack Software Engineer" not in roles
    assert roles == {"Lead Engineer", "Agentic AI Engineer", "Full-Stack Engineer"}


def test_include_done_reopens_the_ticked_ones(doc):
    assert "Software Developer" in {p.role for p in batch.worklist(doc, include_done=True)}


def test_link_and_folder_come_off_the_sub_bullets(doc):
    """The title is on the checkbox line; everything actionable is indented under it."""
    pick = next(p for p in batch.worklist(doc) if p.company == "Kivo Health")
    assert pick.link == "https://www.linkedin.com/jobs/view/4444699628"

    motion = next(p for p in batch.worklist(doc) if p.role == "Agentic AI Engineer")
    assert motion.folder == batch.ROOT / "applications/2026-07-28_motion-recruitment_agentic-ai-engineer"
    assert motion.link.endswith("883541")


def test_a_job_with_no_folder_still_gets_one(doc):
    """A first build has nowhere to point yet, so the folder is derived from the doc's date."""
    pick = next(p for p in batch.worklist(doc) if p.role == "Lead Engineer")
    assert pick.folder.name == "2026-07-28_motion-recruitment_lead-engineer"


def test_a_heading_between_entries_does_not_leak_into_the_one_above(doc):
    """`## Tier 2` ends the Lead Engineer entry; its links must not be attributed upward."""
    pick = next(p for p in batch.worklist(doc) if p.role == "Lead Engineer")
    assert "883541" not in pick.link


def test_only_the_apply_sections_are_work(doc):
    """The audit sections `/job-triage` Step 6 requires are full of `- [ ]` lines that are not jobs.

    `📬 Reply, don't cold-apply` is the one that costs something: those are processes already in
    motion, and a cold application against one cuts across a live conversation. `⚠ Check by hand` is
    a list of JDs nobody could fetch, so there is nothing to write a document against.
    """
    roles = {p.role for p in batch.worklist(doc)}
    assert "Senior Engineer" not in roles
    assert "Platform Engineer" not in roles


def test_an_unrecognized_section_raises_rather_than_guessing(tmp_path):
    """Same reasoning as `scripts/extract.py`: an unclassified section aborts.

    Both guesses are wrong. Treat it as work and the run builds documents for jobs Ben must not
    cold-apply to; treat it as audit and the run silently builds none and reports success.
    """
    p = tmp_path / "2026-07-28.md"
    p.write_text("## Wildcard picks\n- [ ] **Engineer @ Acme** — fit 70\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Wildcard picks"):
        batch.worklist(p)


def test_top_is_a_ceiling_not_a_quota(doc):
    """Document order is rank order, so the cap keeps the strongest. A run that recommends fewer
    than the cap returns fewer — padding to a fixed count manufactures work on jobs below the bar."""
    assert [p.role for p in batch.worklist(doc, top=2)] == ["Lead Engineer", "Agentic AI Engineer"]
    assert len(batch.worklist(doc, top=10)) == len(batch.worklist(doc)) == 3


def test_gloss_cuts_are_deletions_not_rewrites():
    """Every entry must lose a stance and keep every fact — that is the bar §5b sets for a cut."""
    text = "autoscaling under real traffic — GCP experience maps directly to AWS"
    assert batch.degloss(text) == "autoscaling under real traffic"

    nested = {"skills": [{"value": "grounded in the user's own file rather than the model's memory"}]}
    assert batch.degloss(nested)["skills"][0]["value"] == "grounded in the user's own file"


def test_gloss_list_stays_small():
    """A style filter makes substitution the cheapest way to pass — this repo reversed one already.

    The list is deliberately only phrases with no honest rewrite. If it starts growing, the judgement
    half of the pass is being smuggled into code, where no reader can weigh it.
    """
    assert len(batch.GLOSS) <= 12


def test_degloss_plan_reports_what_it_cut(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"summary": "Docker — GCP experience maps directly to AWS"}), encoding="utf-8")

    cut = batch.degloss_plan(plan)

    assert cut == [" — GCP experience maps directly to AWS"]
    assert json.loads(plan.read_text(encoding="utf-8"))["summary"] == "Docker"


def test_degloss_plan_leaves_a_clean_plan_alone(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"summary": "Docker, Cloud Run"}), encoding="utf-8")
    assert batch.degloss_plan(plan) == []


def test_name_slug_is_read_from_the_profile_never_spelled():
    """`scripts/test_leaks.py` asserts no tracked file outside `profile/` carries the owner's name.

    This test states the rule and names nobody: whatever `identity.name` holds, the slug is derived
    from it, so a stranger's clone produces a stranger's filename.
    """
    slug = batch.name_slug()
    assert slug and slug == slug.lower()
    assert " " not in slug
