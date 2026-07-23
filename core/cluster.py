"""Clustering over a free-text corpus field — eight spellings of one idea, counted once.

**Any aggregate over a free-text field is wrong without this, and wrong confidently.** The scorer
writes its own prose every call, so the same finding arrives under a different spelling every time.
Over the 1,144-record corpus the field `red_flags` holds **3,606 distinct strings**, and the single
most common idea in it — *permanent role, not contract* — is spread across 127 of them: `Permanent
role, not contract` (235), `Permanent, not contract` (110), `Permanent full-time, not contract` (48),
`Permanent role, not contract — ranks below equivalent contract` (41), `Likely permanent, not
contract` (20), `Permanent role, not contract/CTH` (17), and a long tail. A plain `Counter` reports
that as a 235-count finding sitting below nothing, when it is a **670-count** finding sitting well
above everything. `source_platform` fragments the same way three ways
(`remotevibecodingjobs.com` 235 / `remotevibecodingjobs` 133 / `vibe-coding` 115), and
`resume_keywords` splits `Node` from `Node.js` and `LLM` from `LLM apps`.

This is machinery. Stage 5's market report consumes it; nothing here renders anything.

## The rule

Distinct values are embedded once each with the same `bge-small` used everywhere else, then grouped
**greedily from the most frequent value outward**: the commonest unassigned spelling becomes a seed,
and every unassigned value close enough to *the seed* joins it. Not single-link agglomeration —
single-link chains, and a chain is exactly how "permanent, not contract" ends up in the same bucket
as "no rate posted" via two hops nobody can see. Every member is compared against the label it is
filed under, so a wrong grouping is one number on one line.

Two signals, either sufficient:

  * **Cosine ≥ 0.82** on the phrase embedding. Measured on the real corpus: `Likely permanent, not
    contract` sits at 0.84 from the seed, and the first genuinely different idea (`Not a real
    full-stack role`) at 0.78 — so the threshold sits in a real gap, not on a knife edge. `Node` /
    `Node.js` is 0.859 and merges; `React` / `Next.js` is 0.689 and does not.
  * **Character-4-gram containment ≥ 0.9** for values of ≥ 8 normalised characters. Embeddings
    cannot see that `vibe-coding` is *inside* `remotevibecodingjobs` — it scores 0.61, a different
    token as far as the model is concerned — and that is one of the three fragments the report has
    to add up. Containment is deliberately near-total and length-floored, so `No equity` does not
    get absorbed into `Equity-heavy comp` (containment 0.6) and a three-letter token cannot swallow
    everything it appears in.

The two failure directions are **not symmetric, and they run opposite to `triage/dedup.py`'s**. There,
a wrong merge silently deleted a real job. Here nothing is deleted: every spelling stays visible under
its cluster with its own count, so a wrong merge is a line you can read and a missed merge is a
finding split in two and under-ranked. Under-counting is the failure that misleads, so this is tuned
*looser* than dedup's 0.95, on purpose.

## Reusing the index

`cluster_corpus` takes the `JobIndex` from `core/index.py` and embeds through **its** embedder, so
there is one model, one cache and one offline story. The phrase vectors are not added to the index:
the index is job documents, retrieved as precedent, and mixing 3,606 fragments of red-flag prose into
it would poison the retrieval that Stage 2's scoring depends on.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Iterable, Mapping

from .index import JobIndex, iter_corpus_records

# Cosine at which two spellings are the same idea. See the module docstring for where the number
# comes from; the measured gap around it runs from 0.84 (a real member) to 0.78 (a real non-member).
SIMILARITY = 0.82

# Character n-gram containment, for the case embeddings structurally cannot see: one value spelled
# *inside* another. Near-total on purpose — a partial overlap is not a containment.
CONTAINMENT = 0.9
_NGRAM = 4
_MIN_CONTAINED_CHARS = 10

_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass
class Member:
    """One spelling inside a cluster, with the number that justifies it being there."""
    value: str
    count: int
    similarity: float          # cosine to the cluster's label, 1.0 for the label itself


@dataclass
class Cluster:
    """One idea: the spelling it is named for, the total, and every spelling that fed it."""
    label: str
    members: list[Member] = dc_field(default_factory=list)

    @property
    def count(self) -> int:
        """What the report prints — the sum over every spelling, which is the whole point."""
        return sum(m.count for m in self.members)

    @property
    def values(self) -> list[str]:
        return [m.value for m in self.members]


def cluster_corpus(
    corpus_dir: Path | str,
    field: str,
    *,
    index: JobIndex | None = None,
    embedder=None,
    **kwargs,
) -> list[Cluster]:
    """Cluster one free-text field across every corpus record. The report's entry point.

    `index` is the `JobIndex` built over the same corpus; its embedder is reused so nothing here
    loads a second model. Pass neither and a `FastEmbedEmbeddings` is constructed — still the same
    weights, just not shared.
    """
    if embedder is None and index is not None:
        embedder = index.embeddings
    return cluster_field(iter_corpus_records(Path(corpus_dir)), field, embedder=embedder, **kwargs)


def cluster_field(records: Iterable[dict], field: str, **kwargs) -> list[Cluster]:
    """Cluster `field` over `records`. See `collect_values` for where the field is looked up."""
    return cluster_values(collect_values(records, field), **kwargs)


def collect_values(records: Iterable[dict], field: str) -> Counter:
    """Every value of `field`, counted. Looks at the record first, then its `analysis`.

    The two live side by side in a state record — `source_platform` is on the record, `red_flags`
    and `resume_keywords` are inside `analysis` — and a caller asking for "the source platform"
    should not have to know which. A list field contributes each element; a string field contributes
    itself; anything else contributes nothing rather than raising.
    """
    counts: Counter = Counter()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        raw = rec.get(field)
        if raw is None and isinstance(rec.get("analysis"), dict):
            raw = rec["analysis"].get(field)
        for value in (raw if isinstance(raw, (list, tuple)) else [raw]):
            if isinstance(value, str) and value.strip():
                counts[value.strip()] += 1
    return counts


def cluster_values(
    counts: Mapping[str, int] | Iterable[str],
    *,
    embedder=None,
    threshold: float = SIMILARITY,
    min_count: int = 1,
) -> list[Cluster]:
    """Distinct values -> clusters, biggest total first.

    Seeded from the most frequent value outward, so a cluster is named for the spelling the corpus
    actually uses most, not for whichever one happened to be embedded first. Ties break on the value
    itself, so two runs over the same corpus produce the same clusters in the same order.

    `min_count` drops values seen fewer than that many times *before* embedding — the tail of a
    free-text field is mostly one-offs, and a report that only wants the recurring findings should
    not pay to embed 2,000 singletons.
    """
    counts = Counter(counts) if not isinstance(counts, Mapping) else counts
    values = sorted((v for v, n in counts.items() if n >= min_count), key=lambda v: (-counts[v], v))
    if not values:
        return []
    if len(values) == 1:
        return [Cluster(values[0], [Member(values[0], counts[values[0]], 1.0)])]

    import numpy as np

    if embedder is None:
        from .index import FastEmbedEmbeddings
        embedder = FastEmbedEmbeddings()

    vectors = np.array(embedder.embed_documents(values), dtype=float)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms == 0, 1.0, norms)
    grams = [_ngrams(v) for v in values]

    clusters: list[Cluster] = []
    unassigned = list(range(len(values)))
    while unassigned:
        seed = unassigned[0]
        # Only the seed's row is ever needed, so this never materialises an n×n matrix — 3,606
        # distinct red flags would be a 100 MB allocation to answer one question at a time.
        sims = unit @ unit[seed]
        members, rest = [], []
        for i in unassigned:
            sim = float(sims[i])
            if i == seed or sim >= threshold or _contains(grams[seed], grams[i]):
                members.append(Member(values[i], counts[values[i]], round(sim, 4)))
            else:
                rest.append(i)
        members.sort(key=lambda m: (-m.count, m.value))
        clusters.append(Cluster(values[seed], members))
        unassigned = rest
    clusters.sort(key=lambda c: (-c.count, c.label))
    return clusters


def _ngrams(value: str) -> frozenset[str]:
    """Character n-grams of the value with everything but letters and digits removed.

    Normalising away punctuation is what lets `vibe-coding` be found inside `remotevibecodingjobs`,
    and n-grams rather than a plain substring test mean a one-character difference costs a little
    rather than everything. Values shorter than the floor return empty, which makes `_contains`
    False — a short token must not swallow every phrase it happens to appear in.
    """
    s = _ALNUM.sub("", (value or "").lower())
    if len(s) < max(_MIN_CONTAINED_CHARS, _NGRAM):
        return frozenset()
    return frozenset(s[i:i + _NGRAM] for i in range(len(s) - _NGRAM + 1))


def _contains(a: frozenset[str], b: frozenset[str]) -> bool:
    """Is the shorter of the two almost entirely inside the longer?"""
    if not a or not b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short & long) / len(short) >= CONTAINMENT
