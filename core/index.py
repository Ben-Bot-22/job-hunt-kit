"""The retrieval core — corpus in, `Document`s out, and the index that searches them.

The **first half is pure**: no embedding model, no network, no API key. It turns what the tool
already stores into what a retriever can search, and it is where the real bugs live, so it is built
and tested with no model involved at all. The **second half** (from `FastEmbedEmbeddings` down)
embeds those documents and retrieves them with MMR — still with no API key and no network once the
model is on disk, which is the property the whole plan rests on.

Two corpora, two rules:

  * **A scored decision record is atomic and is never split.** Score, verdict and rationale only
    mean anything together — a retrieved fragment would ground a future score in half a judgment.
    One corpus record becomes exactly one `Document`.
  * **Markdown is chunked on its heading hierarchy**, carrying the full heading path as metadata, so
    a retrieved chunk is citable rather than anonymous.

**The markdown half is deliberately dormant — the index holds job decisions only.** `profile/notes/`
is not indexed and should not be, because the scorer already reads the goal profile in full on every
call (`profile/rubric.md`, prompt-cached), so retrieval could only hand it a *slice* of a file it
already sees whole. Anything from the notes that should affect scoring belongs in the goal profile,
where it is guaranteed to be read, rather than in an index where it is merely likely to come back.
`chunk_markdown` stays built and tested for a consumer that genuinely needs citable prose; every
document carries `kind` ("job" / "markdown") so filtering is a small change the day one appears.

Nothing here reads a config: callers pass paths in. `core/` imports nothing local (see
`core/__init__.py`), and that includes `triage.config`.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from .models import composite_id

# The JD is kept whole. An earlier 4k-char ceiling was measured and dropped: the median corpus JD is
# 4,596 chars, so it truncated 668 of 1,142 records and deleted 21% of the corpus text to save
# nothing — the whole uncapped corpus is 4.8 MB, the same order as the vectors it sits beside.
# Where a bound *is* load-bearing is injection: three precedents in the analyzer's prompt is real
# token cost per scored job. That belongs at injection time, where it is reversible, not here, where
# it isn't. The embedder reads far less either way (bge-small truncates at 512 word pieces), which is
# why the judgment is written into the page content *before* the JD text.

# Ceiling for one markdown chunk. ~2k chars is about the 512 word pieces bge-small will actually
# read; a section longer than this is split on paragraph boundaries, each part keeping the same
# heading path.
MD_CHUNK_CHARS = 2000

_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


# --------------------------------------------------------------------------------------------------
# Corpus records -> documents
# --------------------------------------------------------------------------------------------------

def iter_corpus_records(corpus_dir: Path) -> Iterator[dict]:
    """Every job record in every `state-*.json` under `corpus_dir`, oldest run first.

    A state file the tool half-wrote (interrupted run) is skipped rather than raising — the index is
    rebuildable, so a bad file costs recall, never the build.
    """
    for path in sorted(Path(corpus_dir).glob("state-*.json")):
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict):
            continue
        for rec in state.get("jobs") or []:
            if isinstance(rec, dict):
                yield {**rec, "_run": path.stem.removeprefix("state-")}


def build_documents(records: Iterable[dict]) -> list[Document]:
    """Corpus records -> one `Document` each. Empty or malformed records are skipped, not raised on."""
    docs = []
    for rec in records:
        doc = record_to_document(rec)
        if doc is not None:
            docs.append(doc)
    return docs


def record_to_document(rec: dict) -> Document | None:
    """One scored record -> exactly one unsplit `Document`, or None if there is nothing to search.

    Nothing to search means no title, no company and no JD text — a record that would embed as noise
    and retrieve as a precedent that says nothing.
    """
    if not isinstance(rec, dict):
        return None
    title = _s(rec.get("title"))
    company = _s(rec.get("company"))
    jd = _s(rec.get("fetched_jd")) or _s(rec.get("email_jd_text"))
    if not (title or company or jd):
        return None

    a = rec.get("analysis") if isinstance(rec.get("analysis"), dict) else None
    lines = [f"{title or '(untitled)'} — {company or '(unknown company)'}"]

    if a:
        traits = [t for t in (_s(a.get("employment_type")), _s(a.get("cadence"))) if t]
        if a.get("is_agency"):
            traits.append("agency")
        rate = _s(a.get("rate"))
        if rate:
            traits.append(rate)
        lines.append(
            f"Verdict: {_s(a.get('verdict')) or 'unknown'} · {_int(a.get('fit_score'))}/100 · "
            f"tier {_s(a.get('tier')) or 'unknown'}" + (f" · {' · '.join(traits)}" if traits else "")
        )
        for label, key in (("Why", "why"), ("Role", "role_summary"), ("Fit", "meets_goals")):
            if _s(a.get(key)):
                lines.append(f"{label}: {_s(a[key])}")
        flags = [_s(f) for f in (a.get("red_flags") or []) if _s(f)]
        if flags:
            lines.append("Red flags: " + " · ".join(flags))
    if jd:
        lines.append("JD: " + jd)

    meta = {
        "kind": "job",
        "id": composite_id(company, title),
        "link": _s(rec.get("link")),
        "company": company,
        "title": title,
        "run": _s(rec.get("_run")),
        "jd_source": _s(rec.get("jd_source")),
        "scored": bool(a),
        # A prefilter kill carries an `analysis` too, but it is a regex verdict, not a judgment.
        # Consumers that offer records back as *precedent* have to be able to tell them apart —
        # showing the scorer "you called this SKIP" when a rule did is teaching it a lie.
        "prefiltered": bool(rec.get("prefiltered")),
    }
    if a:
        meta.update(
            fit_score=_int(a.get("fit_score")),
            verdict=_s(a.get("verdict")),
            tier=_s(a.get("tier")),
            intensity=_int(a.get("intensity")),
            employment_type=_s(a.get("employment_type")),
            cadence=_s(a.get("cadence")),
            is_agency=bool(a.get("is_agency")),
            rate=_s(a.get("rate")),
            rationale=_s(a.get("why")),
        )
    return Document(page_content="\n".join(lines), metadata=meta)


# --------------------------------------------------------------------------------------------------
# Markdown -> heading-aware chunks
# --------------------------------------------------------------------------------------------------

def build_markdown_documents(paths: Sequence[Path] | Iterable[Path]) -> list[Document]:
    """Every markdown file, chunked on its headings. Unreadable files are skipped, not raised on."""
    docs: list[Document] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        docs.extend(chunk_markdown(text, source=str(path)))
    return docs


def chunk_markdown(text: str, *, source: str = "", max_chars: int = MD_CHUNK_CHARS) -> list[Document]:
    """Split markdown on its ATX heading hierarchy, carrying the full heading path as metadata.

    One chunk per section, holding that section's own prose only — a parent's chunk does not repeat
    its children's text. `heading_path` is the whole ancestry (`"Guide > Setup > Auth"`), which is
    what makes a retrieved chunk citable. Sections longer than `max_chars` are split on paragraph
    boundaries into parts that all carry the same path.

    Fenced code is passed through verbatim: a `# comment` inside a fence is not a heading. Setext
    (`===` underline) headings are not recognised — nothing in this repo writes them.
    """
    sections: list[tuple[list[str], list[str]]] = []   # (heading path, body lines)
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    in_fence = False
    fence: str | None = None

    def flush(path: list[str]) -> None:
        if any(line.strip() for line in body):
            sections.append((path, list(body)))
        body.clear()

    for line in (text or "").splitlines():
        m_fence = _FENCE.match(line)
        if m_fence:
            marker = m_fence.group(1)
            if not in_fence:
                in_fence, fence = True, marker
            elif marker == fence:
                in_fence, fence = False, None
            body.append(line)
            continue
        m = None if in_fence else _ATX.match(line)
        if m:
            flush([h for _, h in stack])
            level, heading = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
        else:
            body.append(line)
    flush([h for _, h in stack])

    docs: list[Document] = []
    for path, lines in sections:
        heading_path = " > ".join(path)
        chunk_body = "\n".join(lines).strip()
        header = "\n".join(f"{'#' * (i + 1)} {h}" for i, h in enumerate(path))
        parts = _split_paragraphs(chunk_body, max_chars)
        for i, part in enumerate(parts):
            docs.append(Document(
                page_content=(f"{header}\n\n{part}" if header else part),
                metadata={
                    "kind": "markdown",
                    "source": source,
                    "heading_path": heading_path,
                    "heading": path[-1] if path else "",
                    "heading_level": len(path),
                    "part": i,
                    "parts": len(parts),
                },
            ))
    return docs


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    """Greedily pack paragraphs up to `max_chars`; a single over-long paragraph is hard-split."""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(para[:max_chars])
            para = para[max_chars:]
        if not buf:
            buf = para
        elif len(buf) + 2 + len(para) <= max_chars:
            buf = f"{buf}\n\n{para}"
        else:
            parts.append(buf)
            buf = para
    if buf:
        parts.append(buf)
    return parts


# --------------------------------------------------------------------------------------------------
# The embedder — local, offline, no key
# --------------------------------------------------------------------------------------------------

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Where the ONNX weights live. fastembed's own default is `$TMPDIR/fastembed_cache`, which macOS
# reaps — a temp directory is the wrong home for a 67 MB download the daily run needs. `~/.cache`
# is stable, user-level, and still nothing the repo has to carry.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "fastembed"


class FastEmbedEmbeddings(Embeddings):
    """`bge-small-en-v1.5` served by fastembed (ONNX, CPU, no torch, no key, ~67 MB of weights).

    Ten owned lines instead of a dependency: `langchain-community` is sunset, and the `Embeddings`
    interface it would give us is two methods. The model is constructed on **first use**, not on
    construction, so building or opening an index costs nothing until something is actually embedded
    — which is what lets an empty index answer a query with no model present at all.

    **Pooling, verified rather than assumed** (the caution that silently costs quality): bge-small is
    a CLS-pooling model, and `fastembed.text.onnx_embedding.OnnxTextEmbedding._post_process_onnx_output`
    takes `embeddings[:, 0]` — the CLS token — then L2-normalises. Not mean pooling. Checked in
    fastembed 0.8.0's source, and `core/test_index.py` guards it end-to-end with a retrieval
    assertion rather than by pinning vectors.

    `embed()` is used for queries as well as documents: bge-v1.5 dropped the query-instruction
    prefix its predecessor needed, and mixing prefixed queries with unprefixed documents would put
    the two in different corners of the same space.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, *, cache_dir: Path | str | None = None):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding  # heavy import, deferred to first use

            self._model = TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir))
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._load().embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def model_is_cached(model_name: str = DEFAULT_MODEL, cache_dir: Path | str | None = None) -> bool:
    """Are the weights already on disk? Lets a test that needs the real model skip instead of download."""
    roots = [Path(cache_dir)] if cache_dir else [
        DEFAULT_CACHE_DIR,
        Path(os.getenv("FASTEMBED_CACHE_PATH", Path(tempfile.gettempdir()) / "fastembed_cache")),
    ]
    stem = model_name.split("/")[-1].lower()
    return any(
        any(stem in p.name.lower() for p in root.iterdir())
        for root in roots
        if root.is_dir()
    )


