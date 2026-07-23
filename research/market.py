"""The market-report command — `python -m research.market`.

**Separate from the daily run, deliberately.** The triage pipeline runs every weekday morning; this
runs monthly, or whenever a negotiation is coming. Folding it in would put ~11 seconds of clustering
and (with the external half) a network round trip into every morning for a document nobody reads
daily. Different cadence, different command.

    python -m research.market                 the whole report: your corpus + the keyless baselines
    python -m research.market --offline       first-party only — no network at all, no key, no ToS
    python -m research.market --supply        also pull the third-party job feeds (minutes, not seconds)
    python -m research.market --print         the markdown to stdout as well, for piping

Two files come out of every run, both under `data/reports/`:

  * `market-numbers-<date>.json` — the **machine-owned** numbers, dated and accumulating. This is what
    a later run's trend section reads, and it is the file a narrative cites.
  * `market-report-<date>.md` — the rendered document for a human.

**Nothing here writes prose.** `profile/notes/market-insights.md` (or a stranger's equivalent) is
human/agent-authored judgment and this command never touches it — see `docs/operating/market-report.md`
for the citing convention that keeps the two joined. The ~90% of that document which is mechanically
derivable is what goes stale; the remaining 10% is the reason it exists, and an LLM-written "what this
means" section is precisely where a confidently wrong rate claim would damage a negotiation.

**The first-party half runs with no network at all.** `--offline` (or `report.external: false` in
`config/settings.yaml`) never touches `research/sources/`, and the report says the external half is
missing rather than quietly shrinking — that refusal lives in `research/report.py`.

Markdown goes to stdout only with `--print`; status lines always go to stderr, so the two file paths
are readable even when the document is being piped.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from datetime import date
from pathlib import Path

from core.index import iter_corpus_records
from core.settings import PROFILE_DIR, settings

from . import retrospective, snapshots
from .report import Baseline, build_report, render

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "corpus"
REPORTS_DIR = snapshots.REPORTS_DIR
RUBRIC_PATH = PROFILE_DIR / "rubric.md"

# The rendered document, beside the numbers it was rendered from. Same dating rule as the numbers
# file: one per date, so a month of running this leaves a month of documents rather than one that has
# been overwritten.
REPORT_PREFIX = "market-report-"


def _report_settings() -> dict:
    """The `report:` block of `config/settings.yaml`, validated on load like everything else there."""
    return settings().get("report", {}) or {}


def _bls_areas(configured: dict[str, str] | None) -> dict[str, tuple[str, str]] | None:
    """`{"National": "N0000000"}` -> what `bls.fetch_bands` wants, or `None` for its own default.

    The split into (kind, code) happens here rather than in the settings file because a user should
    write the area code they can look up in one piece, not two. The shape is validated by the schema
    (`core/settings.py:BLSArea`); a wrong-but-well-formed code is BLS's problem and comes back as a
    band that is simply absent.
    """
    if not configured:
        return None
    return {name: (code[0], code[1:]) for name, code in configured.items()}


def collect_baseline(*, supply: bool, bls_areas: dict[str, str] | None = None) -> Baseline:
    """The external half. Network, but no key: both rate baselines are keyless by design.

    Never raises — `fetch_baselines` and `fetch_all` each wrap their sources, so the worst case is a
    `Baseline` whose counts are all zero, which the renderer prints as a named gap listing the sources
    that answered with nothing. That is the difference between "the report is shorter today" and "CALC+
    has moved again", and only the second one is true.
    """
    from . import sources          # imported here: `--offline` must not even load thirteen scrapers

    bands, band_counts = sources.fetch_baselines(options={"bls": {"areas": _bls_areas(bls_areas)}})
    supply_counts: dict[str, int] = {}
    if supply:
        _, supply_counts = sources.fetch_all()
    return Baseline(bands=bands, band_counts=band_counts, supply_counts=supply_counts)


def rubric_fingerprint(path: Path = RUBRIC_PATH) -> str:
    """The stamp that decides which snapshots are comparable with each other.

    A missing rubric fingerprints as empty, and `snapshots.trend` treats an unknown rubric as
    incomparable with everything including another unknown — pairing two blanks is a guess that they
    match, and the gate exists to refuse that guess.
    """
    try:
        return snapshots.fingerprint(path.read_text(encoding="utf-8"))
    except OSError:
        log.warning("no rubric at %s — this snapshot cannot be compared with any other", path)
        return ""


def run(*, corpus_dir: Path, reports_dir: Path, as_of: str, baseline: Baseline | None,
        top_terms: int, top_employers: int, rubric: str, embedder=None) -> tuple[str, Path, Path]:
    """Corpus + whatever the external pull returned -> the markdown, the numbers file, the document.

    The ordering is the one decision in here. Today's snapshot is **written before the history is
    read back**, so the trend section's newest point is the same run the reader is looking at rather
    than the previous one — a table ending a month before Part 1 does would read as a bug. The cost is
    that `build_report` is called with no history and its trend replaced; the alternative is a seam
    that both computes the retrospective and accepts a value derived from it.
    """
    report = build_report(iter_corpus_records(corpus_dir), baseline, as_of=as_of, embedder=embedder,
                          top_terms=top_terms, top_employers=top_employers)

    snap = snapshots.snapshot(report.retrospective, as_of=as_of, rubric=rubric)
    numbers_path = snapshots.write(snap, reports_dir)

    report = dataclasses.replace(report, trend=snapshots.trend(snapshots.load(reports_dir)))
    markdown = render(report)

    reports_dir.mkdir(parents=True, exist_ok=True)
    document_path = reports_dir / f"{REPORT_PREFIX}{as_of}.md"
    document_path.write_text(markdown, encoding="utf-8")
    return markdown, numbers_path, document_path


def main(argv: list[str] | None = None) -> int:
    cfg = _report_settings()
    parser = argparse.ArgumentParser(
        prog="python -m research.market",
        description="The market report: a retrospective over your own scored corpus, plus a keyless "
                    "external baseline. Monthly, on demand — this is not part of the daily run.")
    parser.add_argument("--offline", action="store_true",
                        help="first-party only: no network at all. The external half renders as a "
                             "labelled gap, never as a shorter report.")
    parser.add_argument("--supply", action="store_true",
                        help="also pull the third-party job feeds for per-source counts. Minutes, "
                             "not seconds.")
    parser.add_argument("--as-of", default=date.today().isoformat(), metavar="YYYY-MM-DD",
                        help="the date this report is stamped and filed under (default: today)")
    parser.add_argument("--corpus-dir", type=Path, default=CORPUS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--top-terms", type=int, default=None,
                        help=f"clustered ideas per free-text section (default "
                             f"{cfg.get('top_terms', retrospective.TOP_TERMS)})")
    parser.add_argument("--top-employers", type=int, default=None,
                        help=f"employers per table (default "
                             f"{cfg.get('top_employers', retrospective.TOP_EMPLOYERS)})")
    parser.add_argument("--print", dest="to_stdout", action="store_true",
                        help="write the markdown to stdout as well as to data/reports/")
    args = parser.parse_args(argv)

    # A flag can only ever turn the network *off* against a config that wants it on, or *on* against a
    # config that is silent — the settings file is the standing choice and the flags are this run's.
    external = bool(cfg.get("external", True)) and not args.offline
    supply = args.supply or bool(cfg.get("supply", False))

    baseline: Baseline | None = None
    if external:
        print("· collecting the external baseline (keyless — GSA CALC+, BLS OEWS)"
              + (" and the third-party job feeds" if supply else ""), file=sys.stderr)
        baseline = collect_baseline(supply=supply, bls_areas=cfg.get("bls_areas"))
    else:
        print("· first-party only: no network. The external half will render as a labelled gap.",
              file=sys.stderr)

    markdown, numbers_path, document_path = run(
        corpus_dir=args.corpus_dir, reports_dir=args.reports_dir, as_of=args.as_of,
        baseline=baseline, rubric=rubric_fingerprint(),
        top_terms=args.top_terms if args.top_terms is not None
        else int(cfg.get("top_terms", retrospective.TOP_TERMS)),
        top_employers=args.top_employers if args.top_employers is not None
        else int(cfg.get("top_employers", retrospective.TOP_EMPLOYERS)))

    print(f"· numbers  {numbers_path}", file=sys.stderr)
    print(f"· report   {document_path}", file=sys.stderr)
    print("· the numbers file is what a narrative cites — see docs/operating/market-report.md. "
          "Nothing here rewrites your own market notes.", file=sys.stderr)
    if args.to_stdout:
        print(markdown)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    raise SystemExit(main())
