from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..extraction import norm_text


@dataclass
class ConnectorResult:
    status: str  # one of RESULT_STATES
    mode: str  # live | simulated | not_configured | disabled
    query: str = ""
    http_status: int | None = None
    response_summary: dict = field(default_factory=dict)
    fields_compared: list = field(default_factory=list)
    explanation: str = ""
    reference_url: str = ""
    duration_ms: int = 0


def similarity(a: str, b: str) -> float:
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 3)


def surnames(authors: str) -> list[str]:
    """'K. He, X. Zhang and S. Ren' -> ['he','zhang','ren']"""
    parts = [p.strip() for p in authors.replace(" and ", ",").replace(";", ",").split(",") if p.strip()]
    out = []
    for p in parts:
        toks = norm_text(p).split()
        if toks:
            out.append(toks[-1])
    return out
