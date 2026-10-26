"""Scopus indexing connector (Elsevier Scopus Search API).

Requires an institutional SCOPUS_API_KEY (and usually an insttoken or on-campus IP).
Without credentials the connector reports `source_unavailable` / not_configured and
the indexing claim is routed to manual review — it is never marked verified.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

from ...config import settings
from .base import ConnectorResult

API = "https://api.elsevier.com/content/search/scopus"


def check_indexing(claim: dict, mode: str, transport: httpx.BaseTransport | None = None) -> ConnectorResult:
    doi = (claim.get("doi") or "").strip()
    query = f"DOI({doi})" if doi else f'TITLE("{claim.get("title", "")}")'
    if mode == "disabled":
        return ConnectorResult(status="source_unavailable", mode="disabled", query=query,
                               explanation="Scopus connector disabled by administrator. Indexing claim requires manual verification.")
    if not settings.scopus_api_key:
        return ConnectorResult(
            status="source_unavailable", mode="not_configured", query=query,
            explanation="Scopus indexing could not be checked: no authorised Scopus API credentials are configured. "
                        "A Crossref metadata match is not evidence of Scopus indexing.",
        )
    headers = {"X-ELS-APIKey": settings.scopus_api_key, "Accept": "application/json"}
    if settings.scopus_insttoken:
        headers["X-ELS-Insttoken"] = settings.scopus_insttoken
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=settings.crossref_timeout, transport=transport, headers=headers) as c:
            r = c.get(API, params={"query": query, "field": "dc:title,prism:doi,prism:publicationName,eid"})
    except httpx.HTTPError as e:
        return ConnectorResult(status="source_unavailable", mode="live", query=query,
                               explanation=f"Scopus API unreachable ({type(e).__name__}).")
    ms = int((time.monotonic() - t0) * 1000)
    if r.status_code in (401, 403):
        return ConnectorResult(status="source_unavailable", mode="live", query=query, http_status=r.status_code, duration_ms=ms,
                               explanation="Scopus API rejected the credentials or entitlement for this request.")
    if r.status_code != 200:
        return ConnectorResult(status="source_unavailable", mode="live", query=query, http_status=r.status_code, duration_ms=ms,
                               explanation=f"Scopus API returned HTTP {r.status_code}.")
    data = r.json().get("search-results", {})
    total = int(data.get("opensearch:totalResults", "0") or 0)
    if total >= 1:
        e = data.get("entry", [{}])[0]
        return ConnectorResult(
            status="verified", mode="live", query=query, http_status=200, duration_ms=ms,
            response_summary={"eid": e.get("eid"), "title": e.get("dc:title"), "source": e.get("prism:publicationName")},
            fields_compared=[{"field": "DOI", "claimed": doi, "source": e.get("prism:doi", ""), "match": (e.get("prism:doi", "") or "").lower() == doi.lower(), "detail": ""}],
            explanation="A Scopus record was returned for this identifier.",
            reference_url=f"https://www.scopus.com/record/display.uri?eid={quote(e.get('eid', ''))}",
        )
    return ConnectorResult(
        status="manual_review", mode="live", query=query, http_status=200, duration_ms=ms,
        explanation="Scopus returned no record for this identifier. This may indicate the item is not indexed, or that the identifier differs; request the institution's evidence.",
    )
