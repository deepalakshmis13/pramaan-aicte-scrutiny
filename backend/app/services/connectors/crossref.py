"""Crossref publication-metadata connector.

live      -> queries https://api.crossref.org/works/{doi}
simulated -> reads seed/fixtures/crossref_fixture.json and ALWAYS returns status
             "simulated" (never "verified"), so demo data cannot masquerade as a live check.
disabled  -> returns "source_unavailable".

A Crossref match establishes publication *metadata* only. It is never treated as
evidence of Scopus (or any other) indexing.
"""
from __future__ import annotations

import json
import time
from urllib.parse import quote

import httpx

from ...config import BASE_DIR, settings
from ...security import RateLimiter
from .base import ConnectorResult, similarity, surnames

FIXTURE = BASE_DIR / "seed" / "fixtures" / "crossref_fixture.json"
_limiter = RateLimiter()

LIMITS = (
    "Crossref confirms that a DOI is registered with the stated metadata. It does not confirm "
    "authorship by a specific faculty member at this institution, peer-review status, or indexing in Scopus/WoS."
)


def _compare(claim: dict, rec: dict) -> tuple[list, str, str]:
    title = (rec.get("title") or [""])[0]
    venue = (rec.get("container-title") or [""])[0]
    year = ""
    for key in ("published-print", "published-online", "issued", "published"):
        parts = (rec.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    fam = [(a.get("family") or "").lower() for a in rec.get("author", []) if a.get("family")]
    claimed_s = surnames(claim.get("authors", ""))
    title_sim = similarity(claim.get("title", ""), title)
    venue_sim = similarity(claim.get("venue", ""), venue) if claim.get("venue") else None
    missing_auth = [s for s in claimed_s if s not in fam]
    fields = [
        {"field": "Title", "claimed": claim.get("title", ""), "source": title, "match": title_sim >= 0.9, "detail": f"similarity {title_sim}"},
        {"field": "Year", "claimed": claim.get("year", ""), "source": year, "match": bool(year) and claim.get("year", "") == year, "detail": ""},
        {
            "field": "Authors (surnames)",
            "claimed": ", ".join(claimed_s),
            "source": ", ".join(fam),
            "match": bool(claimed_s) and not missing_auth,
            "detail": ("not in source record: " + ", ".join(missing_auth)) if missing_auth else "all claimed surnames present",
        },
    ]
    if venue_sim is not None:
        fields.append({"field": "Journal / venue", "claimed": claim.get("venue", ""), "source": venue, "match": venue_sim >= 0.8, "detail": f"similarity {venue_sim}"})
    core_fail = [f["field"] for f in fields if not f["match"] and f["field"] in ("Title", "Authors (surnames)")]
    minor_fail = [f["field"] for f in fields if not f["match"] and f["field"] not in ("Title", "Authors (surnames)")]
    if core_fail:
        return fields, "mismatch", (
            f"The DOI resolves to a Crossref record whose {' and '.join(core_fail).lower()} differ from the submitted claim."
        )
    if minor_fail:
        return fields, "manual_review", (
            f"Title and authors agree with Crossref, but {' and '.join(minor_fail).lower()} differ. Reviewer judgement required."
        )
    return fields, "verified", "Title, authors, year and venue agree with the Crossref record for this DOI (publication metadata only)."


def check_publication(claim: dict, mode: str, timeout: float | None = None, transport: httpx.BaseTransport | None = None) -> ConnectorResult:
    doi = (claim.get("doi") or "").strip()
    if not doi:
        return ConnectorResult(
            status="manual_review", mode=mode, query="(no DOI)",
            explanation="No DOI was extracted for this publication, so the metadata could not be looked up by identifier.",
        )
    url = f"https://api.crossref.org/works/{quote(doi, safe='/')}"
    if mode == "disabled":
        return ConnectorResult(status="source_unavailable", mode="disabled", query=url,
                               explanation="The Crossref connector is disabled by the administrator. No lookup was attempted.")
    if mode == "simulated":
        fixtures = json.loads(FIXTURE.read_text()) if FIXTURE.exists() else {}
        rec = fixtures.get(doi.lower())
        if not rec:
            return ConnectorResult(status="simulated", mode="simulated", query=url,
                                   explanation="SIMULATED: no demo fixture exists for this DOI. This is not a live Crossref result.")
        fields, outcome, expl = _compare(claim, rec)
        return ConnectorResult(
            status="simulated", mode="simulated", query=url, response_summary={"fixture_outcome": outcome, "title": rec.get("title")},
            fields_compared=fields, explanation=f"SIMULATED (demo fixture, not a live check). Fixture comparison outcome: {outcome}. {expl}",
            reference_url=f"https://doi.org/{doi}",
        )
    # live
    if not _limiter.check("crossref", 40, 60):
        return ConnectorResult(status="pending", mode="live", query=url, explanation="Crossref rate limit reached for this minute; check deferred.")
    headers = {"User-Agent": f"PRAMAAN-prototype/0.1 (mailto:{settings.crossref_mailto})" if settings.crossref_mailto else "PRAMAAN-prototype/0.1"}
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=timeout or settings.crossref_timeout, transport=transport, headers=headers) as c:
            r = c.get(url)
    except httpx.HTTPError as e:
        return ConnectorResult(
            status="source_unavailable", mode="live", query=url, duration_ms=int((time.monotonic() - t0) * 1000),
            explanation=f"Crossref could not be reached ({type(e).__name__}). The claim is neither confirmed nor refuted.",
        )
    ms = int((time.monotonic() - t0) * 1000)
    if r.status_code == 404:
        return ConnectorResult(
            status="manual_review", mode="live", query=url, http_status=404, duration_ms=ms,
            explanation="Crossref has no record for this DOI. Absence from Crossref does not prove the publication does not exist (it may be registered with another agency, or the DOI may be mistyped).",
        )
    if r.status_code == 429 or r.status_code >= 500:
        return ConnectorResult(status="source_unavailable", mode="live", query=url, http_status=r.status_code, duration_ms=ms,
                               explanation=f"Crossref returned HTTP {r.status_code}; the check should be retried later.")
    if r.status_code != 200:
        return ConnectorResult(status="manual_review", mode="live", query=url, http_status=r.status_code, duration_ms=ms,
                               explanation=f"Unexpected Crossref response HTTP {r.status_code}.")
    try:
        rec = r.json()["message"]
    except Exception:
        return ConnectorResult(status="manual_review", mode="live", query=url, http_status=200, duration_ms=ms,
                               explanation="Crossref response could not be parsed.")
    fields, outcome, expl = _compare(claim, rec)
    return ConnectorResult(
        status=outcome, mode="live", query=url, http_status=200, duration_ms=ms,
        response_summary={"title": (rec.get("title") or [""])[0], "publisher": rec.get("publisher", ""), "type": rec.get("type", ""),
                          "container": (rec.get("container-title") or [""])[0]},
        fields_compared=fields, explanation=expl, reference_url=f"https://doi.org/{doi}",
    )
