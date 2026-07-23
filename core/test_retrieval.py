"""Tests for the retrieval half of the core — embed, store, retrieve.

Every test here runs **offline with no API key**, which is the property this stage exists to
protect. All but one run with no model either: a deterministic bag-of-words embedder stands in, so
the wiring, the MMR diversity and the empty-corpus path are exercised in milliseconds. The single
test that loads the real 67 MB `bge-small` skips itself when the weights aren't cached — it is the
check that catches a wrong pooling mode, and it asserts on *which record comes back*, never on
vectors, which would pin the model instead of the behaviour.

Run:  .venv/bin/python -m pytest core/ -q
"""
from __future__ import annotations

import json
import math
import re
import zlib

import pytest
from langchain_core.embeddings import Embeddings

from .index import (
    DEFAULT_MODEL,
    JobIndex,
    build_documents,
    build_index,
    document_key,
    model_is_cached,
)

# --- a stand-in embedder with real cosine geometry ----------------------------------------------------

DIMS = 64


class FakeEmbedder(Embeddings):
    """Bag of words hashed into 64 L2-normalised dims. No model, but real geometry: texts that share
    vocabulary really are close, and texts that don't really aren't — which is all MMR needs."""

    def __init__(self):
        self.calls = 0            # how many texts were embedded, so incrementality is observable

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    @staticmethod
    def _vec(text: str) -> list[float]:
        v = [0.0] * DIMS
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[zlib.crc32(word.encode()) % DIMS] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


class ExplodingEmbedder(Embeddings):
    """Proves a claim rather than mocking one: nothing was embedded, because embedding would raise."""

    def embed_documents(self, texts):
        raise AssertionError("embedded when it should not have")

    def embed_query(self, text):
        raise AssertionError("embedded when it should not have")


def _job(company, title, jd, **analysis):
    rec = {"company": company, "title": title, "fetched_jd": jd, "link": f"https://x/{title}"}
    if analysis:
        rec["analysis"] = {"verdict": "FIT", "fit_score": 70, "tier": "PRIMARY", **analysis}
    return rec


# Three near-identical React contract postings — the same client req wearing three agency names, the
# exact shape MMR exists to collapse — plus two genuinely different roles.
REACT_TRIO = [
    _job("TEKsystems", "Senior React Developer",
         "Remote contract React TypeScript Node role for a financial client. 6 months, $70/hr."),
    _job("Insight Global", "Senior React Engineer",
         "Remote contract React TypeScript Node role for a financial client. 6 months, $70/hr."),
    _job("Apex Systems", "React Developer - Remote",
         "Remote contract React TypeScript Node role for a financial client. 6 months, $70/hr."),
]
OTHERS = [
    _job("Cerner", "Java Backend Engineer",
         "Onsite permanent Java Spring Oracle backend position. Kansas City. Full benefits."),
    _job("Werner", "Project Coordinator III",
         "Coordinator tracking schedules and status reports for a delivery organisation."),
]
FIXTURES = REACT_TRIO + OTHERS


def _index(tmp_path, records=FIXTURES, embedder=None):
    index = JobIndex(tmp_path / "index.json", embedder=embedder or FakeEmbedder())
    index.add(build_documents(records))
    return index


# --- retrieval works, and works offline ---------------------------------------------------------------

def test_retrieval_finds_the_obviously_right_record(tmp_path):
    docs = _index(tmp_path).retrieve("remote React TypeScript contract", k=1)
    assert docs[0].metadata["company"] in {"TEKsystems", "Insight Global", "Apex Systems"}


