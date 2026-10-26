"""Document-level review (accept / reject / manual verification), per-document status,
verification progress and the 'next action' shown to institution and officer.

Accepting a document never approves the application; it only records the officer's
judgement on that document version."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import DOCUMENT_TYPES
from ..models import (
    Application,
    DeficiencyNotice,
    Document,
    DocumentReview,
    DocumentVersion,
    Finding,
    FindingEvent,
    NoticeItem,
    User,
    VerificationRun,
    utcnow,
)

OPEN_STATES = ("resolved", "verified")

# Automated status → label shown to people (both portals use these words)
DOC_STATUS = {
    "missing": "Missing",
    "unreadable": "Unreadable",
    "invalid": "Invalid",
    "expired": "Expired",
    "mismatch": "Mismatch",
    "incomplete": "Incomplete",
    "manual_verification_required": "Manual verification required",
    "external_unavailable": "External verification unavailable",
    "checks_passed": "Automated checks passed",
    "not_verified": "Awaiting verification",
}
REVIEW_STATUS = {"pending": "Awaiting officer review", "accepted": "Accepted", "rejected": "Rejected", "manual": "Manual verification in progress"}


def _open_issue(f: Finding) -> bool:
    return f.is_issue and f.status not in OPEN_STATES and f.review_state != "dismissed"


def _doc_findings(findings: list[Finding], version_ids: set[int]) -> list[Finding]:
    return [f for f in findings if f.document_version_id in version_ids or f.related_document_version_id in version_ids]


def auto_status(v: DocumentVersion, doc_findings: list[Finding], verified_once: bool) -> tuple[str, str]:
    """(status, reason) from extraction state and the findings that reference this version."""
    if v.processing_status == "failed":
        return "invalid", f"The file could not be processed: {v.processing_error}"
    if v.processing_status != "processed":
        return "not_verified", "Not processed yet."
    if v.document.document_type != "infrastructure_photo" and (v.text_method == "none" or len(v.extracted_text.strip()) < 30):
        return "unreadable", "No readable text could be extracted (native text or OCR)."
    basis = v.classification_basis or {}
    if basis.get("agrees_with_declared") is False:
        return "invalid", f"Content resembles “{DOCUMENT_TYPES.get(basis.get('best_type', ''), basis.get('best_type', ''))}”, not the declared type."
    # Use the latest automated result: a replacement that now passes must not inherit the old official status.
    open_ = [f for f in doc_findings if _open_issue(f) and f.origin == "automated" and f.document_version_id == v.id
             and (f.latest_result or f.status) not in ("verified", "resolved", "not_reevaluated")]
    cur = lambda f: f.latest_result or f.status  # noqa: E731
    for status, key in (("expired", "expired"), ("mismatch", "mismatch"), ("missing", "incomplete")):
        hit = next((f for f in open_ if cur(f) == status), None)
        if hit:
            return key, hit.reason
    manual = next((f for f in open_ if cur(f) in ("manual_review", "inconclusive", "escalated")), None)
    low = [f for f in v.fields if f.needs_confirmation and f.confirmed_value is None]
    if manual:
        return "manual_verification_required", manual.reason
    if low:
        return "manual_verification_required", f"{len(low)} value(s) were read by OCR with low confidence and must be confirmed by an officer."
    if not verified_once:
        return "not_verified", "Run “Verify Application” to check this document."
    ext = next((f for f in doc_findings if f.status in ("source_unavailable", "pending", "simulated") and f.document_version_id == v.id), None)
    if ext:
        return "external_unavailable", ext.reason
    return "checks_passed", "All automated checks on this document passed."


def document_rows(db: Session, app: Application, internal: bool = True) -> dict:
    """Checklist-ordered rows: one per current document, plus a 'missing' row for each mandatory type with no document."""
    findings = db.execute(select(Finding).where(Finding.application_id == app.id)).scalars().all()
    verified_once = db.execute(select(VerificationRun.id).where(VerificationRun.application_id == app.id,
                                                                VerificationRun.status == "completed")).first() is not None
    rows = []
    docs = [d for d in app.documents if d.current]
    order = {c.document_type: i for i, c in enumerate(app.category.checklist)}
    for d in sorted(docs, key=lambda d: (order.get(d.document_type, 99), d.id)):
        v = d.current
        vids = {x.id for x in d.versions}
        dfs = _doc_findings(findings, vids)
        st, why = auto_status(v, dfs, verified_once)
        hist = db.execute(select(DocumentReview).where(DocumentReview.document_version_id.in_(vids)).order_by(DocumentReview.id)).scalars().all()
        row = {
            "document_id": d.id, "title": d.title, "document_type": d.document_type,
            "document_type_label": DOCUMENT_TYPES.get(d.document_type, d.document_type),
            "version_id": v.id, "version_no": v.version_no, "versions": len([x for x in d.versions if not x.is_pending]),
            "original_filename": v.original_filename, "mime_type": v.mime_type, "page_count": v.page_count,
            "uploaded_at": v.uploaded_at.isoformat(), "submission_version": v.submission_version,
            "auto_status": st, "auto_status_label": DOC_STATUS[st], "auto_reason": why,
            "review_status": v.review_status, "review_status_label": REVIEW_STATUS[v.review_status],
            "review_note": v.review_note if internal or v.review_status == "rejected" else "",
            "manually_verified": v.manually_verified, "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
        }
        if internal:
            row.update({
                "text_method": v.text_method, "ocr_mean_confidence": v.ocr_mean_confidence,
                "open_findings": [f.id for f in dfs if _open_issue(f)],
                "reviewed_by": db.get(User, v.reviewed_by_id).full_name if v.reviewed_by_id else None,
                "history": [{"action": h.action, "note": h.note, "actor": h.actor.full_name, "at": h.created_at.isoformat(),
                             "version_id": h.document_version_id} for h in hist],
            })
        rows.append(row)
    present = {d.document_type for d in docs}
    missing = [{"document_type": c.document_type, "document_type_label": c.label, "guidance": c.guidance}
               for c in app.category.checklist if c.mandatory and c.document_type not in present]
    accepted = sum(1 for r in rows if r["review_status"] == "accepted")
    return {
        "documents": rows,
        "missing": missing,
        "progress": {"accepted": accepted, "total": len(rows), "missing_types": len(missing),
                     "rejected": sum(1 for r in rows if r["review_status"] == "rejected"),
                     "pending": sum(1 for r in rows if r["review_status"] in ("pending", "manual")),
                     "verified_once": verified_once},
    }


def _record(db: Session, v: DocumentVersion, user: User, action: str, note: str) -> None:
    v.review_status = action
    v.review_note = note
    v.reviewed_by_id = user.id
    v.reviewed_at = utcnow()
    db.add(DocumentReview(document_version_id=v.id, action=action, note=note, actor_id=user.id))


def _resolve_finding(db: Session, f: Finding, user: User, detail: str) -> None:
    prev = f.status
    f.status, f.review_state, f.reviewed_by_id, f.review_reason = "resolved", "confirmed", user.id, detail
    db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action="resolved", from_status=prev, to_status="resolved", detail=detail))
    for it in db.execute(select(NoticeItem).where(NoticeItem.finding_id == f.id, NoticeItem.status.in_(["open", "responded"]))).scalars():
        it.status, it.outcome_note = "resolved", detail
        _maybe_close_notice(db, it.notice)


def _maybe_close_notice(db: Session, n: DeficiencyNotice) -> None:
    if n.status == "responded" and all(i.status in ("resolved", "not_resolved", "escalated") for i in n.items):
        n.status = "closed"
        app = db.get(Application, n.application_id)
        if app.status in ("response_received", "reverification"):
            app.status = "under_scrutiny"


def accept(db: Session, v: DocumentVersion, user: User, note: str) -> list[str]:
    """Accept a document version. Open findings about it must be acknowledged with a note; they are then resolved."""
    doc: Document = v.document
    findings = db.execute(select(Finding).where(Finding.application_id == doc.application_id)).scalars().all()
    vids = {x.id for x in doc.versions}
    linked = [f for f in _doc_findings(findings, vids) if _open_issue(f)]
    # Issues about this document type that reverification now shows as passing (e.g. a missing certificate now supplied)
    linked += [f for f in findings if _open_issue(f) and f not in linked and f.document_type == doc.document_type
               and f.latest_result == "verified"]
    unresolved_auto = [f for f in linked if f.latest_result not in ("verified", "resolved") and f.origin == "automated"]
    if unresolved_auto and len(note.strip()) < 10:
        raise HTTPException(422, f"{len(unresolved_auto)} automated finding(s) about this document are still open. "
                                 "Explain why you accept it (at least 10 characters).")
    low = [f for f in v.fields if f.needs_confirmation and f.confirmed_value is None]
    manual = v.review_status == "manual" or bool(low)
    _record(db, v, user, "accepted", note.strip())
    v.manually_verified = manual
    resolved = []
    for f in linked:
        _resolve_finding(db, f, user, f"Resolved when {doc.title} v{v.version_no} was accepted" + (f": {note.strip()}" if note.strip() else ""))
        resolved.append(f.code)
    return resolved


def reject(db: Session, v: DocumentVersion, user: User, reason: str) -> Finding:
    """Reject with a reason. Creates (or reopens) an officer finding so the rejection can go into a deficiency notice."""
    if len(reason.strip()) < 15:
        raise HTTPException(422, "Give a specific reason for rejecting this document (at least 15 characters).")
    doc = v.document
    _record(db, v, user, "rejected", reason.strip())
    fp = f"reject:doc{doc.id}"
    f = db.execute(select(Finding).where(Finding.application_id == doc.application_id, Finding.fingerprint == fp)).scalar_one_or_none()
    text = f"'{doc.title}' (version {v.version_no}) was not accepted: {reason.strip()}"
    if f is None:
        n = len(db.execute(select(Finding.id).where(Finding.application_id == doc.application_id)).scalars().all())
        f = Finding(application_id=doc.application_id, fingerprint=fp, code=f"F-{doc.application_id:03d}-{n + 1:03d}", category="manual",
                    title=f"Document rejected: {doc.title}", document_version_id=v.id, document_type=doc.document_type,
                    field="document", reason=reason.strip(), evidence=[{"type": "document", "document_id": doc.id, "document_version_id": v.id,
                    "version_no": v.version_no, "document_title": doc.title, "note": "Rejected by officer"}],
                    certainty="confirmed", origin="manual", severity="high", status="rejected", latest_result="rejected", is_issue=True,
                    review_state="confirmed", reviewed_by_id=user.id, method="Officer review",
                    recommended_action="Ask the institution for a corrected document.", institution_text=text)
        db.add(f)
        db.flush()
        db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action="created", to_status="rejected", detail=reason.strip()))
    else:
        prev = f.status
        f.status = f.latest_result = "rejected"
        f.document_version_id, f.reason, f.institution_text, f.review_state = v.id, reason.strip(), text, "confirmed"
        f.in_notice = False
        db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action="rejected_again", from_status=prev, to_status="rejected", detail=reason.strip()))
    return f


def mark_manual(db: Session, v: DocumentVersion, user: User, reason: str) -> None:
    if len(reason.strip()) < 5:
        raise HTTPException(422, "Say what needs to be checked manually.")
    _record(db, v, user, "manual", reason.strip())


def next_action(db: Session, app: Application, rows: dict | None = None) -> dict:
    """Plain-language current stage and next action for both portals."""
    notice = db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id == app.id)
                        .order_by(DeficiencyNotice.id.desc())).scalars().first()
    deadline = notice.response_deadline.strftime("%d %b %Y") if notice and notice.response_deadline else ""
    s = app.status
    if s == "draft":
        return {"institution": "Upload the required documents and submit the application.", "officer": ""}
    if s == "submitted":
        return {"institution": "Submitted. Waiting for scrutiny to start.", "officer": "Run Verify Application."}
    if s == "notice_issued":
        return {"institution": f"Respond to deficiency notice {notice.reference} by {deadline}.",
                "officer": f"Waiting for the institution to respond (deadline {deadline})."}
    if s in ("reverification", "response_received"):
        return {"institution": "Response received. The scrutiny officer is reviewing your corrected documents.",
                "officer": "Review the institution’s response and the corrected documents."}
    if s == "awaiting_decision":
        return {"institution": "Scrutiny complete. Awaiting the final decision.", "officer": "Record the final decision."}
    if s == "decided":
        return {"institution": "Decision recorded.", "officer": "Complete."}
    rows = rows or document_rows(db, app)
    p = rows["progress"]
    open_issues = db.execute(select(Finding).where(Finding.application_id == app.id)).scalars().all()
    n_open = sum(1 for f in open_issues if _open_issue(f) and not f.in_notice)
    if not p["verified_once"]:
        off = "Run Verify Application."
    elif p["pending"]:
        off = f"Review {p['pending']} document(s): accept, reject or verify manually."
    elif n_open or p["rejected"] or p["missing_types"]:
        off = "Send a deficiency notice for the outstanding items, or resolve them."
    else:
        off = "All documents accepted. Move the application to decision."
    return {"institution": "Under scrutiny.", "officer": off}
