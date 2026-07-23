"""Tests for the retrospective clustering.  Run:  .venv/bin/python -m pytest core/ -q

Split deliberately in two, because the two halves protect different things.

**The wiring half is pure** — a deterministic bag-of-words embedder, no model, milliseconds. It
covers where a value is read from, that a count is a *sum* and not a max, that membership is
inspectable, and that the containment rule is bounded.

**The judgment half needs the real `bge-small`**, and there is no honest way around it: "eight
spellings of one idea group together, and two different ideas don't" is a statement about a real
embedding space, and a stub that agrees with it proves only that the stub was written to agree. So
those tests load the real model and skip when the weights aren't cached — the same bargain
`core/test_retrieval.py` makes for the pooling check. Every string in them is a verbatim
`red_flags` / `source_platform` / `resume_keywords` value from `data/corpus/state-*.json`, with its
real observed count.
"""
from __future__ import annotations

import pytest

from .cluster import Cluster, cluster_field, cluster_values, collect_values
from .index import DEFAULT_MODEL, model_is_cached
from .test_retrieval import FakeEmbedder

# The eight commonest real spellings of one idea, with their real corpus counts. A plain `Counter`
# reports the first of these as a 235-count finding; together they are 489, which is what the market
# report has to print.
PERMANENT = {
    "Permanent role, not contract": 235,
    "Permanent, not contract": 110,
    "Permanent full-time, not contract": 48,
    "Permanent role, not contract — ranks below equivalent contract": 41,
    "Likely permanent, not contract": 20,
    "Permanent role, not contract/CTH": 17,
    "Permanent role, not contract (ranks below equivalent contract)": 10,
    "Full-time permanent, not contract": 8,
}

# Three real red flags that are three different findings. Nothing may put two of these together.
DISTINCT = {
    "No rate posted": 119,
    "On-call rotations required": 5,
    "Angular front-end, not React": 5,
}

# The real `source_platform` values, and the three-way fragmentation the spec names.
PLATFORMS = {
    "linkedin": 564,
    "remotevibecodingjobs.com": 235,
    "remotevibecodingjobs": 133,
    "vibe-coding": 115,
    "dice": 71,
}


def _clusters(counts, **kwargs) -> list[Cluster]:
    return cluster_values(counts, embedder=FakeEmbedder(), **kwargs)


def _labelled(clusters: list[Cluster], value: str) -> Cluster:
    """The cluster `value` was filed under — the lookup a human inspecting a wrong merge does."""
    return next(c for c in clusters if value in c.values)


# --- where the values come from -----------------------------------------------------------------------

def test_a_list_field_inside_analysis_is_counted_per_element():
    records = [
        {"analysis": {"red_flags": ["No rate posted", "On-call rotations required"]}},
        {"analysis": {"red_flags": ["No rate posted"]}},
    ]
    assert collect_values(records, "red_flags") == {"No rate posted": 2, "On-call rotations required": 1}


def test_a_string_field_on_the_record_is_counted_too():
    """`source_platform` sits on the record and `red_flags` inside `analysis`; a caller asking for
    "the source platform" must not have to know which."""
    records = [{"source_platform": "linkedin"}, {"source_platform": "dice"}, {"source_platform": "linkedin"}]
    assert collect_values(records, "source_platform") == {"linkedin": 2, "dice": 1}


def test_records_missing_the_field_or_malformed_are_skipped_not_raised_on():
    """The corpus holds half-written and prefiltered records; a retrospective must not die on one."""
    records = [{"analysis": {"red_flags": ["No rate posted"]}}, {}, {"analysis": None},
               {"analysis": {"red_flags": None}}, {"analysis": {"red_flags": ["", "   ", 7]}}, "not a dict"]
    assert collect_values(records, "red_flags") == {"No rate posted": 1}


def test_an_empty_corpus_clusters_to_nothing():
    assert cluster_field([], "red_flags") == []