def test_retrieved_precedent_carries_the_whole_judgment(tmp_path):
    """What retrieval is *for*: a precedent that grounds a score has to arrive with score, verdict and
    rationale attached, not as an anonymous slice of a JD."""
    records = [_job("Genesis10", "Senior Full Stack Developer",
                    "Remote contract Python React GCP Terraform agentic AI role.",
                    verdict="STRONG_FIT", fit_score=90, why="Exact GCP+GenAI stack, rate clears the floor.")]
    doc = _index(tmp_path, records).retrieve("Python GCP contract", k=1)[0]
    assert doc.metadata["fit_score"] == 90
    assert doc.metadata["verdict"] == "STRONG_FIT"
    assert "Exact GCP+GenAI stack" in doc.page_content


# --- MMR: diverse, not three copies of one job --------------------------------------------------------

def test_mmr_does_not_return_three_copies_of_the_same_job(tmp_path):
    """The failure this stage most has to avoid: three near-identical postings returned as three
    precedents. The scorer would read one job wearing three hats as corroboration."""
    companies = {d.metadata["company"] for d in _index(tmp_path).retrieve("remote React contract", k=3)}
    assert len(companies & {"TEKsystems", "Insight Global", "Apex Systems"}) < 3
    assert companies & {"Cerner", "Werner"}          # the slot went to something actually different


def test_plain_similarity_would_have_returned_all_three(tmp_path):
    """The control. Without this, the test above could pass because the fixtures aren't similar —
    it has to be MMR doing the work, not the data."""
    index = _index(tmp_path)
    hits = index.store.similarity_search("remote React contract", k=3)
    assert {d.metadata["company"] for d in hits} == {"TEKsystems", "Insight Global", "Apex Systems"}


def test_lambda_mult_one_turns_diversity_off(tmp_path):
    """The dial is real and pointed the right way: 1.0 is pure relevance, and gives the trio back."""
    hits = _index(tmp_path).retrieve("remote React contract", k=3, lambda_mult=1.0)
    assert {d.metadata["company"] for d in hits} == {"TEKsystems", "Insight Global", "Apex Systems"}


# --- day one: an empty corpus is safe -----------------------------------------------------------------

def test_empty_corpus_retrieves_nothing_and_does_not_raise(tmp_path):
    """A stranger on day one has no history. Retrieval returns nothing and scoring proceeds."""
    assert JobIndex(tmp_path / "index.json", embedder=FakeEmbedder()).retrieve("anything") == []


def test_empty_corpus_does_not_even_embed_the_query(tmp_path):
    """Stronger, and the reason it matters: day one must not be blocked on a 67 MB download either."""
    assert JobIndex(tmp_path / "index.json", embedder=ExplodingEmbedder()).retrieve("anything") == []


def test_blank_query_retrieves_nothing(tmp_path):
    assert _index(tmp_path).retrieve("   ") == []


def test_build_index_over_an_empty_corpus_dir(tmp_path):
    index = build_index(tmp_path, embedder=ExplodingEmbedder())
    assert len(index) == 0
    assert index.retrieve("react") == []


# --- one file, deletable, incremental -----------------------------------------------------------------

def test_index_persists_to_one_file_beside_the_corpus(tmp_path):
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": FIXTURES}))
    index = build_index(tmp_path, embedder=FakeEmbedder())
    assert (tmp_path / "index.json").is_file()
    assert len(index) == 5


def test_a_deleted_index_rebuilds(tmp_path):
    """The whole recovery procedure for a corrupt index: delete the file, run again."""
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": FIXTURES}))
    build_index(tmp_path, embedder=FakeEmbedder())
    (tmp_path / "index.json").unlink()
    assert len(build_index(tmp_path, embedder=FakeEmbedder())) == 5


def test_a_corrupt_index_file_rebuilds_rather_than_crashing(tmp_path):
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": FIXTURES}))
    (tmp_path / "index.json").write_text("{ half written")
    assert len(build_index(tmp_path, embedder=FakeEmbedder())) == 5


