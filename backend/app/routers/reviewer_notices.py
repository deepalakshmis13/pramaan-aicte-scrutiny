"""Scrutiny officer: deficiency notices (create and send in one step), response review, decisions, reports, audit."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, serialize, storage
from ..db import get_db
from ..enums import DECISION_OUTCOMES, DOCUMENT_TYPES, NOTICE_STATUSES
from ..models import (
    Application,
    AuditEvent,
    Decision,
    DeficiencyNotice,
    DocumentVersion,
    Finding,
    FindingEvent,
    NoticeItem,
    Notification,
    Report,
    SystemConfig,
    User,
    utcnow,
)
from ..security import client_ip, get_application_for_reviewer, require_reviewer
from ..services import engine, notify, pdf_reports, review
from .common import OPEN_ISSUE, accessible_apps

router = APIRouter(prefix="/api/reviewer", tags=["reviewer-notices"])

ACTION_BY_STATUS = {
    "missing": "Upload the required document or the missing details.",
    "expired": "Upload a currently valid certificate covering the academic year under consideration.",
    "mismatch": "Submit a corrected document, or a written clarification supported by evidence explaining the difference.",
    "manual_review": "Provide a clarification and any supporting evidence requested.",
    "escalated": "Provide the additional evidence requested; the item may require inspection.",
    "rejected": "Upload a corrected document that addresses the reason given.",
}


def _notice(db: Session, user: User, notice_id: int) -> DeficiencyNotice:
    n = db.get(DeficiencyNotice, notice_id)
    if not n:
        raise HTTPException(404, "Notice not found")
    get_application_for_reviewer(n.application_id, user, db)
    return n


def _store_report(db: Session, app: Application, kind: str, pdf: bytes, user: User, *, notice=None, decision=None, preview=False, conf="") -> Report:
    key = storage.new_key("reports", app.id, ".pdf")
    storage.save_bytes(key, pdf)
    n = db.execute(select(func.count(Report.id)).where(Report.application_id == app.id, Report.kind == kind)).scalar() or 0
    r = Report(reference=f"RPT-{app.id:04d}-{kind[:3].upper()}-{n + 1:03d}", application_id=app.id, kind=kind,
               notice_id=notice.id if notice else None, decision_id=decision.id if decision else None, version=n + 1,
               is_preview=preview, confidentiality=conf, storage_key=key, sha256=storage.sha256(pdf), size_bytes=len(pdf),
               generated_by_id=user.id)
    db.add(r)
    db.flush()
    return r


def _delivery(db: Session, n: DeficiencyNotice) -> dict:
    """Portal delivery status, derived from the notifications actually created for institution users."""
    rows = db.execute(select(Notification).where(Notification.kind == "notice_issued", Notification.link_path == f"/institution/notices/{n.id}")).scalars().all()
    if not rows:
        return {"status": "not_delivered", "label": "No institution account to notify — share the PDF", "seen_at": None}
    seen = [r.read_at for r in rows if r.read_at]
    return {"status": "seen" if seen else "delivered", "label": "Seen by institution" if seen else "Delivered to institution portal",
            "seen_at": serialize.iso(min(seen)) if seen else None, "recipients": len(rows)}


def notice_summary(db: Session, n: DeficiencyNotice) -> dict:
    a = db.get(Application, n.application_id)
    responded = sum(1 for it in n.items if any(r.status == "submitted" for r in it.responses))
    return {"id": n.id, "reference": n.reference, "status": n.status, "status_label": NOTICE_STATUSES.get(n.status, n.status),
            "application_id": a.id, "application_reference": a.reference, "institution": a.institution.name, "institution_id": a.institution_id,
            "items": len(n.items), "responded_items": responded, "prepared_by": serialize.user_brief(n.prepared_by),
            "issued_at": serialize.iso(n.issued_at), "response_deadline": serialize.iso(n.response_deadline),
            "delivery": _delivery(db, n), "report_id": n.report_id}


@router.get("/notices")
def all_notices(status: str | None = None, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    stmt = select(DeficiencyNotice).where(DeficiencyNotice.status != "withdrawn")
    if status:
        stmt = stmt.where(DeficiencyNotice.status.in_(status.split(",")))
    return [notice_summary(db, n) for n in db.execute(stmt.order_by(DeficiencyNotice.id.desc())).scalars()]


@router.get("/notice-candidates/{application_id}")
def notice_candidates(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    """Open findings (including rejected documents) not already in a notice, pre-worded for the institution."""
    app = get_application_for_reviewer(application_id, user, db)
    fs = db.execute(select(Finding).where(Finding.application_id == app.id, OPEN_ISSUE, Finding.in_notice.is_(False))).scalars().all()
    order = {"rejected": 0, "missing": 1, "expired": 2, "mismatch": 3}
    # A rejected document already states the reason; other findings on that same version are folded into it
    rejected_versions = {f.document_version_id for f in fs if f.status == "rejected"}
    fs = [f for f in fs if f.status == "rejected" or f.document_version_id not in rejected_versions]
    out = []
    for f in sorted(fs, key=lambda f: (order.get(f.status, 9), f.id)):
        dv = db.get(DocumentVersion, f.document_version_id) if f.document_version_id else None
        internal_only = f.category == "anomaly" or f.fingerprint.startswith("dupx:")
        out.append({
            "finding_id": f.id, "code": f.code, "status": f.status, "category": f.category, "title": f.title, "reason": f.reason,
            "document": f"{dv.document.title} (version {dv.version_no})" if dv else DOCUMENT_TYPES.get(f.document_type, f.document_type or "—"),
            "suggested_title": (f"Document requires verification: {dv.document.title}" if dv else "Document requires verification") if internal_only else f.title,
            "suggested_description": f.institution_text or f.reason,
            "suggested_action": ACTION_BY_STATUS.get(f.status, "Provide a clarification and supporting evidence."),
        })
    cfg = db.get(SystemConfig, "notice_response_days")
    days = int((cfg.value or {}).get("value", 15)) if cfg else 15
    return {"items": out, "default_deadline": (engine.reference_date(db) + timedelta(days=days)).isoformat()}


class NoticeItemIn(BaseModel):
    finding_id: int
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=5, max_length=4000)
    corrective_action: str = Field(min_length=5, max_length=2000)


class NoticeSendIn(BaseModel):
    items: list[NoticeItemIn] = Field(min_length=1, max_length=100)
    cover_note: str = Field(default="", max_length=3000)
    response_deadline: date


@router.post("/applications/{application_id}/notices", status_code=201)
def send_notice(application_id: int, body: NoticeSendIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    """Create and send a deficiency notice in one transaction. Success is returned only after the notice,
    its items, the PDF and the institution notifications are committed."""
    app = get_application_for_reviewer(application_id, user, db)
    if app.status not in ("under_scrutiny", "response_received"):
        raise HTTPException(409, "A notice can be sent while the application is under scrutiny or after reviewing a response")
    active = db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id == app.id, DeficiencyNotice.status == "issued")).scalars().first()
    if active:
        raise HTTPException(409, f"Notice {active.reference} is still awaiting the institution's response")
    if body.response_deadline < engine.reference_date(db):
        raise HTTPException(422, "The response deadline cannot be in the past")
    ids = [i.finding_id for i in body.items]
    fs = {f.id: f for f in db.execute(select(Finding).where(Finding.id.in_(ids), Finding.application_id == app.id, OPEN_ISSUE)).scalars()}
    if len(fs) != len(set(ids)):
        raise HTTPException(422, "Some selected items are not open findings of this application")
    seq = (db.execute(select(func.max(DeficiencyNotice.sequence)).where(DeficiencyNotice.application_id == app.id)).scalar() or 0) + 1
    now = utcnow()
    n = DeficiencyNotice(reference=f"DN-{app.reference}-{seq:02d}", application_id=app.id, sequence=seq, submission_version=app.current_version,
                         status="issued", cover_note=body.cover_note.strip(), response_deadline=body.response_deadline, prepared_by_id=user.id,
                         issued_at=now, delivery_channel="Institution portal notification and PDF download (no external e-mail integration)")
    db.add(n)
    db.flush()
    for i, it in enumerate(body.items, start=1):
        f = fs[it.finding_id]
        dv = db.get(DocumentVersion, f.document_version_id) if f.document_version_id else None
        rule = f.rule_version
        db.add(NoticeItem(notice_id=n.id, finding_id=f.id, item_no=i, title=it.title.strip(), description=it.description.strip(),
                          corrective_action=it.corrective_action.strip(),
                          document_reference=f"{dv.document.title} (version {dv.version_no})" if dv else DOCUMENT_TYPES.get(f.document_type, "—"),
                          rule_reference=f"{rule.rule.code} v{rule.version} — {rule.rule.title}" if rule else "Scrutiny officer’s review"))
        f.in_notice = True
        db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action="included_in_notice", from_status=f.status, to_status=f.status,
                            detail=f"Item {i} of {n.reference}"))
    db.flush()
    db.refresh(n)
    pdf = pdf_reports.deficiency_notice_pdf(db, n, preview=False)
    r = _store_report(db, app, "deficiency_notice", pdf, user, notice=n, conf="Confidential — addressed institution only")
    n.report_id = r.id
    app.status = "notice_issued"
    if app.assigned_reviewer_id is None:
        app.assigned_reviewer_id = user.id
    notify.to_institution(db, app.institution_id, "notice_issued", f"Deficiency notice {n.reference}",
                          f"{len(n.items)} item(s) need your response by {n.response_deadline.strftime('%d %b %Y')}.", f"/institution/notices/{n.id}", app.id)
    audit.record(db, "notice.issued", "notice", n.id, actor=user, application_id=app.id,
                 summary=f"{n.reference} sent to {app.institution.name} ({len(n.items)} items, respond by {n.response_deadline.isoformat()})",
                 details={"report_sha256": r.sha256, "finding_ids": ids}, ip=client_ip(request))
    db.commit()
    # Confirm from the database that the notice is persisted and linked before reporting success.
    saved = db.get(DeficiencyNotice, n.id)
    linked = db.get(Application, saved.application_id)
    if not saved or saved.status != "issued" or linked.institution_id != app.institution_id:
        raise HTTPException(500, "The notice could not be confirmed after saving")
    return notice_summary(db, saved) | {"notice": serialize.notice(saved, internal=True)}


@router.get("/notices/{notice_id}")
def get_notice(notice_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    n = _notice(db, user, notice_id)
    return notice_summary(db, n) | {"notice": serialize.notice(n, internal=True)}


# ------------------------------------------------------------------ responses & reverification


@router.get("/applications/{application_id}/responses")
def responses(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    out = []
    for n in db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id == app.id,
                        DeficiencyNotice.status.in_(["issued", "responded", "closed"])).order_by(DeficiencyNotice.id.desc())).scalars():
        d = serialize.notice(n, internal=True)
        for it, item in zip(n.items, d["items"]):
            f = it.finding
            item["finding"] = serialize.finding(f, full=True)
            item["comparison"] = None
            sub = [r for r in it.responses if r.status == "submitted" and r.document_version]
            if sub:
                new = sub[-1].document_version
                old = None
                if new.version_no > 1:
                    old = next((v for v in new.document.versions if v.version_no == new.version_no - 1), None)
                item["comparison"] = {
                    "document_id": new.document_id, "document_title": new.document.title,
                    "previous": serialize.version(old, with_fields=True) if old else None,
                    "replacement": serialize.version(new, with_fields=True),
                    "hash_changed": (old.sha256 != new.sha256) if old else True,
                }
            item["events"] = [serialize.finding_event(e, db.get(User, e.actor_id) if e.actor_id else None) for e in f.events]
        out.append(d)
    return out


class OutcomeIn(BaseModel):
    outcome: str = Field(pattern="^(resolved|not_resolved|escalated)$")
    note: str = Field(min_length=3, max_length=2000)


@router.post("/notice-items/{item_id}/outcome")
def item_outcome(item_id: int, body: OutcomeIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    it = db.get(NoticeItem, item_id)
    if not it:
        raise HTTPException(404, "Notice item not found")
    n = it.notice
    app = get_application_for_reviewer(n.application_id, user, db)
    if n.status not in ("responded", "issued"):
        raise HTTPException(409, "Outcomes are recorded after the notice is issued")
    f = it.finding
    if body.outcome == "resolved" and f.latest_result not in ("verified", "resolved") and len(body.note.strip()) < 15:
        raise HTTPException(422, "The latest automated check for this item does not pass. Provide a justification (15+ characters) to resolve it manually.")
    prev = f.status
    it.status, it.outcome_note = body.outcome, body.note.strip()
    if body.outcome == "resolved":
        f.status = "resolved"
    elif body.outcome == "escalated":
        f.status = "escalated"
    f.review_state = "confirmed"
    f.reviewed_by_id = user.id
    f.review_reason = body.note.strip()
    db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action=f"notice_item_{body.outcome}", from_status=prev, to_status=f.status,
                        detail=f"{n.reference} item {it.item_no}: {body.note.strip()}"))
    if all(i.status in ("resolved", "not_resolved", "escalated") for i in n.items) and n.status == "responded":
        n.status = "closed"
        if app.status in ("response_received", "reverification"):
            app.status = "under_scrutiny"
    audit.record(db, "notice_item.outcome", "notice_item", it.id, actor=user, application_id=app.id,
                 summary=f"{n.reference} item {it.item_no} marked {body.outcome.replace('_', ' ')}", details={"note": body.note}, ip=client_ip(request))
    db.commit()
    return {"item_status": it.status, "finding_status": f.status, "notice_status": n.status}


@router.post("/applications/{application_id}/ready-for-decision")
def ready_for_decision(application_id: int, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    if app.status not in ("under_scrutiny", "response_received"):
        raise HTTPException(409, "Only applications under scrutiny can be moved to decision")
    blocking = db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id == app.id,
                          DeficiencyNotice.status == "issued")).scalars().first()
    if blocking:
        raise HTTPException(409, f"Notice {blocking.reference} is still awaiting the institution's response")
    pending = [r for r in review.document_rows(db, app)["documents"] if r["review_status"] != "accepted"]
    if pending:
        raise HTTPException(409, f"{len(pending)} document(s) are not yet accepted. Accept, or reject them and send a notice, first.")
    app.status = "awaiting_decision"
    audit.record(db, "application.ready_for_decision", "application", app.id, actor=user, application_id=app.id,
                 summary=f"{app.reference} sent for final official decision", ip=client_ip(request))
    db.commit()
    return {"status": app.status}


@router.get("/applications/{application_id}/decision-context")
def decision_context(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    fs = db.execute(select(Finding).where(Finding.application_id == app.id)).scalars().all()
    open_ = [f for f in fs if f.is_issue and f.status not in ("resolved", "verified") and f.review_state != "dismissed"]
    gaps = [f for f in fs if f.status in ("source_unavailable", "pending", "simulated")]
    decs = db.execute(select(Decision).where(Decision.application_id == app.id).order_by(Decision.id)).scalars().all()
    return {
        "application": serialize.application_brief(app, engine.priority(db, app)),
        "can_record": app.status == "awaiting_decision",
        "open_issues": [serialize.finding(f) for f in open_],
        "verification_gaps": [serialize.finding(f) for f in gaps],
        "resolved": [serialize.finding(f) for f in fs if f.status == "resolved"],
        "outcomes": DECISION_OUTCOMES,
        "decisions": [{"id": d.id, "outcome": d.outcome, "outcome_label": DECISION_OUTCOMES.get(d.outcome), "reasons": d.reasons,
                       "conditions": d.conditions, "decided_by": serialize.user_brief(d.decided_by), "decided_at": serialize.iso(d.decided_at),
                       "report_id": d.report_id, "open_issue_count": d.open_issue_count} for d in decs],
        "notice": "The system does not recommend an outcome. The decision and its reasons are recorded by the authorised official.",
    }


class DecisionIn(BaseModel):
    outcome: str
    reasons: str = Field(min_length=20, max_length=6000)
    conditions: str = Field(default="", max_length=4000)
    acknowledge_open_issues: bool = False


@router.post("/applications/{application_id}/decision", status_code=201)
def record_decision(application_id: int, body: DecisionIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    if body.outcome not in DECISION_OUTCOMES:
        raise HTTPException(422, "Unknown outcome")
    if app.status != "awaiting_decision":
        raise HTTPException(409, "The application has not been sent for decision")
    open_n = db.execute(select(func.count(Finding.id)).where(Finding.application_id == app.id, OPEN_ISSUE)).scalar() or 0
    if open_n and not body.acknowledge_open_issues:
        raise HTTPException(409, f"{open_n} finding(s) remain open. Review them or explicitly acknowledge them before recording a decision.")
    if body.outcome == "approved_with_conditions" and len(body.conditions.strip()) < 10:
        raise HTTPException(422, "State the conditions")
    d = Decision(application_id=app.id, outcome=body.outcome, reasons=body.reasons.strip(), conditions=body.conditions.strip(),
                 decided_by_id=user.id, submission_version=app.current_version, open_issue_count=open_n,
                 acknowledged_open_issues=body.acknowledge_open_issues and open_n > 0)
    db.add(d)
    db.flush()
    db.refresh(d)
    pdf = pdf_reports.decision_pdf(db, d)
    r = _store_report(db, app, "final_decision", pdf, user, decision=d, conf="Official record")
    d.report_id = r.id
    app.status = "decided"
    notify.to_institution(db, app.institution_id, "decision_recorded", f"Decision recorded — {app.reference}",
                          DECISION_OUTCOMES[body.outcome], f"/institution/applications/{app.id}", app.id)
    audit.record(db, "decision.recorded", "decision", d.id, actor=user, application_id=app.id,
                 summary=f"Decision recorded by {user.full_name}: {DECISION_OUTCOMES[body.outcome]}",
                 details={"open_issues": open_n, "acknowledged": body.acknowledge_open_issues, "report_sha256": r.sha256}, ip=client_ip(request))
    db.commit()
    return {"id": d.id, "report_id": r.id}


# ------------------------------------------------------------------ reports


@router.get("/applications/{application_id}/reports")
def reports(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    get_application_for_reviewer(application_id, user, db)
    return [serialize.report(r) for r in db.execute(select(Report).where(Report.application_id == application_id).order_by(Report.id.desc())).scalars()]


@router.post("/applications/{application_id}/reports/internal", status_code=201)
def internal_report(application_id: int, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    pdf = pdf_reports.internal_review_pdf(db, app, user)
    r = _store_report(db, app, "internal_review", pdf, user, conf="Restricted — AICTE internal use")
    audit.record(db, "report.generated", "report", r.id, actor=user, application_id=app.id, summary=f"Internal reviewer report {r.reference} generated",
                 details={"sha256": r.sha256}, ip=client_ip(request))
    db.commit()
    return serialize.report(r)


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    get_application_for_reviewer(r.application_id, user, db)
    audit.record(db, "report.downloaded", "report", r.id, actor=user, application_id=r.application_id, summary=f"Downloaded {r.reference}", ip=client_ip(request))
    db.commit()
    return Response(storage.read_bytes(r.storage_key), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{r.reference}.pdf"', "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ audit


@router.get("/audit")
def audit_log(application_id: int | None = None, action: str | None = None, q: str | None = Query(None, max_length=100),
              page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
              user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    ids = [a.id for a in db.execute(accessible_apps(user)).scalars()] or [-1]
    stmt = select(AuditEvent).where(AuditEvent.application_id.in_(ids))
    if application_id:
        stmt = stmt.where(AuditEvent.application_id == application_id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if q:
        stmt = stmt.where(AuditEvent.summary.ilike(f"%{q}%") | AuditEvent.actor_label.ilike(f"%{q}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [audit_row(db, e) for e in rows]}


def audit_row(db: Session, e: AuditEvent) -> dict:
    ref = None
    if e.application_id:
        a = db.get(Application, e.application_id)
        ref = a.reference if a else None
    return {"id": e.id, "at": serialize.iso(e.created_at), "actor": e.actor_label, "actor_role": e.actor_role, "action": e.action,
            "entity_type": e.entity_type, "entity_id": e.entity_id, "application_id": e.application_id, "application_reference": ref,
            "summary": e.summary, "details": e.details, "ip": e.ip_address, "hash": e.hash, "prev_hash": e.prev_hash}
