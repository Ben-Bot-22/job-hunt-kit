"""Render ranked jobs -> the markdown worklist Ben reads (triage-plan §9)."""
from __future__ import annotations

from datetime import date

from core.fetch import needs_manual_review
from core.models import Job

_TIER_TITLES = {
    "PRIMARY": "PRIMARY — agency contract, remote or onsite (lead here)",
    "SECONDARY": "SECONDARY — contract platforms",
    "OPPORTUNISTIC": "OPPORTUNISTIC — perm / AI-native standout / startup",
}


_LIVE_BADGE = {"open": "🟢 OPEN", "closed": "🔴 CLOSED", "unknown": "⚪ UNVERIFIED"}


def _liveness_line(j: Job) -> str | None:
    """Availability, stated plainly. 'unknown' is NOT reassurance — see liveness.py."""
    if not j.liveness:
        return None
    badge = _LIVE_BADGE.get(j.liveness, j.liveness)
    detail = f" — {j.liveness_detail}" if j.liveness_detail else ""
    return f"- **status:** {badge}{detail}"


def _focus_block(i: int, j: Job) -> str:
    a = j.analysis
    posted = f" · ⏱{j.posted_hint}" if j.posted_hint else ""
    live = _liveness_line(j)
    return "\n".join(x for x in [
        f"### {i}. {j.title or 'Untitled'} @ {j.company or 'unknown'}  ·  "
        f"{j.final_tier} · {a.verdict} · fit {a.fit_score} · intensity {a.intensity}{posted}",
        live,
        f"- **why:** {a.why}",
        f"- **role:** {a.role_summary}",
        f"- **meets goals:** {a.meets_goals}",
        f"- **red flags:** {', '.join(a.red_flags) if a.red_flags else 'none'}",
        # Ranked despite the hours, and saying so on its own line rather than leaving the reader to
        # infer it from the intensity number in the heading. 2026-08-04.
        (f"- **⚠ hours:** intensity {a.intensity} — ranked below equal-fit sane-hours roles. This is "
         f"a sort, not a verdict; overrule it if the trade is worth it." if _hours_risk(j) else None),
        _duplicates_line(j),
        # Shown only when the scorer actually leaned on a past decision — that is the line that tells
        # Ben a score is grounded in the record rather than invented, so an empty one says nothing.
        f"- **precedent:** {a.precedent}" if a.precedent else None,
        f"- **tailor with:** {', '.join(a.resume_keywords) if a.resume_keywords else '—'}",
        f"- **apply:** {_link(j)}   ·   **id:** `{j.id}`",
    ] if x is not None)


def _link(j: Job) -> str:
    return f"[open ↗]({j.link})" if j.link else "(inline recruiter email)"


def _dup_label(d: dict) -> str:
    """One absorbed posting and the evidence for absorbing it — both numbers, so a merge Ben doubts
    can be judged on the spot instead of by re-running the tool."""
    name = f"{d.get('title') or 'Untitled'} @ {d.get('company') or 'unknown'}"
    # Linked, because a repost of the same title at the same company is otherwise indistinguishable
    # from the survivor on the page — the URL is the only thing that tells them apart.
    label = f"[{name}]({d['link']})" if d.get("link") else name
    return (f"{label} (similarity {float(d.get('similarity', 0)):.2f} · JD overlap "
            f"{float(d.get('overlap', 0)) * 100:.0f}%)")


def _duplicates_line(j: Job) -> str | None:
    """Shown only when something merged. Silence here means nothing was collapsed, never that a
    collapse went unreported."""
    if not j.duplicates:
        return None
    return "- **also posted as:** " + "; ".join(_dup_label(d) for d in j.duplicates)


def _one_line(j: Job) -> str:
    a = j.analysis
    badge = f"{_LIVE_BADGE[j.liveness]} " if j.liveness in _LIVE_BADGE else ""
    dupes = f" ⧉{len(j.duplicates) + 1}" if j.duplicates else ""
    return (f"- {badge}[{j.final_tier} · {a.verdict} · {a.fit_score} · int{a.intensity}]{dupes} "
            f"{j.title or 'Untitled'} @ {j.company or 'unknown'} — {a.why}  ·  {_link(j)}  ·  `{j.id}`"
            f"{_hours_note(j)}")


