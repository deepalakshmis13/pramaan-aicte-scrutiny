"""Keyword-based document classification. Deliberately simple and explainable:
the basis records exactly which phrases matched for each candidate type."""
from __future__ import annotations

from .extraction import norm_text

KEYWORDS: dict[str, list[str]] = {
    "registration_certificate": ["certificate of registration", "registrar of societies", "societies registration act", "trust deed", "registered under"],
    "affidavit": ["affidavit", "undertaking", "solemnly affirm", "deponent", "notary"],
    "accreditation_certificate": ["accreditation", "national board of accreditation", "naac", "accredited"],
    "noc": ["no objection certificate", "no objection", "noc"],
    "faculty_list": ["faculty list", "list of faculty", "designation", "fid"],
    "qualification_certificate": ["degree", "doctor of philosophy", "master of", "university", "awarded to", "convocation"],
    "publication_list": ["publication", "doi", "indexed in", "journal", "authors"],
    "previous_approval": ["extension of approval", "eoa", "approval letter", "approved intake", "all india council"],
    "intake_details": ["programme", "intake", "programme wise", "course wise"],
    "infrastructure_photo": ["room", "laboratory", "classroom", "lab"],
    "floor_plan": ["floor plan", "carpet area", "sq m", "sqm", "built up area"],
    "fire_safety_certificate": ["fire safety", "fire and rescue", "fire noc", "fire service"],
    "fee_receipt": ["transaction id", "amount paid", "receipt", "processing fee", "payment"],
}


def classify(text: str, declared_type: str) -> tuple[str, dict]:
    t = " " + norm_text(text) + " "
    scores: dict[str, list[str]] = {}
    for dtype, kws in KEYWORDS.items():
        hits = [k for k in kws if f" {norm_text(k)} " in t]
        if hits:
            scores[dtype] = hits
    if not scores:
        return declared_type, {"method": "keyword match", "matches": {}, "note": "No classification keywords found; declared type retained."}
    best = max(scores.items(), key=lambda kv: len(kv[1]))
    declared_hits = scores.get(declared_type, [])
    chosen = declared_type if len(declared_hits) >= len(best[1]) else best[0]
    return chosen, {
        "method": "keyword match",
        "matches": scores,
        "declared_type_hits": declared_hits,
        "best_type": best[0],
        "agrees_with_declared": chosen == declared_type,
    }
