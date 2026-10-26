"""Reviewer: document inventory, viewer pages, original downloads, extracted-field confirmation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, serialize, storage
from ..db import get_db
from ..models import Document, DocumentVersion, ExtractedField, Finding, ReviewerNote, User, utcnow
from ..security import client_ip, get_application_for_reviewer, require_reviewer
from ..services import review
from ..services.extraction import render_page_png

router = APIRouter(prefix="/api/reviewer", tags=["reviewer-documents"])


def _doc(db: Session, user: User, application_id: int, document_id: int) -> Document:
    app = get_application_for_reviewer(application_id, user, db)
    doc = db.get(Document, document_id)
    if not doc or doc.application_id != app.id:
        raise HTTPException(404, "Document not found in this application")
    return doc


def _version(db: Session, user: User, version_id: int) -> DocumentVersion:
    dv = db.get(DocumentVersion, version_id)
    if not dv:
        raise HTTPException(404, "Document version not found")
    get_application_for_reviewer(dv.document.application_id, user, db)
    return dv


@router.get("/applications/{application_id}/documents")
def documents(application_id: int, q: str | None = None, document_type: str | None = None, status: str | None = None,
              user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    out = []
    for d in app.documents:
        if not d.current:
            continue
        if document_type and d.document_type != document_type:
            continue
        if status and d.current.processing_status != status:
            continue
        if q and q.lower() not in (d.title + " " + d.current.original_filename + " " + d.document_type).lower():
            continue
        item = serialize.document(d)
        vids = [v.id for v in d.versions]
        item["open_findings"] = db.execute(select(Finding.id).where(
            Finding.application_id == app.id, Finding.is_issue.is_(True), Finding.status.notin_(["resolved", "verified"]),
            Finding.review_state != "dismissed",
            or_(Finding.document_version_id.in_(vids), Finding.related_document_version_id.in_(vids)))).scalars().all().__len__()
        out.append(item)
    return out


@router.get("/applications/{application_id}/documents/{document_id}")
def document_detail(application_id: int, document_id: int, version: int | None = None,
                    user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    doc = _doc(db, user, application_id, document_id)
    official = [v for v in doc.versions if not v.is_pending]
    if not official:
        raise HTTPException(404, "Document has no submitted version")
    sel = next((v for v in official if v.version_no == version), official[-1]) if version else official[-1]
    vids = [v.id for v in doc.versions]
    fs = db.execute(select(Finding).where(Finding.application_id == application_id, or_(
        Finding.document_version_id.in_(vids), Finding.related_document_version_id.in_(vids))).order_by(Finding.id)).scalars().all()
    notes = db.execute(select(ReviewerNote).where(ReviewerNote.document_id == doc.id).order_by(ReviewerNote.id)).scalars().all()
    return {
        "document": serialize.document(doc),
        "selected_version": serialize.version(sel, with_fields=True),
        "versions": [serialize.version(v, with_fields=True) for v in official],
        "findings": [serialize.finding(f, full=True) for f in fs],
        "notes": [{"id": n.id, "body": n.body, "author": serialize.user_brief(n.author), "created_at": serialize.iso(n.created_at)} for n in notes],
    }


@router.get("/document-versions/{version_id}/pages/{page}.png")
def page_image(version_id: int, page: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    dv = _version(db, user, version_id)
    try:
        png = render_page_png(storage.read_bytes(dv.storage_key), dv.mime_type, page)
    except ValueError:
        raise HTTPException(404, "Page not found")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@router.get("/document-versions/{version_id}/file")
def original_file(version_id: int, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    dv = _version(db, user, version_id)
    data = storage.read_bytes(dv.storage_key)
    audit.record(db, "document.downloaded", "document_version", dv.id, actor=user, application_id=dv.document.application_id,
                 summary=f"Downloaded original of {dv.document.title} v{dv.version_no}", ip=client_ip(request))
    db.commit()
    return Response(data, media_type=dv.mime_type, headers={
        "Content-Disposition": f'attachment; filename="{dv.original_filename}"', "X-Content-Type-Options": "nosniff"})


class ConfirmIn(BaseModel):
    value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default="", max_length=500)


@router.post("/fields/{field_id}/confirm")
def confirm_field(field_id: int, body: ConfirmIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    f = db.get(ExtractedField, field_id)
    if not f:
        raise HTTPException(404, "Field not found")
    dv = _version(db, user, f.document_version_id)
    old = f.effective_value
    f.confirmed_value = body.value.strip()
    f.confirmed_by_id = user.id
    f.confirmed_at = utcnow()
    audit.record(db, "field.confirmed", "extracted_field", f.id, actor=user, application_id=dv.document.application_id,
                 summary=f"Confirmed {f.field_name} on {dv.document.title}: '{old}' → '{f.confirmed_value}'",
                 details={"extracted": f.value, "confirmed": f.confirmed_value, "reason": body.reason}, ip=client_ip(request))
    db.commit()
    return serialize.field(f)


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(accept|reject|manual)$")
    note: str = Field(default="", max_length=2000)


@router.post("/document-versions/{version_id}/review")
def review_document(version_id: int, body: ReviewIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    """Accept, reject (with reason) or flag a document version for manual verification."""
    dv = _version(db, user, version_id)
    app = dv.document.application
    if app.status in ("decided", "awaiting_decision"):
        raise HTTPException(409, "Document decisions are closed at this stage")
    if dv.is_pending or dv.document.current.id != dv.id:
        raise HTTPException(409, "Only the current submitted version can be reviewed")
    resolved: list[str] = []
    if body.action == "accept":
        resolved = review.accept(db, dv, user, body.note)
    elif body.action == "reject":
        review.reject(db, dv, user, body.note)
    else:
        review.mark_manual(db, dv, user, body.note)
    label = {"accept": "accepted", "reject": "rejected", "manual": "marked for manual verification"}[body.action]
    audit.record(db, f"document.{label.split()[0]}", "document_version", dv.id, actor=user, application_id=app.id,
                 summary=f"{dv.document.title} v{dv.version_no} {label}" + (f": {body.note.strip()[:200]}" if body.note.strip() else ""),
                 details={"resolved_findings": resolved}, ip=client_ip(request))
    db.commit()
    return {"review_status": dv.review_status, "resolved_findings": resolved, "application_status": app.status}