#: Intensity at or above this SORTS a job down inside its own tier and puts the quoted tell on its
#: line. It no longer removes anything — see `_is_held_back`. 2026-08-04.
HOURS_RISK_INTENSITY = 4

#: The two vocabulary tokens that are about HOURS rather than about a factual gate or a role Ben
#: could not win. Named for the review section's blurb, which has to tell a reader which groups are a
#: judgment call and which are arithmetic. 2026-08-04.
HOURS_REASONS = frozenset({"intensity", "travel"})

#: What a job with no reason on it is filed under. Present so an unrecognised or empty
#: `held_back_reason` still renders somewhere — a grouping that drops its leftovers is a grouping that
#: deletes jobs, which is the one thing this page must never do. Renders LAST, always.
_UNGROUPED = "other / unspecified"

#: The one heading everything refused lives under. There were two — `⏸ Held back` and
#: `✕ Rejected / skipped` — until 2026-07-30, and Ben collapsed them: *"it doesn't matter if they are
#: rejected for intensity as long as i can look at them and audit… i need to review it personally to
#: know so you need to show me. if it is clearly high intensity (4-5) you need confidence to exclude -
#: it should go in the review section with rejected jobs and the reason."* Two sections split one
#: review pass in half and made the reason a property of WHICH heading a job sat under; one section
#: with the reason on the sub-heading is the same information as a thing he can actually read down.
REVIEW_HEADING = "## ✕ Review — held back and rejected (why)"


def _is_held_back(j: Job) -> bool:
    """Out of the ranked list — and since 2026-08-04, only when the SCORER said so.

    The field means "the gate that fired", so a non-empty one IS the answer and the function is now
    just a null check. What was removed is the second, independent route in: `intensity >= 4`
    overrode the scorer and pulled a job whatever reason it had — or hadn't — recorded.

    That threshold hid six roles on 2026-08-03 for things that are simply what a job is: an on-call
    duty, a 24/7 rotation, incident response, 20-30% travel, "move fast, deploy daily". Two were the
    joint-highest-scoring jobs of the run and one was the only live remote agency contract in it. A
    number the model infers from prose snippets is not evidence enough to refuse a job on, so hours
    now SORT (`_hours_risk`) and the analyzer only spends a `held_back_reason` on stated travel over
    40% or a BJAK-class culture claim. Verdict-blind, as before: a refused role must not reach Focus
    because its verdict happened to disagree with its gate.
    """
    a = j.analysis
    return bool(a) and bool((a.held_back_reason or "").strip())


def _hours_risk(j: Job) -> bool:
    """Ranked, but below equal-fit sane-hours roles, and its line carries the tell.

    This is what replaced the held-back threshold: work-life balance is still priority #2 and still
    enforced, but it sorts rather than excludes.
    """
    a = j.analysis
    return bool(a) and a.intensity >= HOURS_RISK_INTENSITY and not _is_held_back(j)


def _hours_note(j: Job) -> str:
    """The suspect wording, on the line, so a reader can overrule the sort at a glance.

    Ben, 2026-08-04: *"you should just rank them lower and name the suspect wording."* Silence here
    means the scorer read no hours risk — never that it read one and declined to say so.
    """
    if not _hours_risk(j):
        return ""
    a = j.analysis
    tell = "; ".join(a.red_flags) if a.red_flags else a.why
    return f"  ·  ⚠ hours (int{a.intensity}): {tell}"


