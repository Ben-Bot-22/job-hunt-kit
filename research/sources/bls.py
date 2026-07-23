"""BLS OEWS — the permanent-salary anchor. No key, no account, and available per metro area.

CALC+ says what the government will pay a *contractor* per hour; this says what employers actually pay
*employees*, which is the number a permanent offer has to be judged against. It is the Occupational
Employment and Wage Statistics survey, published by the Bureau of Labor Statistics and served by the
public v1 API — no registration, no key, 25 queries a day per IP.

**Per-MSA is the point.** The same occupation is a different number in a different metro, and "is this
salary good for where I live" is not answerable from a national mean. Verified live on 2026-07-22 for
SOC 15-1252 (Software Developers), 2025 annual: national mean **$148,100** and median **$135,980**
against Dallas–Fort Worth's **$138,810** and **$133,290** — a 6.3% gap on the mean that a national-only
baseline would have hidden entirely.

**These are wages and are labelled as such** — the opposite of CALC+'s ceiling bill rate, and the
reason both sources exist. The caveat that ships with each band is still mandatory, because an OEWS
figure has real limits of its own: it is a *survey of employees*, so it excludes independent
contractors, it is May-of-last-year data rather than today's, and it is an occupation-wide figure that
knows nothing about a stack or a seniority band.

**Quota is respected by construction, not by counting.** Series are batched — one request carries up to
25 of them, and the default ask (one occupation, national plus one metro, eight measures) is 16 series
in a single call. `MAX_QUERIES` caps a run at two requests, i.e. 8% of the daily allowance, so nothing
here can exhaust the quota for whatever else the machine does. A refusal is detected on the payload's
own `status` field rather than on an HTTP code — BLS answers a threshold breach with HTTP 200 and
`REQUEST_NOT_PROCESSED` — and degrades to no bands with a log line.
"""
from __future__ import annotations

import logging

import requests

from ._baseline import RateBand

log = logging.getLogger(__name__)

API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
TIMEOUT = 180         # measured: BLS took over 60 s to answer a 7-series request and timed out at 60
MAX_SERIES = 25       # the v1 API's own per-request limit
MAX_QUERIES = 2       # of a 25/day allowance — a hard stop, not a budget to spend

# SOC 15-1252, Software Developers. One occupation by default: it is the one the whole report is about,
# and every extra one multiplies the series count against the 25-per-request limit.
OCCUPATIONS: dict[str, str] = {"Software Developers": "151252"}

# OEWS area codes. `N` + all-zeroes is the nation; `M` + a 7-digit CBSA code is a metro. The code
# default is national-only — this is a remote-first tool, so a stranger who names no `bls_areas` gets
# the national figure rather than one owner's metro. A metro is added by passing `bls_areas` in
# config/settings.yaml (the example anchors on Chicago); the name is what prints, so it is the BLS
# area name. Metro CBSA codes for reference: Dallas-Fort Worth-Arlington, TX = M0019100.
AREAS: dict[str, tuple[str, str]] = {
    "National": ("N", "0000000"),
}

# OEWS data-type codes, all verified live 2026-07-22. Hourly carries the full spread; annual carries
# mean and median only, because adding the four annual percentiles would push the default ask past the
# 25-series limit into a second request to restate numbers that are the hourly ones times 2,080.
_HOURLY = {"mean": "03", "p10": "06", "p25": "07", "median": "08", "p75": "09", "p90": "10"}
_ANNUAL = {"mean": "04", "median": "13"}

CAVEAT = ("BLS OEWS is a survey of EMPLOYEE wages: it excludes independent contractors and the "
          "self-employed, it is an occupation-wide figure that knows nothing about a specific stack or "
          "seniority band, and it reflects the survey year rather than today's market.")

ATTRIBUTION = ("Source: US Bureau of Labor Statistics, Occupational Employment and Wage Statistics "
               "(OEWS), api.bls.gov — US Government public-domain data.")