def test_clustering_the_corpus_embeds_through_the_index_rather_than_loading_a_second_model(tmp_path):
    """Acceptance box 6, made observable. The `JobIndex` is passed in and its embedder does the work,
    so there is one model, one cache and one offline story — not a second embedding stack that
    happens to use the same weights. The phrases are *not* added to the index: it holds job documents
    retrieved as precedent, and 3,606 fragments of red-flag prose in it would poison that."""
    import json

    from .index import JobIndex

    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": [
        {"company": "A", "title": "T", "analysis": {"red_flags": ["No rate posted", "No posted rate"]}},
        {"company": "B", "title": "U", "analysis": {"red_flags": ["No rate posted"]}},
    ]}))
    index = JobIndex(tmp_path / "index.json", embedder=FakeEmbedder())
    before = len(index)

    from .cluster import cluster_corpus
    clusters = cluster_corpus(tmp_path, "red_flags", index=index)

    assert clusters[0].count == 3
    assert index.embeddings.calls == 2      # the two distinct spellings, embedded by the index's own
    assert len(index) == before             # and not stored in it


# --- a cluster is a sum, and it is inspectable --------------------------------------------------------

def test_the_count_is_the_sum_over_every_spelling():
    """The defect this whole module exists to prevent: reporting the biggest spelling's count as the
    finding's count, which under-reports it by however many ways the scorer phrased it."""
    cluster = _clusters({"No rate posted": 119, "No posted rate": 18, "No rate posted.": 17})[0]
    assert cluster.count == 154
    assert cluster.count != 119


def test_every_spelling_stays_visible_under_its_label_with_its_own_count():
    """Nothing is deleted by a merge — that is what makes a wrong grouping readable rather than
    silent, and it is the opposite bargain from `triage/dedup.py`, which really does drop a job."""
    cluster = _clusters({"No rate posted": 119, "No posted rate": 18})[0]
    assert [(m.value, m.count) for m in cluster.members] == [("No rate posted", 119), ("No posted rate", 18)]


def test_each_member_carries_its_similarity_to_the_label_it_was_filed_under():
    """Not to the value that happened to link it in — a diagnosis has to be one number on one line."""
    cluster = _clusters({"Permanent role, not contract": 235, "Permanent, not contract": 110})[0]
    assert cluster.members[0].similarity == 1.0
    assert 0.82 <= cluster.members[1].similarity < 1.0


def test_the_label_is_the_commonest_spelling_not_the_first_one_seen():
    counts = {"No posted rate": 18, "No rate posted": 119}
    assert _clusters(counts)[0].label == "No rate posted"


def test_clusters_come_back_biggest_first():
    counts = {"On-call rotations required": 5, "No rate posted": 119, "No posted rate": 18}
    assert [c.count for c in _clusters(counts)] == [137, 5]


def test_the_same_corpus_clusters_the_same_way_twice():
    """A retrospective that reorders itself between runs is one Ben cannot compare month to month."""
    counts = {**PERMANENT, **DISTINCT}
    first, second = _clusters(counts), _clusters(counts)
    assert [(c.label, c.values) for c in first] == [(c.label, c.values) for c in second]


def test_min_count_drops_the_tail_before_it_is_embedded():
    """1,928 distinct `resume_keywords` are mostly one-offs; a report about recurring demand should
    not pay to embed them. `calls` proves they were dropped *before* the embedder, not after."""
    embedder = FakeEmbedder()
    clusters = cluster_values({"No rate posted": 119, "Seen once": 1}, embedder=embedder, min_count=2)
    assert [c.label for c in clusters] == ["No rate posted"]
    assert embedder.calls == 0        # one surviving value needs no comparison at all


def test_a_single_value_needs_no_model():
    """Day one, or a field with one value: clustering must not be the thing that forces a download."""
    from .test_retrieval import ExplodingEmbedder
    clusters = cluster_values({"linkedin": 564}, embedder=ExplodingEmbedder())
    assert clusters[0].count == 564


# --- the containment rule, which is where over-merging would come from --------------------------------

def test_a_value_spelled_inside_another_merges_even_though_the_embedding_cannot_see_it():
    """`vibe-coding` and `remotevibecodingjobs` embed at 0.60 — a different token as far as the model
    is concerned — and they are two of the three fragments of one source platform."""
    clusters = _clusters({"remotevibecodingjobs.com": 235, "vibe-coding": 115})
    assert len(clusters) == 1
    assert clusters[0].count == 350


