"""Semantic dedup — the same req wearing two names, collapsed before it costs an Opus call.

`seen.json` and `channels.common._dedup_key` catch a posting seen twice at the same URL or under the same
`company|title`. Neither can catch the case that actually costs money here: **one client req posted
under a different company name**, which is what agencies do (325 of the 1,144 corpus records are
agency postings) and what aggregators do when they relabel a listing. On 2026-07-20 the corpus held
`AI Engineer @ Global Payments Inc.` and `AI Engineer @ Worldpay` with **byte-identical** 5,608-char
JDs. Exact-key dedup cannot see that, because the key is the thing that differs.

**The two failure directions are not symmetric, and the gate is built around that.** A missed
duplicate costs one Opus call and one extra worklist line — annoying, visible, cheap. A wrong
collapse **silently deletes a real job**: it never reaches the worklist and nothing says it existed.
So the collapse is deliberately hard to trigger, and everything it does is reported.

Three conditions, all required (measured over all 1,144 corpus records, within-run, below):

  1. **Cosine ≥ 0.95** on the bge-small embedding of `title + JD`. The company is left *out* of the
     embedded text on purpose — it is the field that differs in the case we are hunting.
  2. **Word-5-gram Jaccard ≥ 0.80** on the JD text. This is the load-bearing one. Cosine saturates
     on boilerplate: Grafana Labs' postings share so much company blurb that two unrelated reqs hit
     0.93, and `EY — C# Fullstack Engineer` vs `EY — Java Fullstack Engineer` hits 0.944. Embedding
     similarity alone cannot tell "the same req" from "the same boilerplate"; near-verbatim body text
     can.
  3. **Not (same company AND different title).** Two different titles at one employer are two reqs,
     full stop — that is the Grafana / Redhorse / EY family, and no similarity score should ever
     merge them. Same company *and* the same title is a genuine repost under two URLs (Haystack's
     `AI Engineer` appeared 6 times in one run) and does collapse.

Plus a floor: both JDs must be ≥ 500 chars, so two title-only postings can't collapse on a shared
"Apply here!" snippet.

**Measured on the real corpus** (`data/corpus/state-*.json`, 1,144 records, pairs within one run):
the gate fires on 89 pairs → 48 clusters absorbing 63 postings, ~5.5% of a run's Opus calls. Every
one was checked by hand and every one is a real duplicate. The nearest *rejected* different-company
pair is cosine 0.932 with Jaccard 0.004 — two genuinely different LLM roles — so the margin at the
threshold is wide, not knife-edge. Tune 0.95/0.80 **downward** only with that asymmetry in mind: it
buys back at most one Opus call per missed pair and risks losing a job outright.

What is deliberately not done: **cross-run dedup.** This collapses within one run only. Collapsing
against the corpus would suppress a job with no line in today's worklist at all — the fully silent
failure — and a repost days later is often a genuinely re-opened req.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from core.models import Job, composite_id

from . import config

log = logging.getLogger("triage.dedup")

_SHINGLE = 5            # words per shingle — long enough that shared stock phrases don't overlap
_MAX_EMBED_CHARS = 4000  # bge-small reads ~512 word pieces; the rest is weight, not signal
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Group:
    """One surviving posting and everything that merged into it."""
    job: Job
    merged: list[tuple[Job, float, float]] = field(default_factory=list)   # (job, cosine, overlap)


def collapse(jobs: list[Job], *, embedder=None) -> list[Job]:
    """Collapse near-identical postings and return the survivors, annotated with what merged.

    Each surviving `Job` carries `duplicates` — one dict per absorbed posting, with its id, company,
    title, link and the two similarity numbers that justified the merge. That list is what the
    worklist renders and what `_phase1` marks as seen, so a wrong merge is a line Ben can read rather
    than a job that vanished.

    Fails soft in both senses: disabled, degenerate, or broken (no model, no numpy, an embed error)
    all return `jobs` unchanged. Scoring everything is the cheap failure.
    """
    if not config.dedup_enabled() or len(jobs) < 2:
        return jobs
    try:
        groups = group(jobs, embedder=embedder)
    except Exception as e:      # noqa: BLE001 — a broken deduper must never cost the run its worklist
        log.warning("semantic dedup failed (%s) — scoring every posting", e)
        return jobs

    survivors = []
    for g in groups:
        g.job.duplicates = [
            {"id": d.id, "company": d.company, "title": d.title, "link": d.link,
             "similarity": round(cos, 4), "overlap": round(ov, 4)}
            for d, cos, ov in g.merged
        ]
        survivors.append(g.job)
    return survivors


def group(jobs: list[Job], *, embedder=None) -> list[Group]:
    """The gate itself: `jobs` -> one `Group` per surviving posting, input order preserved.

    Split out from `collapse` so a test can see the similarity numbers a merge was made on, rather
    than only its rendered result.
    """
    import numpy as np

    if embedder is None:
        from core.index import FastEmbedEmbeddings
        embedder = FastEmbedEmbeddings()

    # A job a human emailed Ben about is never a dedup candidate. It is not a lead, it is a live
    # thread (see worklist.render), and absorbing one into an agency repost would hide it.
    eligible = [i for i, j in enumerate(jobs) if _eligible(j)]
    if len(eligible) < 2:
        return [Group(j) for j in jobs]

    vectors = np.array(embedder.embed_documents([_embed_text(jobs[i]) for i in eligible]), dtype=float)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms == 0, 1.0, norms)
    sim = unit @ unit.T
    row = {i: a for a, i in enumerate(eligible)}        # job index -> row in `sim`

    shingles = {i: _shingles(jobs[i].jd_text) for i in eligible}
    parent = {i: i for i in eligible}

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    min_cos, min_ov = config.dedup_similarity(), config.dedup_overlap()
    for a, i in enumerate(eligible):
        for b, j in enumerate(eligible[a + 1:], start=a + 1):
            cos = float(sim[a][b])
            if cos < min_cos or not _titles_allow_merge(jobs[i], jobs[j]):
                continue
            if _jaccard(shingles[i], shingles[j]) < min_ov:
                continue
            ri, rj = root(i), root(j)
            if ri != rj:
                parent[ri] = rj

    # The survivor is the posting with the most JD text — it is the one the scorer can judge best —
    # with input order breaking ties, so the result doesn't depend on dict iteration.
    clusters: dict[int, list[int]] = {}
    for i in eligible:
        clusters.setdefault(root(i), []).append(i)
    canonical = {min(members, key=lambda i: (-len(jobs[i].jd_text), i)): members
                 for members in clusters.values()}

    absorbed = {i for members in canonical.values() for i in members} - set(canonical)
    groups = []
    for i, job in enumerate(jobs):
        if i in absorbed:
            continue
        g = Group(job)
        # Reported against the SURVIVOR, not against whichever pair happened to link the cluster —
        # in a chain of three, the number Ben reads has to be the one that justifies *this* merge.
        for j in canonical.get(i, []):
            if j != i:
                g.merged.append((jobs[j], float(sim[row[i]][row[j]]),
                                 _jaccard(shingles[i], shingles[j])))
        groups.append(g)
    return groups


def _eligible(job: Job) -> bool:
    """Enough JD text to compare, and not a live human thread."""
    return not job.from_correspondence and len(job.jd_text or "") >= config.dedup_min_jd_chars()


def _embed_text(job: Job) -> str:
    """Title and JD only. The company is excluded because it is the field the target case differs on."""
    return f"{job.title}\n{job.jd_text[:_MAX_EMBED_CHARS]}".strip()


def _titles_allow_merge(a: Job, b: Job) -> bool:
    """Two different titles at the same employer are two different reqs, whatever they score.

    `composite_id(x, "")` / `composite_id("", x)` are the repo's own normalizers — legal suffixes
    stripped, punctuation flattened — reused so "NVIDIA AI" and "NVIDIA" stay distinct companies
    while "Acme Inc." and "Acme LLC" do not.
    """
    if composite_id(a.company, "") != composite_id(b.company, ""):
        return True
    return composite_id("", a.title) == composite_id("", b.title)


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    words = _WORD.findall((text or "").lower())
    return frozenset(tuple(words[i:i + _SHINGLE]) for i in range(max(0, len(words) - _SHINGLE + 1)))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
