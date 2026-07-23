"""Tests for `Job.id` and the link canonicalizer behind its fallback.

Run:  .venv/bin/python -m pytest core/ -q

The two failure directions here are **not symmetric**, and the whole design is scoped around that.

*Widening* the identity — letting the fallback fire for a job that has a company or a title — changes
the key of jobs already recorded, and nothing errors. `seen.json` (1,071 keys) and `applied.json`
(33 rows) simply stop matching, and the next morning's run re-surfaces a month of jobs Ben already
rejected or already applied to. There is no repair short of re-scoring the corpus. That is what the
pinned-corpus tests below exist to catch, and why the fallback is gated on the composite being
*entirely* empty rather than on "no company" or "no link".

*Narrowing* it — two spellings of one URL producing two ids — costs a duplicate in a worklist. That
is visible and cheap, which is why `link_identity` drops tracking params by name instead of dropping
the whole query string: on plenty of ATSs the query *is* the posting (`viewjob?jk=`, `?gh_jid=`), and
collapsing two real jobs into one id is the silent-collision bug this ticket is fixing, not a fix.

The pins are real strings copied out of `data/corpus/` on the 2026-07-20 run. `data/` is gitignored,
so the literals are the test; the whole-corpus sweep runs as well when a checkout happens to have the
corpus, and skips cleanly when it doesn't — the `model_is_cached` pattern from `test_retrieval.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from .models import Job, composite_id, link_identity, normalize_link

CORPUS = Path(__file__).resolve().parent.parent / "data" / "corpus"

# (company, title, link, id) — copied verbatim from data/corpus/state-2026-07-20-094851.json and
# verified present in seen.json. Every one of these must survive the fallback untouched.
PINNED = [
    ("Genesis10", "Senior Full Stack Developer - Remote",
     "https://remotevibecodingjobs.com/jobs/genesis10-senior-full-stack-developer-remote-49206afa",
     "genesis10|senior full stack developer remote|"),
    # No link at all — identity has always been the composite, and a fallback that fired on a missing
    # link rather than a missing composite would send this one to "".
    ("The College Board", "Senior Full Stack Engineer", "",
     "the college board|senior full stack engineer|"),
    ("VortexLink", "Senior Agentic AI Full Stack Developer-Boston, MA(contract -100% remote considered)",
     "https://www.dice.com/job-detail/e3267a40-c2d3-42d0-b767-f60d4a0acc7c",
     "vortexlink|senior agentic ai full stack developer boston ma contract 100 remote considered|"),
    ("Hashorn", "Senior Backend Engineer (Node.js / TypeScript)",
     "https://www.linkedin.com/jobs/view/4438953214",
     "hashorn|senior backend engineer node js typescript|"),
    ("NTT DATA North America", "React Developer",
     "https://www.linkedin.com/jobs/view/4439754333", "ntt data north america|react developer|"),
]


@pytest.mark.parametrize("company,title,link,expected", PINNED)
def test_identity_is_byte_identical_for_jobs_with_company_and_title(company, title, link, expected):
    assert Job(link=link, company=company, title=title).id == expected


def test_a_title_alone_still_keys_off_the_composite():
    """`applied.json` carries agency rows with no hiring company — `|software engineer iii|`. The
    composite isn't *empty*, so the fallback must not fire and steal the row's key."""
    assert Job(link="https://example.com/x", title="Software Engineer III").id == "|software engineer iii|"
    assert Job(link="https://example.com/y", company="DiversifyFund").id == "diversifyfund||"


def test_empty_composite_falls_back_to_the_link():
    """The defect: a pasted URL has neither company nor title, so every such job used to be `"||"`."""
    job = Job(link="https://boards.greenhouse.io/acme/jobs/4012345")
    assert job.id == "https://boards.greenhouse.io/acme/jobs/4012345"
    assert job.id != composite_id("", "")


def test_two_pasted_urls_get_two_identities():
    a = Job(link="https://boards.greenhouse.io/acme/jobs/4012345")
    b = Job(link="https://boards.greenhouse.io/acme/jobs/4012346")
    assert a.id != b.id


def test_a_job_with_neither_composite_nor_link_is_still_the_old_empty_key():
    """Nothing to key on at all: keep `"||"` rather than inventing something. It collides, but it
    collides the way it always has, and the caller has no identity to give it."""
    assert Job(link="").id == "||"


@pytest.mark.parametrize("variant", [
    "https://boards.greenhouse.io/acme/jobs/4012345",
    "https://boards.greenhouse.io/acme/jobs/4012345/",
    "https://www.boards.greenhouse.io/acme/jobs/4012345",
    "HTTPS://Boards.Greenhouse.IO/acme/jobs/4012345",
    "https://boards.greenhouse.io/acme/jobs/4012345#app",
    "https://boards.greenhouse.io/acme/jobs/4012345?gh_src=newsletter",
    "https://boards.greenhouse.io/acme/jobs/4012345?utm_campaign=x&utm_source=y",
    "  https://boards.greenhouse.io/acme/jobs/4012345?ref=twitter  ",
])
def test_normalization_collapses_equivalent_url_forms(variant):
    """Otherwise the fallback manufactures duplicates instead of preventing them: the same posting
    forwarded, shared and pasted would be three jobs."""
    assert link_identity(variant) == "https://boards.greenhouse.io/acme/jobs/4012345"


def test_normalization_keeps_a_query_that_is_the_posting():
    """The worse direction. `jk=` and `gh_jid=` identify the job; dropping the query wholesale would
    collapse every Indeed posting onto `https://indeed.com/viewjob`."""
    assert link_identity("https://www.indeed.com/viewjob?jk=aaa111") != \
        link_identity("https://www.indeed.com/viewjob?jk=bbb222")
    assert link_identity("https://job-boards.eu.lever.co/acme?gh_jid=99") != \
        link_identity("https://job-boards.eu.lever.co/acme?gh_jid=98")


def test_param_order_does_not_fork_an_identity():
    assert link_identity("https://x.co/j?a=1&b=2") == link_identity("https://x.co/j?b=2&a=1")


def test_link_identity_reuses_the_platform_rewrites():
    """LinkedIn's tracking URL and the clean one are the same posting — `normalize_link` already knew
    that, and the fallback must not be a second, weaker normalizer."""
    tracked = ("https://www.linkedin.com/comm/jobs/view/senior-backend-engineer-4438953214"
               "?trk=eml-jobs_jymbii_digest-header-0-jobcard&midToken=AQE")
    assert normalize_link(tracked) == "https://www.linkedin.com/jobs/view/4438953214"
    # `link_identity` then strips `www.`, so the id is the host-canonical form of that same URL.
    assert link_identity(tracked) == "https://linkedin.com/jobs/view/4438953214"
    assert link_identity(tracked) == link_identity("https://www.linkedin.com/jobs/view/4438953214")


# --- the whole-corpus sweep (skipped when data/ isn't present) ---------------------------------------

def _load(name: str):
    path = CORPUS / name
    if not path.exists():
        pytest.skip(f"{path} not present — data/ is gitignored")
    return json.loads(path.read_text())


def test_every_id_in_the_live_state_file_is_still_a_key_in_seen():
    """The acceptance check, run against the real caches: 358 jobs from the 2026-07-20 run, every one
    of their recomputed ids already a key in the 1,071-key seen cache. One miss is one decision Ben
    made that the tool would forget."""
    seen = set(_load("seen.json"))
    jobs = _load("state-2026-07-20-094851.json")["jobs"]
    missing = [j for j in jobs
               if Job(link=j.get("link", ""), company=j.get("company", ""),
                      title=j.get("title", "")).id not in seen]
    assert not missing, f"{len(missing)}/{len(jobs)} ids no longer match seen.json"


def test_no_live_cache_key_was_being_produced_by_the_empty_composite():
    """`"||"` appearing in seen or applied would mean a real decision is stored under the colliding
    key and the fallback is about to change what that key means."""
    seen = set(_load("seen.json"))
    applied = _load("applied.json")
    assert "||" not in seen
    assert [r for r in applied if r.get("composite_key")] and \
        not [r for r in applied if not r.get("composite_key", "").strip("|")]


def test_the_corpus_links_do_not_collide_under_canonicalization():
    """Real links, not synthetic ones: if the canonicalizer is too aggressive it shows up here as two
    distinct postings sharing an identity."""
    jobs = _load("state-2026-07-20-094851.json")["jobs"]
    links = {j["link"] for j in jobs if j.get("link")}
    ids = {link_identity(link) for link in links}
    assert len(ids) == len(links), f"{len(links) - len(ids)} distinct corpus links collapsed"
