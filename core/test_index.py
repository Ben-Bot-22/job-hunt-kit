"""Tests for the document-building half of the retrieval core.  Run:  .venv/bin/python -m pytest core/ -q

Pure — no embedding model, no network, no key. This is where the real bugs live: a decision split in
half, or a chunk that can't be cited. Records below are trimmed from real `data/corpus/state-*.json`
entries so the shapes are the ones the tool actually writes.
"""
from __future__ import annotations

import json

from .index import build_documents, build_markdown_documents, chunk_markdown, iter_corpus_records

# A real 2026-07-20 record, trimmed.
GENESIS10 = {
    "link": "https://remotevibecodingjobs.com/jobs/genesis10-senior-full-stack-developer-remote",
    "company": "Genesis10",
    "title": "Senior Full Stack Developer - Remote",
    "fetched_jd": "Genesis10 is seeking a Senior Full Stack Developer for a major financial "
                  "institution. 5+ month contract. Python, React, GCP, Terraform, agentic AI.",
    "jd_source": "full",
    "analysis": {
        "tier": "PRIMARY",
        "fit_score": 90,
        "intensity": 3,
        "verdict": "STRONG_FIT",
        "why": "Remote contract, exact GCP+GenAI stack, $65/hr well above floor.",
        "role_summary": "5+ month remote contract via Genesis10 for a major financial institution.",
        "meets_goals": "Fully remote, contract, $65/hr clears the floor.",
        "red_flags": ["Enterprise financial-institution bureaucracy", "W2 only, no corp-to-corp"],
        "rate": "$65/hr",
        "cadence": "remote",
        "employment_type": "contract",
        "is_agency": True,
    },
}


# --- a decision is atomic ---------------------------------------------------------------------------

def test_scored_record_is_exactly_one_document():
    """Splitting a decision produces a retrieved fragment that grounds a future score in half a
    judgment. One record in, one document out — always."""
    docs = build_documents([GENESIS10])
    assert len(docs) == 1


def test_document_carries_score_verdict_and_rationale_together():
    doc = build_documents([GENESIS10])[0]
    assert "STRONG_FIT" in doc.page_content
    assert "90/100" in doc.page_content
    assert "exact GCP+GenAI stack" in doc.page_content          # the rationale, in the text
    assert doc.metadata["fit_score"] == 90
    assert doc.metadata["verdict"] == "STRONG_FIT"
    assert doc.metadata["rationale"].startswith("Remote contract")


def test_document_carries_the_jd_and_the_filterable_metadata():
    doc = build_documents([GENESIS10])[0]
    assert "Terraform" in doc.page_content
    assert doc.metadata["company"] == "Genesis10"
    assert doc.metadata["is_agency"] is True
    assert doc.metadata["employment_type"] == "contract"
    assert doc.metadata["id"] == "genesis10|senior full stack developer remote|"
    assert doc.metadata["scored"] is True


def test_judgment_precedes_the_jd_text():
    """bge-small reads the first ~512 word pieces. The judgment must be inside that window, so it is
    written before the JD, not after it."""
    body = build_documents([GENESIS10])[0].page_content
    assert body.index("Verdict:") < body.index("JD:")


def test_long_jd_is_kept_whole():
    """The median corpus JD is 4,596 chars and the longest is 15,006. Nothing is truncated at build
    time — a ceiling here deletes text irreversibly to save memory the corpus doesn't use."""
    jd = ("React and Terraform. " * 800).strip()   # ~16.8k chars, above the longest real JD
    docs = build_documents([{**GENESIS10, "fetched_jd": jd}])
    assert len(docs) == 1
    assert docs[0].page_content.endswith(jd)


# --- malformed input costs recall, never the build ---------------------------------------------------

def test_empty_and_malformed_records_are_skipped_not_raised_on():
    records = [{}, {"company": "", "title": "", "fetched_jd": ""}, None, "garbage", GENESIS10]
    docs = build_documents(records)
    assert len(docs) == 1
    assert docs[0].metadata["company"] == "Genesis10"


