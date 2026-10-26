"""Reviewer: verification runs, findings & evidence, source checks, compliance, evidence graph, passport, notes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, serialize
from ..db import get_db
from ..enums import RESULT_STATES
from ..models import (
    AuditEvent,
    DeficiencyNotice,
    Document,
    DocumentVersion,
    Finding,
    FindingEvent,
    InstitutionResponse,
    NoticeItem,
    ReviewerNote,
    SourceCheck,
    Submission,
    User,
    VerificationRun,
)
from ..security import client_ip, get_application_for_reviewer, require_reviewer
from ..services import engine

router = APIRouter(prefix="/api/reviewer", tags=["reviewer-verification"])


@router.post("/applications/{application_id}/verify", status_code=202)
def run_verification(application_id: int, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    if app.status == "decided":
        raise HTTPException(409, "A decision has been recorded; verification is closed")
    if not any(d.current for d in app.documents):
        raise HTTPException(409, "The application has no documents to verify")
    kind = "reverification" if app.status in ("response_received", "reverification") else ("initial" if app.status == "submitted" else "manual")
    if app.assigned_reviewer_id is None:
        app.assigned_reviewer_id = user.id
    audit.record(db, "verification.requested", "application", app.id, actor=user, application_id=app.id,
                 summary=f"Verification ({kind}) requested", ip=client_ip(request))
    db.commit()
    run = engine.enqueue(db, app, kind, user.id)
    return serialize.run(run)


@router.get("/applications/{application_id}/runs")
def runs(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    get_application_for_reviewer(application_id, user, db)
    return [serialize.run(r) for r in db.execute(select(VerificationRun).where(VerificationRun.application_id == application_id)
                                                  .order_by(VerificationRun.id.desc())).scalars()]


@router.get("/runs/{run_id}")
def run_detail(run_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    r = db.get(VerificationRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    get_application_for_reviewer(r.application_id, user, db)
    return serialize.run(r)


@router.get("/applications/{application_id}/findings")
def findings(application_id: int, category: str | None = None, status: str | None = None, issues_only: bool = False,
             review_state: str | None = None, q: str | None = Query(None, max_length=100),
             user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    get_application_for_reviewer(application_id, user, db)
    stmt = select(Finding).where(Finding.application_id == application_id)
    if category:
        stmt = stmt.where(Finding.category.in_(category.split(",")))
    if status:
        stmt = stmt.where(Finding.status.in_(status.split(",")))
    if issues_only:
        stmt = stmt.where(Finding.is_issue.is_(True))
    if review_state:
        stmt = stmt.where(Finding.review_state == review_state)
    if q:
        stmt = stmt.where(Finding.title.ilike(f"%{q}%") | Finding.code.ilike(f"%{q}%"))
    sev = {"high": 0, "medium": 1, "low": 2}
    rows = db.execute(stmt).scalars().all()
    rows.sort(key=lambda f: (not f.is_issue, f.status in ("verified", "resolved"), sev.get(f.severity, 3), f.id))
    return [serialize.finding(f, full=True) for f in rows]


def _get_finding(db: Session, user: User, finding_id: int) -> Finding:
    f = db.get(Finding, finding_id)
    if not f:
        raise HTTPException(404, "Finding not found")
    get_application_for_reviewer(f.application_id, user, db)
    return f


def _dv_info(db: Session, dv_id: int | None) -> dict | None:
    if not dv_id:
        return None
    dv = db.get(DocumentVersion, dv_id)
    d = db.get(Document, dv.document_id)
    return {"document_id": d.id, "document_title": d.title, "document_type": d.document_type, "version_id": dv.id,
            "version_no": dv.version_no, "page_count": dv.page_count, "mime_type": dv.mime_type,
            "is_current": d.current.id == dv.id if d.current else False}


@router.get("/findings/{finding_id}")
def finding_detail(finding_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    f = _get_finding(db, user, finding_id)
    events = db.execute(select(FindingEvent).where(FindingEvent.finding_id == f.id).order_by(FindingEvent.id)).scalars().all()
    notes = db.execute(select(ReviewerNote).where(ReviewerNote.finding_id == f.id).order_by(ReviewerNote.id)).scalars().all()
    items = db.execute(select(NoticeItem).where(NoticeItem.finding_id == f.id)).scalars().all()
    return {
        **serialize.finding(f, full=True),
        "document": _dv_info(db, f.document_version_id), "related_document": _dv_info(db, f.related_document_version_id),
        "events": [serialize.finding_event(e, db.get(User, e.actor_id) if e.actor_id else None) for e in events],
        "notes": [{"id": n.id, "body": n.body, "author": serialize.user_brief(n.author), "created_at": serialize.iso(n.created_at)} for n in notes],
        "notice_items": [{"id": i.id, "notice_id": i.notice_id, "notice_reference": i.notice.reference, "item_no": i.item_no,
                          "status": i.status, "notice_status": i.notice.status} for i in items],
    }


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(confirm|dismiss|resolve|escalate|reopen)$")
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/findings/{finding_id}/review")
def review_finding(finding_id: int, body: ReviewIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    f = _get_finding(db, user, finding_id)
    app = f.application_id
    before = (f.status, f.review_state)
    if body.action == "confirm":
        f.review_state = "confirmed"
    elif body.action == "dismiss":
        if f.in_notice and f.status not in ("resolved",):
            raise HTTPException(409, "This finding is part of an issued notice; record the outcome on the notice item instead")
        f.review_state = "dismissed"
    elif body.action == "resolve":
        if f.latest_result not in ("verified", "resolved") and len(body.reason.strip()) < 15:
            raise HTTPException(422, "The latest automated check does not pass. Give a justification of at least 15 characters to resolve manually.")
        f.status = "resolved"
        f.review_state = "confirmed"
    elif body.action == "escalate":
        f.status = "escalated"
    elif body.action == "reopen":
        f.status = f.latest_result if f.latest_result not in ("", "not_reevaluated") else "manual_review"
        f.review_state = "unreviewed"
    f.review_reason = body.reason.strip()
    f.reviewed_by_id = user.id
    db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action=body.action, from_status=before[0], to_status=f.status,
                        detail=body.reason.strip()))
    audit.record(db, f"finding.{body.action}", "finding", f.id, actor=user, application_id=app,
                 summary=f"{f.code} {body.action}: {f.title}", details={"reason": body.reason, "from": before[0], "to": f.status},
                 ip=client_ip(request))
    db.commit()
    return serialize.finding(f, full=True)


class ManualFindingIn(BaseModel):
    title: str = Field(min_length=5, max_length=255)
    reason: str = Field(min_length=10, max_length=4000)
    severity: str = Field(pattern="^(high|medium|low)$")
    document_version_id: int | None = None
    recommended_action: str = Field(default="", max_length=2000)
    institution_text: str = Field(default="", max_length=2000)


@router.post("/applications/{application_id}/findings", status_code=201)
def manual_finding(application_id: int, body: ManualFindingIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    ev = []
    dtype = ""
    if body.document_version_id:
        dv = db.get(DocumentVersion, body.document_version_id)
        if not dv or dv.document.application_id != app.id:
            raise HTTPException(400, "Document version is not part of this application")
        ev = [{"type": "document", "document_id": dv.document_id, "document_version_id": dv.id, "version_no": dv.version_no,
               "document_title": dv.document.title, "note": "Cited by reviewer"}]
        dtype = dv.document.document_type
    n = db.execute(select(Finding.id).where(Finding.application_id == app.id)).scalars().all()
    import uuid

    f = Finding(application_id=app.id, fingerprint=f"manual:{uuid.uuid4().hex[:12]}", code=f"F-{app.id:03d}-{len(n) + 1:03d}",
                category="manual", title=body.title, document_version_id=body.document_version_id, document_type=dtype,
                reason=body.reason, evidence=ev, certainty="confirmed", origin="manual", severity=body.severity,
                status="manual_review", latest_result="manual_review", is_issue=True, review_state="confirmed",
                reviewed_by_id=user.id, recommended_action=body.recommended_action,
                institution_text=body.institution_text or body.reason, method="Reviewer observation")
    db.add(f)
    db.flush()
    db.add(FindingEvent(finding_id=f.id, actor_id=user.id, action="created", to_status="manual_review", detail="Recorded by reviewer"))
    audit.record(db, "finding.manual_created", "finding", f.id, actor=user, application_id=app.id, summary=f"{f.code} recorded: {f.title}", ip=client_ip(request))
    db.commit()
    return serialize.finding(f, full=True)


@router.get("/applications/{application_id}/source-checks")
def source_checks(application_id: int, run_id: int | None = None, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    get_application_for_reviewer(application_id, user, db)
    stmt = select(SourceCheck).where(SourceCheck.application_id == application_id)
    if run_id:
        stmt = stmt.where(SourceCheck.run_id == run_id)
    return [serialize.source_check(c) for c in db.execute(stmt.order_by(SourceCheck.id.desc())).scalars()]


@router.get("/applications/{application_id}/evidence-graph")
def evidence_graph(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    fs = {f.fingerprint: f for f in db.execute(select(Finding).where(Finding.application_id == app.id)).scalars()}

    def st(fp: str):
        f = fs.get(fp)
        return (f.status, f.id) if f else ("unchecked", None)

    nodes["form"] = {"id": "form", "kind": "form", "label": "Application form", "sub": app.reference}
    for d in app.documents:
        if d.current:
            nodes[f"doc{d.id}"] = {"id": f"doc{d.id}", "kind": "document", "label": d.title, "sub": f"DOC-{d.id} v{d.current.version_no}",
                                   "document_id": d.id, "document_type": d.document_type}
    nodes["ent:inst"] = {"id": "ent:inst", "kind": "institution", "label": app.institution.name, "sub": "Institution"}
    edges.append({"source": "ent:inst", "target": "form", "label": "declared name", "value": app.declared.get("institution_name", ""), "state": "declared"})
    for d in app.documents:
        v = d.current
        if not v:
            continue
        for f in v.fields:
            if f.field_name == "institution_name":
                s, fid = st(f"xdoc:institution_name:doc{d.id}")
                edges.append({"source": "ent:inst", "target": f"doc{d.id}", "label": "name on document", "value": f.effective_value, "state": s, "finding_id": fid})
                break
        if d.document_type == "faculty_list":
            groups: dict[str, dict] = {}
            for f in v.fields:
                if f.field_name.startswith("faculty_"):
                    groups.setdefault(f.group_key, {})[f.field_name] = f.effective_value
            for fid_, g in groups.items():
                nid = f"ent:fac:{fid_}"
                nodes[nid] = {"id": nid, "kind": "faculty", "label": g.get("faculty_name", fid_), "sub": fid_}
                s, fnd = st(f"faculty:{fid_}")
                edges.append({"source": nid, "target": f"doc{d.id}", "label": "listed with", "value": g.get("faculty_qualification", ""), "state": "claim"})
                f = fs.get(f"faculty:{fid_}")
                if f and f.related_document_version_id:
                    rdv = db.get(DocumentVersion, f.related_document_version_id)
                    edges.append({"source": nid, "target": f"doc{rdv.document_id}", "label": "certificate shows", "value": f.expected_value, "state": s, "finding_id": fnd})
                elif f:
                    edges.append({"source": nid, "target": "gap:" + nid, "label": "certificate", "value": "not submitted", "state": s, "finding_id": fnd})
                    nodes["gap:" + nid] = {"id": "gap:" + nid, "kind": "gap", "label": "No certificate", "sub": "missing evidence"}
        if d.document_type == "publication_list":
            groups = {}
            for f in v.fields:
                if f.field_name.startswith("pub_"):
                    groups.setdefault(f.group_key, {})[f.field_name] = f.effective_value
            for gk, g in groups.items():
                doi = (g.get("pub_doi") or gk).lower()
                nid = f"ent:pub:{doi}"
                nodes[nid] = {"id": nid, "kind": "publication", "label": (g.get("pub_title", "")[:60] or doi), "sub": doi}
                edges.append({"source": nid, "target": f"doc{d.id}", "label": "claimed in", "value": g.get("pub_indexing", ""), "state": "claim"})
                s, fnd = st(f"pubmeta:{doi}")
                nodes["src:crossref"] = {"id": "src:crossref", "kind": "source", "label": "Crossref", "sub": "publication metadata"}
                edges.append({"source": nid, "target": "src:crossref", "label": "metadata", "value": RESULT_STATES.get(s, s), "state": s, "finding_id": fnd})
                if "scopus" in (g.get("pub_indexing", "").lower()):
                    s2, fnd2 = st(f"pubindex:{doi}")
                    nodes["src:scopus"] = {"id": "src:scopus", "kind": "source", "label": "Scopus", "sub": "indexing"}
                    edges.append({"source": nid, "target": "src:scopus", "label": "indexing", "value": RESULT_STATES.get(s2, s2), "state": s2, "finding_id": fnd2})
        if d.document_type == "infrastructure_photo":
            for f in v.fields:
                if f.field_name == "room_label":
                    nid = f"ent:room:{f.effective_value}"
                    nodes[nid] = {"id": nid, "kind": "room", "label": f.effective_value, "sub": "facility"}
                    s, fnd = st(f"infra:room:doc{d.id}")
                    edges.append({"source": nid, "target": f"doc{d.id}", "label": "photo label", "value": f.effective_value, "state": s, "finding_id": fnd})
                    for pd in app.documents:
                        if pd.document_type == "floor_plan" and pd.current:
                            if any(x.field_name == "floor_room" and x.effective_value == f.effective_value for x in pd.current.fields):
                                edges.append({"source": nid, "target": f"doc{pd.id}", "label": "on floor plan", "value": f.effective_value, "state": "claim"})
        if d.document_type in ("previous_approval", "fire_safety_certificate", "noc", "accreditation_certificate", "registration_certificate"):
            num = next((f.effective_value for f in v.fields if f.field_name == "certificate_number"), None)
            if num:
                nid = f"ent:cert:{d.id}"
                nodes[nid] = {"id": nid, "kind": "certificate", "label": num, "sub": d.document_type.replace("_", " ")}
                s, fnd = st(f"validity:doc{d.id}")
                edges.append({"source": nid, "target": f"doc{d.id}", "label": "validity", "value": RESULT_STATES.get(s, "recorded") if s != "unchecked" else "recorded", "state": s if s != "unchecked" else "claim", "finding_id": fnd})
    for fp, f in fs.items():
        if fp.startswith("dup:") and f.is_issue:
            a, b = fp[4:].split("-")
            if a in nodes and b in nodes:
                edges.append({"source": a, "target": b, "label": "duplicate", "value": f.method, "state": "manual_review", "finding_id": f.id})
    used = {e["source"] for e in edges} | {e["target"] for e in edges}
    return {"nodes": [n for k, n in nodes.items() if k in used or n["kind"] == "document"], "edges": edges,
            "note": "Built only from extracted fields and recorded findings. Edges marked 'claim' are statements in a document, not verified facts."}


@router.get("/applications/{application_id}/passport")
def passport(application_id: int, kind: str | None = None, q: str | None = Query(None, max_length=100),
             user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    ev: list[dict] = []
    for s in db.execute(select(Submission).where(Submission.application_id == app.id)).scalars():
        ev.append({"at": serialize.iso(s.submitted_at), "kind": "submission", "title": f"Submission v{s.version} ({s.kind})", "detail": s.note,
                   "link": f"/reviewer/applications/{app.id}"})
    for d in app.documents:
        for v in d.versions:
            if v.is_pending:
                continue
            ev.append({"at": serialize.iso(v.uploaded_at), "kind": "document", "title": f"{d.title} — version {v.version_no}",
                       "detail": f"{v.original_filename} · SHA-256 {v.sha256[:16]}… · {v.processing_status} ({v.text_method or 'n/a'})",
                       "link": f"/reviewer/applications/{app.id}/documents/{d.id}?version={v.version_no}"})
    for r in db.execute(select(VerificationRun).where(VerificationRun.application_id == app.id)).scalars():
        ev.append({"at": serialize.iso(r.finished_at or r.created_at), "kind": "run", "title": f"Verification run #{r.id} ({r.kind}) — {r.status}",
                   "detail": "Rules applied: " + ", ".join(f"{k} v{v}" for k, v in (r.rule_versions or {}).items()) if r.rule_versions else r.error,
                   "summary": r.summary, "link": f"/reviewer/applications/{app.id}/verification?run={r.id}"})
    for c in db.execute(select(SourceCheck).where(SourceCheck.application_id == app.id)).scalars():
        ev.append({"at": serialize.iso(c.checked_at), "kind": "source", "title": f"{c.source_name} [{c.mode}] → {RESULT_STATES.get(c.status, c.status)}",
                   "detail": f"{c.claim_type}: {c.query}", "link": f"/reviewer/applications/{app.id}/verification?check={c.id}"})
    fids = {f.id: f for f in db.execute(select(Finding).where(Finding.application_id == app.id)).scalars()}
    for e in db.execute(select(FindingEvent).where(FindingEvent.finding_id.in_(list(fids) or [-1]))).scalars():
        f = fids[e.finding_id]
        actor = db.get(User, e.actor_id) if e.actor_id else None
        ev.append({"at": serialize.iso(e.created_at), "kind": "finding" if not actor else "review",
                   "title": f"{f.code} {e.action.replace('_', ' ')}" + (f" → {RESULT_STATES.get(e.to_status, e.to_status)}" if e.to_status else ""),
                   "detail": f"{f.title}. {e.detail}", "actor": actor.full_name if actor else "system",
                   "link": f"/reviewer/applications/{app.id}/findings/{f.id}"})
    for n in db.execute(select(ReviewerNote).where(ReviewerNote.application_id == app.id)).scalars():
        ev.append({"at": serialize.iso(n.created_at), "kind": "note", "title": "Reviewer observation (internal)", "detail": n.body,
                   "actor": n.author.full_name, "link": f"/reviewer/applications/{app.id}/notes"})
    for a in db.execute(select(AuditEvent).where(AuditEvent.application_id == app.id, AuditEvent.action.in_(
            ["field.confirmed", "notice.created", "notice.submitted", "notice.approved", "notice.returned", "notice.issued",
             "institution.resubmitted", "notice_item.outcome", "decision.recorded", "application.ready_for_decision", "report.generated"]))).scalars():
        ev.append({"at": serialize.iso(a.created_at), "kind": a.action.split(".")[0] if a.action.split(".")[0] in ("notice", "decision", "report") else "action",
                   "title": a.summary, "detail": f"Audit event #{a.id}", "actor": a.actor_label, "link": None, "audit_hash": a.hash[:12]})
    for r in db.execute(select(InstitutionResponse).join(NoticeItem).join(DeficiencyNotice).where(
            DeficiencyNotice.application_id == app.id, InstitutionResponse.status == "submitted")).scalars():
        ev.append({"at": serialize.iso(r.updated_at), "kind": "response", "title": f"Institution response to item {r.item.item_no} ({r.item.notice.reference})",
                   "detail": r.response_text[:300], "link": f"/reviewer/applications/{app.id}/responses"})
    if kind:
        ev = [e for e in ev if e["kind"] in kind.split(",")]
    if q:
        ql = q.lower()
        ev = [e for e in ev if ql in (e["title"] + " " + (e.get("detail") or "")).lower()]
    ev.sort(key=lambda e: e["at"] or "", reverse=True)
    return {"application": serialize.application_brief(app), "events": ev,
            "integrity": "Audit-backed events include the first 12 characters of their chained SHA-256 hash."}


class NoteIn(BaseModel):
    body: str = Field(min_length=2, max_length=4000)
    finding_id: int | None = None
    document_id: int | None = None


@router.get("/applications/{application_id}/notes")
def notes(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    get_application_for_reviewer(application_id, user, db)
    out = []
    for n in db.execute(select(ReviewerNote).where(ReviewerNote.application_id == application_id).order_by(ReviewerNote.id.desc())).scalars():
        f = db.get(Finding, n.finding_id) if n.finding_id else None
        d = db.get(Document, n.document_id) if n.document_id else None
        out.append({"id": n.id, "body": n.body, "author": serialize.user_brief(n.author), "created_at": serialize.iso(n.created_at),
                    "finding": {"id": f.id, "code": f.code, "title": f.title} if f else None,
                    "document": {"id": d.id, "title": d.title} if d else None})
    return out


@router.post("/applications/{application_id}/notes", status_code=201)
def add_note(application_id: int, body: NoteIn, request: Request, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    if body.finding_id:
        f = db.get(Finding, body.finding_id)
        if not f or f.application_id != app.id:
            raise HTTPException(400, "Finding not in this application")
    if body.document_id:
        d = db.get(Document, body.document_id)
        if not d or d.application_id != app.id:
            raise HTTPException(400, "Document not in this application")
    n = ReviewerNote(application_id=app.id, finding_id=body.finding_id, document_id=body.document_id, author_id=user.id, body=body.body.strip())
    db.add(n)
    db.flush()
    audit.record(db, "note.added", "reviewer_note", n.id, actor=user, application_id=app.id, summary="Internal observation recorded", ip=client_ip(request))
    db.commit()
    return {"id": n.id}