def test_reload_from_disk_retrieves_without_re_embedding(tmp_path):
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": FIXTURES}))
    build_index(tmp_path, embedder=FakeEmbedder())

    reopened = JobIndex(tmp_path / "index.json", embedder=FakeEmbedder())
    assert len(reopened) == 5
    assert reopened.retrieve("remote React contract", k=1)
    assert reopened.embeddings.calls == 0        # vectors came off disk; only the query was embedded


def test_a_new_run_embeds_only_the_new_documents(tmp_path):
    """User story 13: a month of corpus must not mean a long wait every morning."""
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": FIXTURES}))
    build_index(tmp_path, embedder=FakeEmbedder())

    (tmp_path / "state-2026-07-21.json").write_text(json.dumps(
        {"jobs": [_job("Motion Recruitment", "Platform Engineer", "Remote contract Go and Kubernetes.")]}))
    embedder = FakeEmbedder()
    index = build_index(tmp_path, embedder=embedder)
    assert embedder.calls == 1                   # not 6
    assert len(index) == 6


def test_re_indexing_an_unchanged_corpus_embeds_nothing(tmp_path):
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": FIXTURES}))
    build_index(tmp_path, embedder=FakeEmbedder())
    embedder = FakeEmbedder()
    build_index(tmp_path, embedder=embedder)
    assert embedder.calls == 0


def test_a_rescored_record_replaces_its_entry_rather_than_duplicating_it(tmp_path):
    """A posting prefiltered on Monday and scored on Tuesday is one job, and the live judgment wins."""
    prefiltered = _job("TEKsystems", "Senior React Developer", "Remote contract React role.")
    index = _index(tmp_path, [prefiltered])
    assert index.retrieve("react", k=1)[0].metadata["scored"] is False

    scored = {**prefiltered, "analysis": {"verdict": "FIT", "fit_score": 72, "tier": "PRIMARY",
                                          "why": "Solid remote contract."}}
    assert index.add(build_documents([scored])) == 1
    assert len(index) == 1
    assert index.retrieve("react", k=1)[0].metadata["fit_score"] == 72


def test_document_key_is_the_dedup_identity_not_the_run(tmp_path):
    """The same posting in two runs is one entry — the key is `company|title`, as in `seen.json`."""
    monday = build_documents([{**REACT_TRIO[0], "_run": "2026-07-20"}])[0]
    tuesday = build_documents([{**REACT_TRIO[0], "_run": "2026-07-21"}])[0]
    assert document_key(monday) == document_key(tuesday)


def test_markdown_chunks_key_on_their_heading_path(tmp_path):
    from .index import chunk_markdown
    a, b = chunk_markdown("# Guide\n\nintro\n\n## Auth\n\nbody\n", source="docs/g.md")
    assert document_key(a) != document_key(b)
    assert "Guide > Auth" in document_key(b)


# --- the one test that loads the real model -----------------------------------------------------------

@pytest.mark.skipif(not model_is_cached(), reason=f"{DEFAULT_MODEL} weights are not cached")
def test_real_fastembed_retrieves_the_obviously_right_record(tmp_path):
    """The pooling check, stated as behaviour. bge-small is a **CLS**-pooling model; fastembed takes
    `embeddings[:, 0]` and normalises, which is correct — but a wrong pooling mode anywhere in the
    chain shows up as retrieval that no longer distinguishes a React contract from a Java perm role.
    Assert on which record comes back, never on the vectors, which would pin the model instead."""
    from .index import FastEmbedEmbeddings

    index = JobIndex(tmp_path / "index.json", embedder=FastEmbedEmbeddings())
    index.add(build_documents(FIXTURES))

    react = index.retrieve("remote React and TypeScript contract role", k=1)[0]
    assert react.metadata["company"] in {"TEKsystems", "Insight Global", "Apex Systems"}

    java = index.retrieve("on-site permanent Java Spring backend job", k=1)[0]
    assert java.metadata["company"] == "Cerner"

    coordinator = index.retrieve("project coordinator tracking schedules and status reports", k=1)[0]
    assert coordinator.metadata["company"] == "Werner"