def test_unscored_record_still_indexes_for_dedup():
    """A prefiltered job has no analysis but is still a real posting — semantic dedup needs it, so it
    indexes with `scored: False` rather than vanishing."""
    doc = build_documents([{"company": "TEKsystems", "title": "React Developer"}])[0]
    assert doc.metadata["scored"] is False
    assert "fit_score" not in doc.metadata


def test_half_written_state_file_is_skipped(tmp_path):
    (tmp_path / "state-2026-07-20.json").write_text(json.dumps({"jobs": [GENESIS10]}))
    (tmp_path / "state-2026-07-21.json").write_text('{"jobs": [{"company": "Apex",')  # interrupted run
    records = list(iter_corpus_records(tmp_path))
    assert [r["company"] for r in records] == ["Genesis10"]
    assert records[0]["_run"] == "2026-07-20"


# --- markdown is citable -----------------------------------------------------------------------------

MD = """\
# Tailoring playbook

The strategy, in one file.

## Braintrust

### Rate

Bid at the top of the band.

### Profile

Keep the founder line.

## Gun.io

Slower to place.
"""


def _by_path(docs):
    return {d.metadata["heading_path"]: d for d in docs}


def test_markdown_chunk_carries_its_full_heading_path():
    """An uncitable chunk is the whole reason for heading-aware splitting: retrieval has to be able
    to say *where* the claim came from."""
    docs = _by_path(chunk_markdown(MD, source="profile/notes/tailoring-playbook.md"))
    assert "Tailoring playbook > Braintrust > Rate" in docs
    rate = docs["Tailoring playbook > Braintrust > Rate"]
    assert "Bid at the top of the band." in rate.page_content
    assert rate.metadata["heading"] == "Rate"
    assert rate.metadata["heading_level"] == 3
    assert rate.metadata["source"] == "profile/notes/tailoring-playbook.md"


def test_sibling_sections_do_not_bleed_into_each_other():
    docs = _by_path(chunk_markdown(MD))
    assert "founder" not in docs["Tailoring playbook > Braintrust > Rate"].page_content
    assert "Gun.io" not in docs["Tailoring playbook > Braintrust > Profile"].page_content


def test_a_parent_section_holds_only_its_own_prose():
    docs = _by_path(chunk_markdown(MD))
    top = docs["Tailoring playbook"]
    assert "The strategy, in one file." in top.page_content
    assert "Bid at the top" not in top.page_content          # the child's text is the child's chunk


def test_heading_level_pops_back_out():
    """`## Gun.io` after `### Profile` must reattach to the H1, not nest under Braintrust."""
    assert "Tailoring playbook > Gun.io" in _by_path(chunk_markdown(MD))


def test_hash_inside_a_code_fence_is_not_a_heading():
    md = "# Setup\n\n```bash\n# install the deps\npip install -r requirements.txt\n```\n"
    docs = chunk_markdown(md)
    assert len(docs) == 1
    assert docs[0].metadata["heading_path"] == "Setup"
    assert "# install the deps" in docs[0].page_content


def test_preamble_before_the_first_heading_is_kept():
    doc = chunk_markdown("Status: ready-for-agent\n\n# Spec\n\nBody.\n")[0]
    assert doc.metadata["heading_path"] == ""
    assert "Status: ready-for-agent" in doc.page_content


def test_empty_sections_produce_no_chunks():
    docs = chunk_markdown("# A\n\n## B\n\n## C\n\nreal text\n")
    assert [d.metadata["heading_path"] for d in docs] == ["A > C"]


def test_oversize_section_splits_on_paragraphs_keeping_one_path():
    md = "# Long\n\n" + "\n\n".join(f"Paragraph {i}. " + "x" * 300 for i in range(20))
    docs = chunk_markdown(md, max_chars=800)
    assert len(docs) > 1
    assert {d.metadata["heading_path"] for d in docs} == {"Long"}
    assert [d.metadata["part"] for d in docs] == list(range(len(docs)))
    assert all(d.metadata["parts"] == len(docs) for d in docs)


def test_unreadable_markdown_file_is_skipped(tmp_path):
    good = tmp_path / "good.md"
    good.write_text("# Kept\n\nbody\n")
    docs = build_markdown_documents([good, tmp_path / "missing.md"])
    assert [d.metadata["heading_path"] for d in docs] == ["Kept"]
