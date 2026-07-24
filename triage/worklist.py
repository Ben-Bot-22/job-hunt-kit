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
            f"{j.title or 'Untitled'} @ {j.company or 'unknown'} — {a.why}  ·  {_link(j)}  ·  `{j.id}`")


def render(jobs: list[Job], *, days: int, skipped_pre: int, banner: str | None = None) -> str:
    # Jobs that came from a human writing to Ben are pulled OUT of the ranked list entirely. They are
    # real and often high-scoring, but they are not fresh leads — on 2026-07-20 a College Board role he
    # was actively interviewing for ranked fit 86 at #2, where acting on the list would have meant
    # cold-applying through an agency to a live process. They get their own section instead.
    correspondence = [j for j in jobs if j.from_correspondence and j.analysis
                      and j.analysis.verdict != "SKIP"]
    corr_ids = {id(j) for j in correspondence}
    jobs_ranked = [j for j in jobs if id(j) not in corr_ids]

    actionable = [j for j in jobs_ranked if j.analysis and j.analysis.verdict != "SKIP"]
    skipped = [j for j in jobs_ranked if j.analysis and j.analysis.verdict == "SKIP"]
    unfetched = [j for j in jobs_ranked if needs_manual_review(j)]

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

    if skipped:
        L.append("\n## ✕ Rejected / skipped (why)")
        L += [f"- [SKIP · {j.analysis.fit_score}] {j.title or 'Untitled'} @ {j.company or 'unknown'} — "
              f"{j.analysis.why}" for j in skipped]

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

    if unfetched:
        L.append("\n## ⚠ Couldn't fetch — investigate manually")
        for j in unfetched:
            used = "email snippet used" if j.jd_source == "email_snippet" else "no JD text available"
            reason = (j.fetch_error or "unfetched").split(" for url")[0][:80]
            L.append(f"- {j.title or 'Untitled'} @ {j.company or 'unknown'} — {_link(j)}  "
                     f"({used}; {reason})")

    return "\n".join(L) + "\n"