# --------------------------------------------------------------------------------------------------
# The index — one deletable file, MMR retrieval
# --------------------------------------------------------------------------------------------------

INDEX_FILENAME = "index.json"


class JobIndex:
    """The scored corpus, embedded, searchable, and persisted to **one file you can delete**.

    Backed by `InMemoryVectorStore`: brute-force numpy cosine over a dict. At the corpus's real size
    (~1–5k vectors) a search is a fraction of a millisecond, so a vector database would buy latency
    nobody can perceive at the price of an operational component. Deleting `index.json` costs one
    rebuild and is the entire recovery procedure.

    Two properties the callers in 04–06 depend on:

    * **Retrieval is MMR**, not plain similarity. Three near-identical postings would otherwise come
      back as three precedents, and a score grounded in one job wearing three hats is worse than a
      score grounded in nothing — it looks corroborated.
    * **`retrieve` on an empty index returns `[]` without embedding anything**, so day one works
      before the corpus exists and before the model is downloaded.
    """

    def __init__(self, path: Path | str, *, embedder: Embeddings | None = None):
        self.path = Path(path)
        self.embeddings = embedder if embedder is not None else FastEmbedEmbeddings()
        if self.path.exists():
            try:
                self.store = InMemoryVectorStore.load(str(self.path), self.embeddings)
            except (OSError, ValueError, KeyError):
                # A half-written index is a rebuildable file, never a crash on startup.
                self.store = InMemoryVectorStore(self.embeddings)
        else:
            self.store = InMemoryVectorStore(self.embeddings)

    def __len__(self) -> int:
        return len(self.store.store)

    def add(self, docs: Iterable[Document]) -> int:
        """Embed and store `docs`, skipping any whose text is already indexed. Returns how many were new.

        This is what makes a month of runs cheap: identity is the document key, so yesterday's 1,144
        documents are recognised and skipped, and only this morning's are embedded. A document whose
        *text* changed — a record that was prefiltered and has since been scored — is re-embedded and
        replaces its old entry, so the index never keeps a stale judgment under a live key.
        """
        fresh = [d for d in docs if self.store.store.get(document_key(d), {}).get("text") != d.page_content]
        if fresh:
            self.store.add_documents(fresh, ids=[document_key(d) for d in fresh])
        return len(fresh)

    def save(self) -> Path:
        self.store.dump(str(self.path))
        return self.path

    def retrieve(
        self,
        query: str,
        k: int = 3,
        *,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
        filter: Callable[[Document], bool] | None = None,   # noqa: A002 — langchain's own name
    ) -> list[Document]:
        """The `k` most relevant *and mutually different* documents. Empty index -> `[]`, never a raise.

        `lambda_mult` is the relevance/diversity dial (1.0 = pure similarity, 0.0 = pure diversity);
        0.5 is LangChain's default and the point of using MMR at all.
        """
        if not self.store.store or not query.strip():
            return []
        return self.store.max_marginal_relevance_search(
            query, k=k, fetch_k=fetch_k, lambda_mult=lambda_mult, filter=filter,
        )


