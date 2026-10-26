"""Institution representative workspace. Every query is scoped to the user's institution.
Internal reviewer notes, source-check internals, priority and unissued findings are never returned."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, serialize, storage
from ..db import get_db
from ..enums import DECISION_OUTCOMES, DOCUMENT_TYPES
from ..models import (
    Application,
    ApplicationCategory,
    Decision,
    DeficiencyNotice,
    Document,
    DocumentVersion,
    InstitutionResponse,
    NoticeItem,
    Report,
    Submission,
    User,
    utcnow,
)
from ..security import client_ip, get_application_for_institution, require_institution
from ..services import engine, notify, review
from ..services.uploads import add_version, read_validated

router = APIRouter(prefix="/api/institution", tags=["institution"])

VISIBLE_NOTICE = ("issued", "responded", "closed")
INSTITUTION_STATUS = {
    "draft": "Draft — not yet submitted",
    "submitted": "Received — awaiting scrutiny",
    "under_scrutiny": "Under scrutiny",
    "notice_issued": "Action required — deficiency notice issued",
    "response_received": "Response received — under review",
    "reverification": "Response received — reverification in progress",
    "awaiting_decision": "Scrutiny complete — awaiting decision",
    "decided": "Decision recorded",
}


def _app_brief(a: Application, db: Session | None = None) -> dict:
    d = {"id": a.id, "reference": a.reference, "status": a.status, "status_label": INSTITUTION_STATUS.get(a.status, a.status),
         "category": a.category.name, "category_code": a.category.code, "academic_year": a.academic_year,
         "submitted_at": serialize.iso(a.submitted_at) if a.status != "draft" else None,
         "current_version": a.current_version, "is_synthetic": a.is_synthetic, "updated_at": serialize.iso(a.updated_at)}
    if db is not None:
        d["next_action"] = review.next_action(db, a)["institution"]
    return d


def _inst_doc_rows(db: Session, a: Application) -> dict:
    """Document rows as the institution may see them: upload problems, officer acceptance/rejection (with reason), never internal findings."""
    rows = review.document_rows(db, a, internal=False)
    for r in rows["documents"]:
        if a.status == "draft" or r["auto_status"] in ("unreadable", "invalid") and r["review_status"] == "pending":
            r["status"], r["status_label"], r["status_reason"] = r["auto_status"], r["auto_status_label"], (
                r["auto_reason"] if r["auto_status"] in ("unreadable", "invalid") else "Will be verified after submission.")
            if r["status"] == "not_verified":
                r["status"], r["status_label"] = "uploaded", "Uploaded — awaiting verification"
        else:
            r["status"], r["status_label"] = r["review_status"], {"pending": "Awaiting verification", "manual": "Being verified manually",
                                                                  "accepted": "Accepted", "rejected": "Rejected"}[r["review_status"]]
            r["status_reason"] = r["review_note"] if r["review_status"] == "rejected" else ""
        for k in ("auto_status", "auto_status_label", "auto_reason", "review_note"):
            r.pop(k, None)
    return rows


def _notice_for_inst(db: Session, user: User, notice_id: int) -> DeficiencyNotice:
    n = db.get(DeficiencyNotice, notice_id)
    if not n or n.status not in VISIBLE_NOTICE:
        raise HTTPException(404, "Notice not found")
    get_application_for_institution(n.application_id, user, db)
    return n


@router.get("/dashboard")
def dashboard(user: User = Depends(require_institution), db: Session = Depends(get_db)):
    apps = db.execute(select(Application).where(Application.institution_id == user.institution_id).order_by(Application.id.desc())).scalars().all()
    ids = [a.id for a in apps] or [-1]
    notices = db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id.in_(ids), DeficiencyNotice.status.in_(VISIBLE_NOTICE))
                         .order_by(DeficiencyNotice.id.desc())).scalars().all()
    action = []
    for n in notices:
        if n.status == "issued":
            pending = [i for i in n.items if not any(r.status == "draft" for r in i.responses)]
            a = db.get(Application, n.application_id)
            action.append({"notice_id": n.id, "reference": n.reference, "application_reference": a.reference, "application_id": a.id,
                           "items": len(n.items), "items_without_response": len(pending), "deadline": serialize.iso(n.response_deadline),
                           "days_left": (n.response_deadline - engine.reference_date(db)).days if n.response_deadline else None})
    for a in apps:
        if a.status == "draft":
            action.append({"draft_application_id": a.id, "reference": a.reference, "application_reference": a.reference, "application_id": a.id,
                           "items": 0, "items_without_response": 0, "deadline": None, "days_left": None})
    return {"institution": user.institution.name if user.institution else "", "permanent_id": user.institution.permanent_id if user.institution else "",
            "applications": [_app_brief(a, db) for a in apps], "action_required": action,
            "notices": [{"id": n.id, "reference": n.reference, "status": n.status, "items": len(n.items),
                         "issued_at": serialize.iso(n.issued_at), "application_id": n.application_id} for n in notices]}


@router.get("/applications")
def applications(user: User = Depends(require_institution), db: Session = Depends(get_db)):
    return [_app_brief(a, db) for a in db.execute(select(Application).where(Application.institution_id == user.institution_id)
                                                    .order_by(Application.id.desc())).scalars()]


@router.get("/applications/{application_id}")
def application(application_id: int, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    a = get_application_for_institution(application_id, user, db)
    subs = db.execute(select(Submission).where(Submission.application_id == a.id).order_by(Submission.version)).scalars().all()
    ns = db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id == a.id, DeficiencyNotice.status.in_(VISIBLE_NOTICE))
                    .order_by(DeficiencyNotice.id)).scalars().all()
    dec = db.execute(select(Decision).where(Decision.application_id == a.id).order_by(Decision.id.desc())).scalars().first()
    steps = ["draft", "submitted", "under_scrutiny", "notice_issued", "response_received", "awaiting_decision", "decided"]
    return {
        **_app_brief(a, db), "institution": a.institution.name, "permanent_id": a.institution.permanent_id, "declared": a.declared,
        "timeline": steps, **_inst_doc_rows(db, a),
        "checklist": [{"document_type": c.document_type, "label": c.label, "mandatory": c.mandatory, "guidance": c.guidance}
                      for c in a.category.checklist],
        "submissions": [{"version": s.version, "kind": s.kind, "submitted_at": serialize.iso(s.submitted_at), "note": s.note,
                         "notice_id": s.notice_id} for s in subs],
        "notices": [{"id": n.id, "reference": n.reference, "status": n.status, "items": len(n.items), "issued_at": serialize.iso(n.issued_at),
                     "response_deadline": serialize.iso(n.response_deadline)} for n in ns],
        "decision": {"outcome": dec.outcome, "outcome_label": DECISION_OUTCOMES.get(dec.outcome), "decided_at": serialize.iso(dec.decided_at),
                     "report_id": dec.report_id, "conditions": dec.conditions} if dec else None,
    }


@router.get("/notices")
def notices(user: User = Depends(require_institution), db: Session = Depends(get_db)):
    ids = [a.id for a in db.execute(select(Application).where(Application.institution_id == user.institution_id)).scalars()] or [-1]
    out = []
    for n in db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id.in_(ids), DeficiencyNotice.status.in_(VISIBLE_NOTICE))
                        .order_by(DeficiencyNotice.id.desc())).scalars():
        a = db.get(Application, n.application_id)
        out.append({"id": n.id, "reference": n.reference, "status": n.status, "application_id": a.id, "application_reference": a.reference,
                    "items": len(n.items), "issued_at": serialize.iso(n.issued_at), "response_deadline": serialize.iso(n.response_deadline)})
    return out


@router.get("/notices/{notice_id}")
def notice(notice_id: int, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    n = _notice_for_inst(db, user, notice_id)
    a = db.get(Application, n.application_id)
    d = serialize.notice(n, internal=False)
    d["application"] = _app_brief(a)
    d["can_respond"] = n.status == "issued"
    for it, item in zip(n.items, d["items"]):
        item["document_type_label"] = DOCUMENT_TYPES.get(it.finding.document_type, it.finding.document_type)
        item["upload_target"] = upload_target(it)
        item["needs_document"] = it.finding.status in ("missing", "expired", "rejected")
    return d


@router.post("/notice-items/{item_id}/response", status_code=201)
async def respond(item_id: int, request: Request, response_text: str = Form(..., min_length=3, max_length=4000),
                  file: UploadFile | None = File(None), user: User = Depends(require_institution), db: Session = Depends(get_db)):
    it = db.get(NoticeItem, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    n = _notice_for_inst(db, user, it.notice_id)
    if n.status != "issued":
        raise HTTPException(409, "This notice is no longer open for responses")
    app = db.get(Application, n.application_id)
    upload = None
    if file is not None and file.filename:
        upload = await read_validated(file)
    # replace an existing draft for this item
    for r in list(it.responses):
        if r.status == "draft":
            _discard_draft(db, r)
    dv = None
    if upload:
        data, mime, name = upload
        tgt = upload_target(it)
        if tgt["mode"] == "replace":
            target = db.get(Document, tgt["document_id"])
        else:
            target = Document(application_id=app.id, document_type=tgt["document_type"], title=tgt["label"])
            db.add(target)
            db.flush()
        dv = add_version(db, target, data, mime, name, user, app.current_version + 1, pending=True)
    r = InstitutionResponse(notice_item_id=it.id, author_id=user.id, response_text=response_text.strip(),
                            document_version_id=dv.id if dv else None, status="draft")
    db.add(r)
    audit.record(db, "institution.response_drafted", "notice_item", it.id, actor=user, application_id=app.id,
                 summary=f"Draft response to {n.reference} item {it.item_no}" + (f" with file {dv.original_filename}" if dv else ""),
                 details={"sha256": dv.sha256 if dv else None}, ip=client_ip(request))
    db.commit()
    db.refresh(r)
    return serialize.response(r)


def upload_target(it: NoticeItem) -> dict:
    """Where an uploaded correction goes: a new version of the cited document, or a new document of the required type."""
    f = it.finding
    dtype = f.document_type if f.document_type in DOCUMENT_TYPES else "other"
    cited = f.document_version.document if f.document_version else None
    if cited is not None and cited.document_type == dtype and f.status != "missing":
        return {"mode": "replace", "document_id": cited.id, "label": cited.title, "document_type": dtype}
    return {"mode": "new", "document_id": None, "label": DOCUMENT_TYPES.get(dtype, "Additional evidence"), "document_type": dtype}


def _discard_draft(db: Session, r: InstitutionResponse) -> None:
    dv = r.document_version
    db.delete(r)
    db.flush()
    if dv and dv.is_pending:
        doc = dv.document
        try:
            storage.path_for(dv.storage_key).unlink(missing_ok=True)
        except ValueError:
            pass
        db.delete(dv)
        db.flush()
        db.refresh(doc)
        if not doc.versions:
            db.delete(doc)


@router.delete("/responses/{response_id}")
def delete_response(response_id: int, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    r = db.get(InstitutionResponse, response_id)
    if not r:
        raise HTTPException(404, "Response not found")
    n = _notice_for_inst(db, user, r.item.notice_id)
    if r.status != "draft":
        raise HTTPException(409, "Submitted responses are part of the record and cannot be removed")
    _discard_draft(db, r)
    audit.record(db, "institution.response_discarded", "notice_item", r.notice_item_id, actor=user, application_id=n.application_id,
                 summary="Draft response discarded", ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/notices/{notice_id}/resubmit")
def resubmit(notice_id: int, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    n = _notice_for_inst(db, user, notice_id)
    if n.status != "issued":
        raise HTTPException(409, "This notice has already been responded to")
    drafts = {it.id: [r for r in it.responses if r.status == "draft"] for it in n.items}
    missing = [it.item_no for it in n.items if not drafts[it.id]]
    if missing:
        raise HTTPException(422, f"Respond to every item before resubmitting. Items without a response: {', '.join(map(str, missing))}")
    app = db.get(Application, n.application_id)
    new_v = app.current_version + 1
    sub = Submission(application_id=app.id, version=new_v, kind="resubmission", submitted_by_id=user.id, notice_id=n.id,
                     note=f"Response to {n.reference}")
    db.add(sub)
    db.flush()
    files = 0
    for it in n.items:
        for r in drafts[it.id]:
            r.status, r.submission_id = "submitted", sub.id
            if r.document_version:
                r.document_version.is_pending = False
                r.document_version.submission_version = new_v
                r.document_version.uploaded_at = utcnow()
                files += 1
        it.status = "responded"
    n.status = "responded"
    app.current_version = new_v
    app.status = "reverification"
    audit.record(db, "institution.resubmitted", "submission", sub.id, actor=user, application_id=app.id,
                 summary=f"{app.institution.name} resubmitted (v{new_v}) in response to {n.reference}: {len(n.items)} responses, {files} file(s)",
                 ip=client_ip(request))
    notify.to_officers(db, app, "response_received", f"Institution response received — {app.reference}",
                       f"{len(n.items)} item(s) answered; reverification started.", f"/reviewer/applications/{app.id}#notices")
    db.commit()
    engine.enqueue(db, app, "reverification", None)
    return {"submission_version": new_v, "status": app.status}


@router.get("/document-versions/{version_id}/file")
def own_file(version_id: int, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    dv = db.get(DocumentVersion, version_id)
    if not dv:
        raise HTTPException(404, "Not found")
    get_application_for_institution(dv.document.application_id, user, db)
    return Response(storage.read_bytes(dv.storage_key), media_type=dv.mime_type,
                    headers={"Content-Disposition": f'attachment; filename="{dv.original_filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/reports/{report_id}/download")
def report(report_id: int, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if not r or r.is_preview or r.kind not in ("deficiency_notice", "final_decision"):
        raise HTTPException(404, "Report not found")
    get_application_for_institution(r.application_id, user, db)
    if r.kind == "deficiency_notice":
        n = db.get(DeficiencyNotice, r.notice_id)
        if not n or n.status not in VISIBLE_NOTICE:
            raise HTTPException(404, "Report not found")
    audit.record(db, "report.downloaded", "report", r.id, actor=user, application_id=r.application_id, summary=f"Institution downloaded {r.reference}",
                 ip=client_ip(request))
    db.commit()
    return Response(storage.read_bytes(r.storage_key), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{r.reference}.pdf"', "X-Content-Type-Options": "nosniff"})


@router.get("/applications/{application_id}/history")
def history(application_id: int, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    a = get_application_for_institution(application_id, user, db)
    out = []
    for s in db.execute(select(Submission).where(Submission.application_id == a.id).order_by(Submission.version)).scalars():
        resp = db.execute(select(InstitutionResponse).where(InstitutionResponse.submission_id == s.id)).scalars().all()
        out.append({"version": s.version, "kind": s.kind, "submitted_at": serialize.iso(s.submitted_at), "note": s.note,
                    "notice_id": s.notice_id,
                    "responses": [{"item_no": r.item.item_no, "item_title": r.item.title, "text": r.response_text,
                                   "file": r.document_version.original_filename if r.document_version else None,
                                   "document_version_id": r.document_version_id, "item_status": r.item.status} for r in resp]})
    return {"application": _app_brief(a), "submissions": out}


# ------------------------------------------------------------------ creating and submitting applications


@router.get("/categories")
def categories(user: User = Depends(require_institution), db: Session = Depends(get_db)):
    """Application types with their own document checklists."""
    return [{"code": c.code, "name": c.name, "description": c.description,
             "checklist": [{"document_type": i.document_type, "label": i.label, "mandatory": i.mandatory, "guidance": i.guidance}
                           for i in c.checklist]}
            for c in db.execute(select(ApplicationCategory).where(ApplicationCategory.is_active).order_by(ApplicationCategory.id)).scalars()]


class ApplicationIn(BaseModel):
    category_code: str = Field(max_length=32)
    academic_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    declared_institution_name: str = Field(min_length=3, max_length=255)
    declared_permanent_id: str = Field(pattern=r"^\d-\d{6,12}$")
    declared_approved_intake: int = Field(ge=1, le=20000)


def _draft(db: Session, user: User, application_id: int) -> Application:
    a = get_application_for_institution(application_id, user, db)
    if a.status != "draft":
        raise HTTPException(409, "This application has been submitted; changes are made through notice responses")
    return a


@router.post("/applications", status_code=201)
def create_application(body: ApplicationIn, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    cat = db.execute(select(ApplicationCategory).where(ApplicationCategory.code == body.category_code, ApplicationCategory.is_active)).scalar_one_or_none()
    if not cat:
        raise HTTPException(422, "Choose a valid application type")
    dup = db.execute(select(Application).where(Application.institution_id == user.institution_id, Application.category_id == cat.id,
                                               Application.academic_year == body.academic_year)).scalars().first()
    if dup:
        raise HTTPException(409, f"You already have a {cat.name} application for {body.academic_year} ({dup.reference})")
    n = db.execute(select(func.count(Application.id))).scalar() or 0
    a = Application(reference=f"{cat.code}-{body.academic_year[:4]}-{n + 1:05d}", institution_id=user.institution_id, category_id=cat.id,
                    academic_year=body.academic_year, status="draft", created_by_id=user.id, is_synthetic=user.institution.is_synthetic,
                    declared={"institution_name": body.declared_institution_name.strip(), "permanent_id": body.declared_permanent_id,
                              "approved_intake": str(body.declared_approved_intake)},
                    scenario="Created by the institution in the portal")
    db.add(a)
    db.flush()
    audit.record(db, "application.created", "application", a.id, actor=user, application_id=a.id,
                 summary=f"Draft {a.reference} created by {user.institution.name}", ip=client_ip(request))
    db.commit()
    return _app_brief(a, db)


@router.patch("/applications/{application_id}")
def update_application(application_id: int, body: ApplicationIn, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    a = _draft(db, user, application_id)
    a.academic_year = body.academic_year
    a.declared = {"institution_name": body.declared_institution_name.strip(), "permanent_id": body.declared_permanent_id,
                  "approved_intake": str(body.declared_approved_intake)}
    audit.record(db, "application.updated", "application", a.id, actor=user, application_id=a.id, summary="Draft details updated", ip=client_ip(request))
    db.commit()
    return _app_brief(a, db)


@router.post("/applications/{application_id}/documents", status_code=201)
async def upload_document(application_id: int, request: Request, document_type: str = Form(...), file: UploadFile = File(...),
                          replace_document_id: int | None = Form(None), user: User = Depends(require_institution), db: Session = Depends(get_db)):
    a = _draft(db, user, application_id)
    allowed = {c.document_type: c for c in a.category.checklist}
    if document_type not in allowed:
        raise HTTPException(422, "This document type is not on the checklist for this application type")
    data, mime, name = await read_validated(file)
    if replace_document_id:
        doc = db.get(Document, replace_document_id)
        if not doc or doc.application_id != a.id:
            raise HTTPException(404, "Document not found")
    else:
        doc = Document(application_id=a.id, document_type=document_type, title=allowed[document_type].label)
        db.add(doc)
        db.flush()
    dv = add_version(db, doc, data, mime, name, user, 1)
    from ..services.processing import process_version

    process_version(db, dv)
    audit.record(db, "document.uploaded", "document", doc.id, actor=user, application_id=a.id,
                 summary=f"{'Replaced' if replace_document_id else 'Uploaded'} {doc.title} ({name})", details={"sha256": dv.sha256}, ip=client_ip(request))
    db.commit()
    return _inst_doc_rows(db, a)


@router.delete("/applications/{application_id}/documents/{document_id}")
def remove_document(application_id: int, document_id: int, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    """Drafts only: a document that was never submitted can be removed completely."""
    a = _draft(db, user, application_id)
    doc = db.get(Document, document_id)
    if not doc or doc.application_id != a.id:
        raise HTTPException(404, "Document not found")
    title = doc.title
    for v in list(doc.versions):
        for f in list(v.fields):
            db.delete(f)
        try:
            storage.path_for(v.storage_key).unlink(missing_ok=True)
        except ValueError:
            pass
        db.delete(v)
    db.flush()
    db.delete(doc)
    audit.record(db, "document.removed", "document", document_id, actor=user, application_id=a.id, summary=f"Removed {title} from draft", ip=client_ip(request))
    db.commit()
    db.refresh(a)
    return _inst_doc_rows(db, a)


@router.post("/applications/{application_id}/submit")
def submit_application(application_id: int, request: Request, user: User = Depends(require_institution), db: Session = Depends(get_db)):
    a = _draft(db, user, application_id)
    problems = []
    d = a.declared or {}
    for k, label in (("institution_name", "Institution name"), ("permanent_id", "AICTE permanent ID"), ("approved_intake", "Approved intake")):
        if not str(d.get(k, "")).strip():
            problems.append(f"{label} is required")
    rows = _inst_doc_rows(db, a)
    for m in rows["missing"]:
        problems.append(f"Upload the {m['document_type_label']}")
    for r in rows["documents"]:
        if r["status"] in ("unreadable", "invalid"):
            problems.append(f"{r['title']}: {r['status_label'].lower()} — replace or remove it")
    if problems:
        raise HTTPException(422, "The application cannot be submitted yet: " + "; ".join(problems))
    a.status = "submitted"
    a.submitted_at = utcnow()
    db.add(Submission(application_id=a.id, version=1, kind="initial", submitted_by_id=user.id, note="Submitted by the institution"))
    notify.to_officers(db, a, "application_submitted", f"New application — {a.reference}", f"{a.institution.name}, {a.category.name}",
                       f"/reviewer/applications/{a.id}")
    audit.record(db, "application.submitted", "application", a.id, actor=user, application_id=a.id,
                 summary=f"{a.reference} submitted with {len(rows['documents'])} documents", ip=client_ip(request))
    db.commit()
    return _app_brief(a, db)
