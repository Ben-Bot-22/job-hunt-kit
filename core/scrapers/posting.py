"""One way to turn a source's fields into the shared `core.models.Job`.

The frozen pipeline carried its own `Job` — a flat row with `metro`, `cadence`, `rate`, `agency`,
`core_stack`, `seniority_yrs` — because it was shaped for a spreadsheet column order. That model is
deleted: `core/models.py` is the one `Job`, and it is shaped for the thing this repo actually does,
which is put job *text* in front of a model.

So the market facts a source knows structurally are folded into the JD text as a short header rather
than becoming new fields on the shared carrier. Three reasons, in order of weight:

1. **The rate already works this way.** `core/rates.py` reads a posted rate out of free text, because
   stage 5's sourcing research concluded the honest source of a contract rate is the string in the job
   description and not a source's `salary_min` (which, for Adzuna, is a model's point estimate).
   A `rate` field would be a second, less trustworthy answer to a question already answered.
2. **The scrapers already did it.** Motion, Mondo, Apex and TEKsystems have always prefixed
   `"Employment type: …"` onto the description; this makes that one function instead of six copies.
3. Adding `metro`/`cadence` to `core.models.Job` would put three fields on the shared carrier that
   exactly one leaf writes and that triage's analyzer infers for itself into `Analysis`. If a later
   ticket genuinely needs them structured, it should add them deliberately — not inherit them because
   a 2026-06 spreadsheet had those columns.

The header is stable and machine-readable on purpose (`Key: value.` sentences, in a fixed order), so
an aggregation can recover employment type or cadence with a regex if it has to.

**Attribution is the last header field, and it rides in the text for the same reason `RateBand`
validates its own.** Himalayas, Remotive and Adzuna all require to be named wherever their data
appears — a terms-of-use obligation, not a courtesy. An obligation that lives in a render template is
one a later template edit silently deletes; an obligation carried on every record is one the renderer
would have to strip on purpose. `research/sources/__init__.py` drops any job from an
attribution-bearing source that arrives without it, so "cannot omit" is behaviour rather than advice.
"""
from __future__ import annotations

import html as _html
import re

from core.models import Job

_HEADER_ORDER = ("Employment type", "Location", "Cadence", "Posted rate", "Tech", "Attribution")

_TAGS = re.compile(r"<[^>]+>")


def strip_html(s: str, limit: int = 6000) -> str:
    """A rendered description as plain text — what the JSON feeds hand back instead of prose.

    Same treatment `_jsonld.description` has always given a schema.org description, hoisted here so
    the two paths cannot drift into two different ideas of what a job description is. The limit
    exists because Remotive descriptions run to 25,000 characters of benefits boilerplate.
    """
    return _html.unescape(_TAGS.sub(" ", s or "")).strip()[:limit]


def posting(*, title: str, company: str, link: str, source: str,
            description: str = "", employment_type: str = "", metro: str = "",
            cadence: str = "", rate: str = "", tech: str = "", posted: str = "",
            attribution: str = "") -> Job:
    """A `core.models.Job` from what a market source knows. Blank facts are simply left out.

    `jd_source` follows the text: a source that returned a description gives a `full` JD, and one that
    returned only a listing row gives `title_only`. Getting that backwards would let the retrospective
    count a title as a job description it had read.
    """
    facts = dict(zip(_HEADER_ORDER,
                     (employment_type, metro, cadence, rate, tech, attribution)))
    header = " ".join(f"{k}: {v.strip()}." for k, v in facts.items() if v and v.strip())
    text = f"{header} {description.strip()}".strip() if description.strip() else header

    return Job(
        link=link,
        company=company.strip(),
        title=title.strip(),
        source_platform=source,
        posted_hint=posted,
        fetched_jd=text,
        jd_source="full" if description.strip() else "title_only",
    )