def test_a_short_value_does_not_swallow_every_phrase_it_appears_in():
    """The failure direction of containment, found on the real corpus: `Contract` is inside
    `contractor/vendor oversight` and `Vague comp` is inside `Vague company description`, and both
    merges are wrong. The 10-character floor is what stops them."""
    clusters = _clusters({"Contract": 30, "contractor/vendor oversight": 1,
                          "Vague comp": 3, "Vague company description (agency-hosted, no name)": 1})
    assert len(clusters) == 4


def test_a_partial_overlap_is_not_a_containment():
    """`No equity` shares three of its five 4-grams with `Equity-heavy comp` and means the opposite."""
    assert len(_clusters({"No equity offered": 2, "Equity-heavy compensation": 2})) == 2


# --- the judgment: does it actually group ideas ------------------------------------------------------

pytestmark_real = pytest.mark.skipif(
    not model_is_cached(), reason=f"{DEFAULT_MODEL} weights are not cached"
)


@pytestmark_real
def test_the_eight_real_spellings_of_permanent_not_contract_are_one_finding():
    """The headline case, verbatim from the corpus. Counted flat, this idea reports as 235 and ranks
    below nothing; counted as one idea it is 489 and the largest finding in the corpus."""
    from .index import FastEmbedEmbeddings

    clusters = cluster_values(PERMANENT, embedder=FastEmbedEmbeddings())
    assert len(clusters) == 1
    assert clusters[0].label == "Permanent role, not contract"
    assert clusters[0].count == sum(PERMANENT.values()) == 489


@pytestmark_real
def test_three_genuinely_different_red_flags_stay_three_findings():
    """The direction that would make the report a lie in the other way: a rate complaint, an on-call
    complaint and a stack mismatch merged into one bucket nobody can act on."""
    from .index import FastEmbedEmbeddings

    clusters = cluster_values(DISTINCT, embedder=FastEmbedEmbeddings())
    assert len(clusters) == 3


@pytestmark_real
def test_permanent_and_no_rate_posted_do_not_merge_even_though_both_are_common():
    """The control for the test above — the two biggest findings are adjacent in the corpus and
    nothing about their frequency may pull them together."""
    from .index import FastEmbedEmbeddings

    clusters = cluster_values({**PERMANENT, **DISTINCT}, embedder=FastEmbedEmbeddings())
    assert _labelled(clusters, "Permanent role, not contract").count == 489
    assert "No rate posted" not in _labelled(clusters, "Permanent role, not contract").values


@pytestmark_real
def test_the_source_platform_fragments_three_ways_and_adds_back_up():
    """`remotevibecodingjobs.com` / `remotevibecodingjobs` / `vibe-coding` are one board. Reported
    flat, LinkedIn (564) looks like the dominant channel; clustered, the board is 483 and the gap is
    a fifth of what it looked like."""
    from .index import FastEmbedEmbeddings

    clusters = cluster_values(PLATFORMS, embedder=FastEmbedEmbeddings())
    board = _labelled(clusters, "vibe-coding")
    assert board.count == 483
    assert _labelled(clusters, "linkedin").count == 564
    assert _labelled(clusters, "dice").count == 71


@pytestmark_real
def test_gating_terms_fold_their_spellings_without_folding_two_technologies():
    """`resume_keywords` is the field behind "what does the market keep asking for that I don't
    have", and it splits `Node` from `Node.js`. It must not go on to merge `React` with `Next.js`,
    which are a skill Ben has and a skill he is repeatedly asked for."""
    from .index import FastEmbedEmbeddings

    counts = {"React": 407, "Next.js": 88, "Node.js": 218, "Node": 78, "React.js": 12}
    clusters = cluster_values(counts, embedder=FastEmbedEmbeddings())
    assert _labelled(clusters, "Node").count == 296
    assert _labelled(clusters, "Next.js").count == 88
    assert "Next.js" not in _labelled(clusters, "React").values
