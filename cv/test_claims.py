"""The DO-NOT-CLAIM list, enforced against the documents that actually get sent.

`profile/bullet-bank.md` has carried a DO-NOT-CLAIM list since the start, and the `/tailor-cv` skill is
told to obey it. That was a note, and a note is advice: on 2026-07-25 a bare `SQL` claim was found on
roughly twenty shipped résumés — no project in the bank has ever contained a query, a schema or a
migration. It survived because `SQL & NoSQL data stores` is one phrase in a job description and the
skills line was being copied forward from the previous plan, so nobody re-derived it from evidence.

So the list gets a test. This walks every résumé **edit-plan** — the JSON the renderer consumes, which
is the last machine-readable form of the document before it becomes a docx — and fails on a forbidden
claim. Checking the plan rather than the PDF is deliberate: the plan is the input a human wrote and can
fix, and it is what a re-render reproduces.

**Why the patterns live here and not in the markdown.** The bank is prose for a model to read; this is
a list for a machine to check. They are meant to agree, and the bank names this file so a reader
editing one goes looking for the other — but a regex over prose would fail the day someone rewords a
bullet, and a guard that cries wolf gets deleted.

**This file bans untrue claims and nothing else.** A companion test policing *style* — internal
vocabulary in a bullet — was added and removed the same day (2026-07-25). It failed for a structural
reason worth recording, because the idea will look attractive again: banning a **term** leaves
substitution as the cheapest way to pass, so `int8-quantized, TorchScript-compiled` became
`size-optimized`, which is vaguer, less accurate, and drops the keyword an ML JD actually screens for.
The defect it was reaching for is *a bullet that tells no story*, which no regex sees. That bar lives
in `profile/bullet-bank.md` under the shipped-capability menu, judged when a bullet is picked. Naming
tech is fine here; a sentence a stranger cannot follow is not.

Skips, not failures, on a clone that has neither (`applications/` is gitignored and `profile/` is the
owner's): a stranger has nothing to guard, and `pytest -q` on a fresh clone must never read `failed`.
See `docs/agents/tests.md`.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "The DO-NOT-CLAIM list is enforced against the documents that actually get sent."
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS = REPO_ROOT / "applications"
GENERIC_PLAN = REPO_ROOT / "profile" / "cv-generic-plan.json"

# Each entry: (name, pattern, why). The pattern runs against the plan's rendered text, case-insensitive.
# Keep every entry traceable to a DO-NOT-CLAIM line in `profile/bullet-bank.md`.
FORBIDDEN = [
    (
        "bare SQL",
        # `SQL` on its own or heading a pair, but NOT as the tail of NoSQL/PostgreSQL/MySQL/SQLite —
        # those either are the true claim (NoSQL) or would be real evidence if they ever appeared.
        r"(?<![a-z])sql\b(?!ite)",
        "no project has a query, schema or migration; Reazy is Firestore and job-hunt-kit is JSON "
        "files. Write 'NoSQL data stores (Firestore)'.",
    ),
    (
        "years of experience",
        r"\b(\d+|five|six|seven|eight|nine|ten)\s*\+?\s*years?\b",
        "Ben retracted the years claim on 2026-07-10; the base docx still carries it, so every plan "
        "must replace that sentence rather than let it through.",
    ),
    (
        "paying subscribers",
        r"paying\s+(subscribers?|users?)|\bsubscribers\b",
        "there are no fully paying subscribers (Ben's correction, 2026-07-24). Use '500+ users'.",
    ),
    (
        "MCP servers",
        r"mcp\s+servers?",
        "there is no MCP implementation anywhere; Ben is a consumer of MCP tooling, not a builder of "
        "servers. A JD asking for it is a cover-letter gap.",
    ),
    (
        "GitHub Actions / CI",
        r"github\s+actions|\bci/cd\b",
        "Ben has never used CI meaningfully. The repo has had no `.github/` since f3b385e "
        "(2026-07-22), and what was there before was a cron running the daily script — a scheduled "
        "job, not continuous integration and not a skill. Reazy deploys from a Firebase CLI script. "
        "Nothing on a document may claim either.",
    ),
    (
        "OpenAI / GPT",
        r"\bopenai\b|\bgpt-?4",
        "Ben's standing call (2026-07-10): not part of his stack, and the sole evidence is one "
        "data-cleaning script.",
    ),
]


# Foreign-cloud service names — no project has ever touched one; Ben's cloud is Google Cloud throughout.
# These are ALLOWED on a skills line, as the equivalence parenthetical the playbook mandates
# ("Google Cloud — Cloud Run, … (AWS equivalents: ECS/Fargate, Lambda, …)"), because a skills line is
# an inventory of vocabulary. They are FORBIDDEN in a summary or an experience bullet, which are
# sentences about work done. That seam is the whole reason the mapping is honest; see
# `docs/knowledge-base/personal/tailoring-playbook.md` → "Cloud translation".
#
# Bare `Azure` is deliberately NOT here: the bank has real evidence (multi-provider TTS benchmark
# collection from Azure + Google Cloud TTS, as an API consumer). Azure *infrastructure* is unbacked and
# is listed. The rule bans what is provably unbacked, not every mention of a foreign vendor.
FOREIGN_CLOUD_SERVICES = (
    r"\baws\b|amazon web services|\blambdas?\b|\bdynamo\s?db\b|\bec2\b|\becs\b|\beks\b|"
    r"\bfargate\b|\bcloudfront\b|\bs3\b|\bsns\b|\bsqs\b|\bbedrock\b|\bredshift\b|"
    r"\bcloudformation\b|azure (?:functions|openai|kubernetes|container apps|service bus)|"
    r"\bcosmos\s?db\b|\bblob storage\b|\bservice bus\b|\bkey vault\b|\bai foundry\b|\baks\b"
)


def _prose_strings(path: Path) -> list[str]:
    """The plan's *sentences* — summary and every experience bullet. Not the skills block.

    Structure-aware on purpose: the flattened `_plan_text` above cannot tell a claim from an
    inventory, and the cloud rule is entirely about which of the two a term sits in.
    """
    try:
        plan = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    out: list[str] = []
    if isinstance(plan.get("summary"), str):
        out.append(plan["summary"])
    for key in ("experience", "insert_experience"):
        for entry in plan.get(key) or []:
            if isinstance(entry, dict):
                out.extend(b for b in (entry.get("bullets") or []) if isinstance(b, str))
    return out


def _plan_text(path: Path) -> str:
    """Every string value in the plan, joined — so a claim is caught wherever in the shape it sits."""
    try:
        plan = json.loads(path.read_text())
    except (OSError, ValueError):  # a half-written plan is not this test's business
        return ""

    out: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                if str(key).startswith("_"):  # `_comment` is annotation, not claim
                    continue
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(plan)
    return "\n".join(out)


def _plans() -> list[Path]:
    """The **live** set only — `applications/*/plan.json` plus the generic master, never the archive.

    `applications/archive/` is the record of what was actually sent, and archiving is one-way. Editing
    a plan in there to satisfy this test would falsify that record, and leaving it failing would be a
    permanently red suite with no legal fix — both worse than the omission. The archive is where you
    go to measure how far a claim spread (twelve archived plans name OpenAI, twenty name SQL); this
    test is what stops the next one going out.
    """
    found = sorted(APPLICATIONS.glob("*/plan.json")) if APPLICATIONS.is_dir() else []
    if GENERIC_PLAN.exists():
        found.append(GENERIC_PLAN)
    return found


needs_plans = pytest.mark.skipif(
    not _plans(),
    reason="no résumé edit-plans in this clone — `applications/` is gitignored generated output and "
           "`profile/cv-generic-plan.json` is the owner's. Nothing to guard; the rules themselves are "
           "in profile/bullet-bank.md under DO-NOT-CLAIM.")


@needs_plans
@pytest.mark.parametrize("name,pattern,why", FORBIDDEN, ids=[f[0] for f in FORBIDDEN])
def test_no_forbidden_claim_reaches_a_resume(name: str, pattern: str, why: str) -> None:
    """No plan that renders a document may carry a claim the bank forbids.

    A failure names the file. **Fix the plan and re-render — never loosen the pattern.** If the claim
    became true, the bank's DO-NOT-CLAIM entry is what changes first, with the evidence.
    """
    rx = re.compile(pattern, re.IGNORECASE)
    offenders = sorted(
        str(p.relative_to(REPO_ROOT)) for p in _plans() if rx.search(_plan_text(p))
    )
    assert not offenders, (
        f"{len(offenders)} résumé plan(s) claim '{name}' — {why}\n  " + "\n  ".join(offenders)
    )


@needs_plans
def test_no_cloud_claim_in_an_experience_bullet() -> None:
    """An AWS service name may sit on a skills line as an equivalence; never in a sentence about work.

    This is the honesty seam under the cloud-translation rule (Ben's ruling, 2026-07-31): the résumé
    now carries `Google Cloud — … (AWS equivalents: Lambda, S3, …)` so the token reaches a string
    match, and that is only defensible while no bullet says he did the work. A skills line is an
    inventory; a bullet is a sentence about work done.

    A failure names the file and the line. **Move the term into the Cloud skills line's
    parenthetical** — do not delete the mapping, and do not loosen this pattern. If Ben ever does AWS
    work, the bank's DO-NOT-CLAIM entry changes first, with the evidence.
    """
    rx = re.compile(FOREIGN_CLOUD_SERVICES, re.IGNORECASE)
    offenders = [
        f"{p.relative_to(REPO_ROOT)}: {line}"
        for p in _plans() for line in _prose_strings(p) if rx.search(line)
    ]
    assert not offenders, (
        f"{len(offenders)} résumé bullet(s)/summary claim a foreign-cloud service — no project has ever used "
        "one. The GCP→AWS mapping belongs in the Cloud skills line's parenthetical, where it reads "
        "as vocabulary rather than as work done.\n  " + "\n  ".join(sorted(offenders))
    )
