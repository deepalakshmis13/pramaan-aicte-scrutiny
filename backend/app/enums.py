"""Allowed values for string-typed enumerations, with display labels."""

ROLES = ("reviewer", "institution", "admin")

APPLICATION_STATUSES = {
    "draft": "Draft — not yet submitted",
    "submitted": "Submitted — awaiting scrutiny",
    "under_scrutiny": "Under scrutiny",
    "notice_issued": "Deficiency notice issued",
    "response_received": "Institution response received",
    "reverification": "Reverification in progress",
    "awaiting_decision": "Awaiting official decision",
    "decided": "Decision recorded",
}

# Verification result states (spec §9)
RESULT_STATES = {
    "verified": "Verified",
    "mismatch": "Mismatch Detected",
    "expired": "Expired",
    "missing": "Missing",
    "pending": "Pending",
    "source_unavailable": "Source Unavailable",
    "inconclusive": "Inconclusive",
    "manual_review": "Manual Review Required",
    "resolved": "Resolved",
    "escalated": "Escalated",
    "simulated": "Simulated (demo fixture)",
    "rejected": "Rejected by officer",
}

FINDING_CATEGORIES = {
    "completeness": "Completeness",
    "validity": "Validity & expiry",
    "extraction": "Extraction quality",
    "cross_document": "Cross-document consistency",
    "external": "External source verification",
    "duplicate": "Duplicates",
    "anomaly": "Anomaly indicators",
    "compliance": "Regulatory compliance",
    "infrastructure": "Infrastructure evidence",
    "manual": "Reviewer observation",
}

SEVERITIES = ("high", "medium", "low")

DOCUMENT_TYPES = {
    "registration_certificate": "Society / Trust registration certificate",
    "affidavit": "Affidavit / undertaking",
    "accreditation_certificate": "Accreditation certificate",
    "noc": "No Objection Certificate",
    "faculty_list": "Faculty list",
    "qualification_certificate": "Faculty qualification certificate",
    "publication_list": "Research publication list",
    "previous_approval": "Previous approval (EoA) letter",
    "intake_details": "Programme & intake details",
    "infrastructure_photo": "Infrastructure photograph",
    "floor_plan": "Floor plan",
    "fire_safety_certificate": "Fire safety certificate",
    "fee_receipt": "Fee / transaction receipt",
    "other": "Other document",
}

NOTICE_STATUSES = {
    "draft": "Draft",
    "issued": "Sent — awaiting response",
    "responded": "Response received",
    "closed": "Closed — all items reviewed",
    "withdrawn": "Withdrawn",
}

DECISION_OUTCOMES = {
    "approved": "Approved",
    "approved_with_conditions": "Approved with conditions",
    "deferred_for_inspection": "Deferred — physical inspection required",
    "returned_for_clarification": "Returned for further clarification",
    "rejected": "Not approved",
}

ALLOWED_UPLOAD_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