def document_key(doc: Document) -> str:
    """Stable identity for a document, so re-indexing overwrites rather than duplicates.

    A job is keyed by `company|title` — the same identity `seen.json` dedups on — so the same posting
    seen in two runs is one entry. A markdown chunk is keyed by file, heading path and part.
    """
    m = doc.metadata
    if m.get("kind") == "markdown":
        return f"md:{m.get('source', '')}#{m.get('heading_path', '')}#{m.get('part', 0)}"
    return f"job:{m.get('id') or composite_id(m.get('company', ''), m.get('title', ''))}"


def build_index(
    corpus_dir: Path | str,
    *,
    embedder: Embeddings | None = None,
    index_path: Path | str | None = None,
) -> JobIndex:
    """Open (or create) the index beside the corpus, add whatever is new, save, return it.

    Incremental by construction: this is the call the daily run makes, and on a morning that added
    one run it embeds that run only. An empty or missing corpus directory yields an empty index —
    and no download, because nothing was embedded.
    """
    corpus_dir = Path(corpus_dir)
    index = JobIndex(index_path or corpus_dir / INDEX_FILENAME, embedder=embedder)
    added = index.add(build_documents(iter_corpus_records(corpus_dir)))
    if added or not index.path.exists():
        index.save()
    return index


# --------------------------------------------------------------------------------------------------

def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