def fetch_bands(occupations: dict[str, str] | None = None,
                areas: dict[str, tuple[str, str]] | None = None) -> list[RateBand]:
    """One hourly and one annual `RateBand` per (occupation, area). Never raises.

    An unreachable API, a timeout or a spent daily quota all come back as fewer bands and a log line —
    the external half of the report degrades to a labelled gap, never to a shorter report that reads
    as complete.
    """
    occupations = occupations or OCCUPATIONS
    areas = areas or AREAS

    wanted: dict[str, tuple[str, str, str, str]] = {}   # series id -> (occupation, area, unit, measure)
    for occ_name, soc in occupations.items():
        for area_name, (kind, code) in areas.items():
            for unit, measures in (("hour", _HOURLY), ("year", _ANNUAL)):
                for measure, dt in measures.items():
                    wanted[f"OEU{kind}{code}000000{soc}{dt}"] = (occ_name, area_name, unit, measure)

    values = _values(list(wanted))
    if values is None:
        return []

    bands: list[RateBand] = []
    for occ_name in occupations:
        for area_name in areas:
            for unit in ("hour", "year"):
                got = {m: values[sid] for sid, (o, a, u, m) in wanted.items()
                       if o == occ_name and a == area_name and u == unit and sid in values}
                if not got:
                    continue
                bands.append(RateBand(
                    source="bls",
                    occupation=occ_name,
                    scope=area_name,
                    unit=unit,
                    n=0,   # OEWS publishes a distribution, not the sample behind it
                    period=_period(values, wanted, occ_name, area_name, unit),
                    caveat=CAVEAT,
                    attribution=ATTRIBUTION,
                    is_ceiling=False,
                    query={"occupation": occ_name, "soc": occupations[occ_name], "area": area_name},
                    **{k: got.get(k) for k in ("median", "mean", "p10", "p25", "p75", "p90")},
                ))
    return bands


def _period(values, wanted, occ_name, area_name, unit) -> str:
    years = {values.get(sid + "@year", "") for sid, (o, a, u, _m) in wanted.items()
             if o == occ_name and a == area_name and u == unit}
    year = next((y for y in sorted(years, reverse=True) if y), "")
    return f"OEWS {year} annual estimates" if year else "OEWS, year unknown"


def _values(series_ids: list[str]) -> dict | None:
    """`{series id: latest value}` plus `{id}@year` markers, or `None` when BLS could not be read.

    `None` and `{}` differ: the first is a gap the report must declare, the second is BLS answering
    that it has nothing for those series — which for an obscure SOC/metro pair is a real answer.
    """
    out: dict = {}
    batches = [series_ids[i:i + MAX_SERIES] for i in range(0, len(series_ids), MAX_SERIES)]
    if len(batches) > MAX_QUERIES:
        # Never silently. A caller that asked for more than two requests' worth gets the first two and
        # is told, rather than getting a baseline that is quietly missing half its metros.
        log.warning("bls: %d series is %d requests; capping at %d and dropping the rest",
                    len(series_ids), len(batches), MAX_QUERIES)
        batches = batches[:MAX_QUERIES]

    reached = False
    for batch in batches:
        try:
            r = requests.post(API, json={"seriesid": batch},
                              headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:  # noqa: BLE001 — the external half degrades, it does not raise
            log.warning("bls: request failed: %s", e)
            continue
        # A spent daily quota is an HTTP 200 carrying REQUEST_NOT_PROCESSED, so the status code says
        # nothing. Checking the payload is the only way to tell a refusal from an empty answer.
        if payload.get("status") != "REQUEST_SUCCEEDED":
            log.warning("bls: %s — %s", payload.get("status"), "; ".join(payload.get("message") or []))
            continue
        reached = True
        out.update(_read(payload))
    return out if reached else None


def _read(payload: dict) -> dict:
    out: dict = {}
    for series in (payload.get("Results") or {}).get("series", []):
        data = series.get("data") or []
        if not data:
            continue
        latest = data[0]
        try:
            out[series["seriesID"]] = float(str(latest["value"]).replace(",", ""))
        except (KeyError, TypeError, ValueError):
            continue
        out[series["seriesID"] + "@year"] = str(latest.get("year") or "")
    return out
