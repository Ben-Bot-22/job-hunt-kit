"""What `to_pdf` must never do: return a PDF it did not just write.

`soffice --headless --convert-to pdf` exits **0 and writes nothing** when another headless
LibreOffice instance already holds the profile lock. That is not an edge case — it is the
normal state of a `/tailor-cv-batch` run, where one agent per job renders concurrently.

The original guard was `if not pdf.exists()`, which the previous render satisfies. So the
failure was silent and it was worse than a crash: `cv/review_cv.py` graded the stale file
and returned scores for text that had been deleted. Two agents caught it independently on
2026-07-30, one against a PDF 46 seconds older than its own docx; neither could have been
sure how many earlier passes had been scored the same way.

The fix is to unlink the target before converting, so a no-op conversion leaves nothing to
mistake for a result. These tests pin the behaviour rather than the implementation: after a
conversion that writes nothing, `to_pdf` must raise **and** the stale file must be gone.

No LibreOffice needed — `subprocess.run` and the binary lookup are both stubbed, so this
runs anywhere, including a stranger's clone with no `profile/`.

The fixture filename is deliberately generic rather than the real output name: this file is
tracked and ships, so `scripts/test_leaks.py` forbids the owner's name in it. The first
version of this test used the real filename and went red the moment it was committed —
untracked files are not scanned, so the guard only fires once the file is staged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


RULE = "A PDF render that wrote nothing fails loudly instead of returning the previous one."

_SPEC = importlib.util.spec_from_file_location(
    "render_cv", Path(__file__).resolve().parent / "scripts" / "render_cv.py"
)


def _render_module():
    if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import plumbing
        pytest.skip("render_cv.py not importable")
    mod = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(mod)
    return mod


@pytest.fixture
def render(monkeypatch):
    mod = _render_module()
    monkeypatch.setattr(mod, "_find_soffice", lambda: "/fake/soffice")
    return mod


def _docx(tmp_path: Path) -> Path:
    docx = tmp_path / "tailored_cv.docx"
    docx.write_bytes(b"docx bytes")
    return docx


def test_silent_noop_conversion_raises_instead_of_returning_the_stale_pdf(render, monkeypatch, tmp_path):
    """The exact production failure: soffice exits 0, writes nothing, a previous PDF is present."""
    docx = _docx(tmp_path)
    stale = tmp_path / "tailored_cv.pdf"
    stale.write_bytes(b"the previous render, whose text has since been deleted")

    monkeypatch.setattr(render.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(RuntimeError) as excinfo:
        render.to_pdf(docx)

    assert not stale.exists(), "the stale PDF must be removed, never left to be graded as current"
    assert "wrote nothing" in str(excinfo.value)


def test_a_real_conversion_still_returns_the_pdf(render, monkeypatch, tmp_path):
    """The happy path is unchanged — unlinking first must not break a working render."""
    docx = _docx(tmp_path)
    pdf = tmp_path / "tailored_cv.pdf"
    pdf.write_bytes(b"an earlier render")

    def _convert(*_a, **_k):
        pdf.write_bytes(b"%PDF-1.7 freshly written")

    monkeypatch.setattr(render.subprocess, "run", _convert)

    assert render.to_pdf(docx) == pdf
    assert pdf.read_bytes().startswith(b"%PDF")


def test_no_previous_pdf_is_not_an_error(render, monkeypatch, tmp_path):
    """First render of a new application folder: there is nothing to unlink."""
    docx = _docx(tmp_path)
    pdf = tmp_path / "tailored_cv.pdf"

    monkeypatch.setattr(render.subprocess, "run", lambda *a, **k: pdf.write_bytes(b"%PDF-1.7"))

    assert render.to_pdf(docx) == pdf


def test_missing_libreoffice_still_reports_itself(render, monkeypatch, tmp_path):
    """The other failure mode keeps its own message — this fix must not swallow it."""
    monkeypatch.setattr(render, "_find_soffice", lambda: None)

    with pytest.raises(RuntimeError, match="LibreOffice"):
        render.to_pdf(_docx(tmp_path))