def _review_line(j: Job) -> str:
    """One refused job, with the evidence, in the one format the whole review section uses.

    The quoted tell is the point of the line: intensity is the most inferred number in the analysis,
    so a reader who cannot see what the scorer keyed on has no way to overrule it — and overruling it
    is exactly what this section exists to let him do. `red_flags` is where the scorer is told to put
    the verbatim quote; `why` is the fallback for a refusal that raised none.
    """
    a = j.analysis
    tell = "; ".join(a.red_flags) if a.red_flags else a.why
    return (f"- [{j.final_tier} · {a.verdict} · fit {a.fit_score} · int{a.intensity}] "
            f"**{j.title or 'Untitled'} @ {j.company or 'unknown'}** — {tell}  ·  {_link(j)}  ·  `{j.id}`")


def _reason(j: Job) -> str:
    """The bucket one job is filed under — never blank, so nothing can fall out of the grouping.

    The scorer's own token wins whenever it set one. The old `intensity >= 4` backfill is gone with
    the threshold (2026-08-04): a pre-2026-08-04 record carrying intensity 5 and a blank reason was
    held back by a rule that no longer exists, and re-deriving `intensity` for it here would keep
    hiding exactly the roles this change exists to surface.
    """
    a = j.analysis
    return ((a.held_back_reason or "").strip() if a else "") or _UNGROUPED


def _reason_groups(jobs: list[Job]) -> list[tuple[str, list[Job]]]:
    """Everything refused, bucketed by reason, biggest bucket first, leftovers last.

    Runs over the whole held-back-and-rejected set, not over SKIPs alone — that is what makes
    `role-shape` and `years-bar` reachable at all, since both are CAPS at LOW_FIT and never SKIPs.
    Grouping is deterministic and off a fixed vocabulary on purpose: `why` is free text and an LLM
    clustering of it would give a different set of headings every morning for the same jobs.
    """
    groups: dict[str, list[Job]] = {}
    for j in jobs:
        groups.setdefault(_reason(j), []).append(j)
    ordered = sorted(((r, g) for r, g in groups.items() if r != _UNGROUPED),
                     key=lambda kv: (-len(kv[1]), kv[0]))
    return ordered + ([(_UNGROUPED, groups[_UNGROUPED])] if _UNGROUPED in groups else [])


def _review_section(review: list[Job]) -> list[str]:
    """Everything this run refused, in one block, grouped by why.

    Nothing here was deleted and none of it is final: an intensity group is a set of roles that may
    well be excellent, and the reader's job is to decide. That is why the heading says *review* rather
    than *rejected*, and why every line carries the verdict, the score, the intensity and the tell.
    """
    if not review:
        return []
    L = [f"\n{REVIEW_HEADING} ({len(review)})",
         "_Out of the rankings, not out of the run — nothing here was deleted, and every line carries "
         "its link so any of it can be pulled back in. Grouped by the reason that fired. **`travel` "
         "(over 40%) and `intensity` (a posting claiming the whole person, at the BJAK bar) are the "
         "only two that are about hours** — everything else here failed a factual gate or is a role "
         "that could not be won. On-call, 24/7 rotations, incident response, sprints and travel under "
         "40% no longer reach this section at all; they rank lower with the tell quoted instead._"]
    for reason, group in _reason_groups(review):
        L.append(f"\n### {reason} ({len(group)})")
        L += [_review_line(j) for j in group]
    return L


def _mail_line(r: dict) -> str:
    """One email as a line someone can recognise their own mail in — from, subject, then the machinery."""
    who = r.get("sender") or "(unknown sender)"
    what = r.get("subject") or "(no subject)"
    reason = f"  ·  **{r['reason']}**" if r.get("reason") else ""
    return (f"- **{who}** — {what}{reason}  \n"
            f"  {r.get('n_jobs', 0)} job(s): {r.get('context', '')}  ·  `{r.get('mid', '')}`")


def _held_section(plan) -> list[str]:
    """Mail this run refused to archive. Near the TOP, because it is the only half needing a decision."""
    if plan is None or not plan.held:
        return []
    return [f"\n## 📥 HELD BACK from archiving — {len(plan.held)} email(s) a person appears to have sent",
            "_Still in your inbox, untouched. The From: header names a person, so this run refused to "
            "move it: a wrongly-held alert costs one email left in an inbox, a wrongly-archived human "
            "costs a warm inbound lead permanently. Read these; archive by hand if they are blasts._"
            ] + [_mail_line(r) for r in plan.held]


