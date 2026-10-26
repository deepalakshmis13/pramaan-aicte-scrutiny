"""Placeholder adapter for AICTE's own approval records.

No authorised integration with the live AICTE portal exists in this prototype.
The adapter therefore always reports `not_configured`; previous-approval claims
are compared only against the documents the institution submitted.
"""
from __future__ import annotations

from .base import ConnectorResult


def check_previous_approval(claim: dict) -> ConnectorResult:
    return ConnectorResult(
        status="source_unavailable",
        mode="not_configured",
        query=f"approval reference {claim.get('reference', '(none)')}",
        explanation="Planned integration: AICTE approval records are not connected in this prototype. "
                    "The previous-approval letter was checked only against other submitted documents.",
    )