def _archived_section(plan) -> list[str]:
    """What was touched in the mailbox — the audit half, at the bottom.

    It is here because this page is the only report anybody reads: the `jobs-triage` label is write-only
    in practice, so an archive that is not described here is an archive that happened invisibly.
    """
    if plan is None or not plan.rows:
        return []
    return [f"\n## 📥 Archived this run — {len(plan.rows)} email(s) moved out of the inbox",
            "_Proposed for the archive label. Nothing is deleted — if one of these turns out to be a real "
            "conversation it is in the label, and the guard that should have caught it needs fixing._"
            ] + [_mail_line(r) for r in plan.rows]


def render(jobs: list[Job], *, days: int, skipped_pre: int, banner: str | None = None,
           archive=None) -> str:
    # Jobs that came from a human writing to Ben are pulled OUT of the ranked list entirely. They are
    # real and often high-scoring, but they are not fresh leads — on 2026-07-20 a College Board role he
    # was actively interviewing for ranked fit 86 at #2, where acting on the list would have meant
    # cold-applying through an agency to a live process. They get their own section instead.
    #
    # verdict-blind, like the held-back review section: a SKIP filter here silently dropped 5 of 7
    # correspondence jobs from every rendered section on 2026-07-31 (they weren't ranked, weren't in
    # correspondence, weren't in review — gone). This section already says "NOT fresh leads"; the
    # verdict was never the reason to show it.
    correspondence = [j for j in jobs if j.from_correspondence and j.analysis]
    corr_ids = {id(j) for j in correspondence}
    jobs_ranked = [j for j in jobs if id(j) not in corr_ids]

    # A job whose analysis RAISED carries a SKIP stub, so without this split it renders as a rejection —
    # a judgment that was never made, wearing the words of one. It gets its own section below, because
    # the whole point of not marking it `seen` is that someone knows to retry it.
    errored = [j for j in jobs_ranked if j.analysis_errored]
    err_ids = {id(j) for j in errored}
    jobs_ranked = [j for j in jobs_ranked if id(j) not in err_ids]

    # Computed before the held-back split, deliberately: a JD we failed to fetch is a fetching problem
    # whatever the job scored, and the count in the header would otherwise move for an unrelated reason.
    unfetched = [j for j in jobs_ranked if needs_manual_review(j)]

    # Priority #2, enforced in the rendering rather than in the scoring — but since 2026-08-04 it
    # SORTS rather than excludes. Only the scorer's own `travel` (>40%, stated) and `intensity` (the
    # BJAK-class culture claim) still leave the list; see `_is_held_back`.
    held_back = [j for j in jobs_ranked if _is_held_back(j)]
    held_ids = {id(j) for j in held_back}
    jobs_ranked = [j for j in jobs_ranked if id(j) not in held_ids]

    actionable = [j for j in jobs_ranked if j.analysis and j.analysis.verdict != "SKIP"]
    # The demotion that replaced the threshold. Stable, so `rank.py`'s order survives inside each
    # group and this only ever moves an hours-risk role BELOW an equal-ranked sane-hours one — it
    # never reorders two roles that share a risk level.
    actionable.sort(key=_hours_risk)
    skipped = [j for j in jobs_ranked if j.analysis and j.analysis.verdict == "SKIP"]
    # ONE review set, and it is a partition of what left the rankings: `held_back` was subtracted from
    # `jobs_ranked` before `skipped` was computed, so the two lists cannot overlap and no job renders
    # twice. Everything else on the page renders from a list that had this one removed first.
    review = held_back + skipped

    focus = [j for j in actionable if j.analysis.verdict in ("STRONG_FIT", "FIT")][:5]
    focus_ids = {id(j) for j in focus}
    rest = [j for j in actionable if id(j) not in focus_ids]

    L: list[str] = []
    L.append(f"# Job Worklist — {date.today().isoformat()}   "
             f"({len(jobs)} new · {skipped_pre} skipped pre-eval · {len(unfetched)} couldn't-fetch · "
             f"last {days}d)")

    # A preflight banner (rubric-is-the-example, and only that) rides at the top of the page, because
    # the worklist is read hours after the terminal warning has scrolled away. `__main__` passes it.
    if banner:
        L.append("\n" + banner)

    if correspondence:
        L.append("\n## 📬 Live correspondence — NOT fresh leads (do not cold-apply)")
        L.append("_A human emailed you about these. Some are processes you are already in — check the thread "
                 "before acting. These are never auto-archived._")
        for j in correspondence:
            a = j.analysis
            who = f" · from {j.email_sender}" if j.email_sender else ""
            L.append(f"- [{a.verdict} · fit {a.fit_score}] **{j.title or 'Untitled'} @ "
                     f"{j.company or 'unknown'}**{who} — {a.why}")

    L += _held_section(archive)

    L.append("\n## ▶ Focus today (top picks — put real effort here)")
    if focus:
        for i, j in enumerate(focus, 1):
            L.append("\n" + _focus_block(i, j))
    else:
        L.append("\n_(nothing cleared FIT this run — see the ranked list below)_")

    for tier in ("PRIMARY", "SECONDARY", "OPPORTUNISTIC"):
        group = [j for j in rest if j.final_tier == tier]
        if group:
            L.append(f"\n## {_TIER_TITLES[tier]}")
            L += [_one_line(j) for j in group]

    # One section, grouped by reason, since 2026-07-30. A flat 700-line list of free-text refusals is
    # not something anybody reads, and two separate sections made the reason a property of which
    # heading a job sat under — "show me everything rejected because of X" is the question actually
    # being asked of this page. Ben: *"I want to see all the rejected because of X ones."*
    L += _review_section(review)

    # Every collapse, in one place, including collapses onto a SKIPped job that renders nowhere else.
    # This section is the whole safety story for semantic dedup: a wrong merge deleted a real job, and
    # the only way Ben ever finds out is by reading it here. See triage/dedup.py for the thresholds.
    collapsed = [j for j in jobs if j.duplicates]
    if collapsed:
        n = sum(len(j.duplicates) for j in collapsed)
        L.append(f"\n## ⧉ Collapsed duplicates ({n} posting(s) merged into {len(collapsed)})")
        L.append("_Same req under more than one posting — scored once. Check these: a wrong merge means "
                 "the absorbed job was never scored at all._")
        for j in collapsed:
            L.append(f"- **{j.title or 'Untitled'} @ {j.company or 'unknown'}** absorbed "
                     + "; ".join(_dup_label(d) for d in j.duplicates))

    # Placed BEFORE 'couldn't fetch' because it is the more actionable of the two: these jobs have a JD
    # and no judgment, and one command scores them. They are deliberately absent from `seen.json`, so
    # they come back on their own — this section says how many, and why they failed.
    if errored:
        L.append(f"\n## ⚠ NOT SCORED — the analyzer failed on {len(errored)} job(s)")
        L.append("_No judgment was made on these; the SKIP they carry is a placeholder. They are NOT "
                 "recorded as seen, so they return on the next run — or ask Claude to pick up where this "
                 "run left off (`python -m triage --merge`) to score them now._")
        for j in errored:
            L.append(f"- {j.title or 'Untitled'} @ {j.company or 'unknown'} — {j.analysis.why}  ·  "
                     f"{_link(j)}  ·  `{j.id}`")

    if unfetched:
        L.append("\n## ⚠ Couldn't fetch — investigate manually")
        for j in unfetched:
            used = "email snippet used" if j.jd_source == "email_snippet" else "no JD text available"
            reason = (j.fetch_error or "unfetched").split(" for url")[0][:80]
            L.append(f"- {j.title or 'Untitled'} @ {j.company or 'unknown'} — {_link(j)}  "
                     f"({used}; {reason})")

    L += _archived_section(archive)

    return "\n".join(L) + "\n"
