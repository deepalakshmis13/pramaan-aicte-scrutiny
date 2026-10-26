"""Scrutiny officer: dashboard, applications queue, single application view, CSV export."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, serialize
from ..db import get_db
from ..models import Application, ApplicationCategory, Decision, DeficiencyNotice, Finding, Submission, User, VerificationRun
from ..security import client_ip, get_application_for_reviewer, require_reviewer
from ..services import engine, review
from .common import OPEN_ISSUE, accessible_apps, has_filter, search_cond

router = APIRouter(prefix="/api/reviewer", tags=["officer"])


def _row(db: Session, a: Application, ref) -> dict:
    p = engine.priority(db, a, ref)
    d = serialize.application_brief(a, p)
    d["outstanding"] = p["open_issues"]
    d["next_action"] = review.next_action(db, a)["officer"]
    return d


def _apps(db: Session, user: User, status_: str | None, category: str | None, q: str | None, has: str | None):
    stmt = accessible_apps(user)
    if status_:
        stmt = stmt.where(Application.status.in_(status_.split(",")))
    if category:
        stmt = stmt.where(Application.category.has(ApplicationCategory.code == category))
    if q:
        stmt = stmt.where(search_cond(q))
    if has:
        cond = has_filter(has)
        if cond is not None:
            stmt = stmt.where(cond)
    return db.execute(stmt).scalars().all()


@router.get("/applications")
def list_applications(status_: str | None = Query(None, alias="status"), category: str | None = None, q: str | None = Query(None, max_length=100),
                      has: str | None = None, sort: str = "priority", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                      user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    ref = engine.reference_date(db)
    rows = [_row(db, a, ref) for a in _apps(db, user, status_, category, q, has)]
    keys = {"priority": lambda r: -r["priority"]["score"], "submitted_at": lambda r: r["submitted_at"], "reference": lambda r: r["reference"]}
    rows.sort(key=keys.get(sort, keys["priority"]))
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": len(rows), "page": page, "page_size": page_size}


@router.get("/applications/export.csv")
def export_csv(request: Request, status_: str | None = Query(None, alias="status"), category: str | None = None, q: str | None = None,
               user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    apps = _apps(db, user, status_, category, q, None)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reference", "institution", "permanent_id", "type", "academic_year", "stage", "submitted_at", "priority_level",
                "priority_score", "priority_reasons", "outstanding_findings", "action_required", "synthetic"])
    ref = engine.reference_date(db)
    for a in apps:
        r = _row(db, a, ref)
        w.writerow([a.reference, a.institution.name, a.institution.permanent_id, a.category.name, a.academic_year, r["status_label"],
                    a.submitted_at.date().isoformat(), r["priority"]["level"], r["priority"]["score"],
                    "; ".join(x["text"] for x in r["priority"]["reasons"]), r["outstanding"], r["next_action"], "yes" if a.is_synthetic else "no"])
    audit.record(db, "export.applications_csv", "application", "", actor=user, summary=f"Exported {len(apps)} applications to CSV", ip=client_ip(request))
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="applications.csv"'})


@router.get("/dashboard")
def dashboard(user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    apps = db.execute(accessible_apps(user)).scalars().all()
    ids = [a.id for a in apps] or [-1]
    by_status = dict(db.execute(select(Application.status, func.count()).where(Application.id.in_(ids)).group_by(Application.status)).all())
    manual_apps = db.execute(select(func.count(func.distinct(Finding.application_id))).where(
        Finding.application_id.in_(ids), OPEN_ISSUE, Finding.status.in_(["manual_review", "inconclusive"]))).scalar() or 0
    ref = engine.reference_date(db)
    ranked = sorted((_row(db, a, ref) for a in apps if a.status != "decided"), key=lambda r: -r["priority"]["score"])
    stages = [
        {"key": "submitted", "label": "Awaiting scrutiny", "value": by_status.get("submitted", 0) + by_status.get("under_scrutiny", 0),
         "link": "/reviewer/applications?status=submitted,under_scrutiny"},
        {"key": "manual", "label": "Need manual verification", "value": manual_apps, "link": "/reviewer/applications?has=manual_review"},
        {"key": "notice_issued", "label": "Awaiting institution response", "value": by_status.get("notice_issued", 0),
         "link": "/reviewer/applications?status=notice_issued"},
        {"key": "response", "label": "Responses to review", "value": by_status.get("response_received", 0) + by_status.get("reverification", 0),
         "link": "/reviewer/applications?status=response_received,reverification"},
        {"key": "awaiting_decision", "label": "Ready for decision", "value": by_status.get("awaiting_decision", 0),
         "link": "/reviewer/applications?status=awaiting_decision"},
        {"key": "decided", "label": "Decided", "value": by_status.get("decided", 0), "link": "/reviewer/applications?status=decided"},
    ]
    return {"reference_date": ref.isoformat(), "total": len(apps), "stages": stages, "priority_queue": ranked[:8]}


@router.get("/applications/{application_id}")
def application_detail(application_id: int, user: User = Depends(require_reviewer), db: Session = Depends(get_db)):
    app = get_application_for_reviewer(application_id, user, db)
    p = engine.priority(db, app)
    rows = review.document_rows(db, app)
    runs = db.execute(select(VerificationRun).where(VerificationRun.application_id == app.id).order_by(VerificationRun.id.desc())).scalars().all()
    notices = db.execute(select(DeficiencyNotice).where(DeficiencyNotice.application_id == app.id).order_by(DeficiencyNotice.id.desc())).scalars().all()
    subs = db.execute(select(Submission).where(Submission.application_id == app.id).order_by(Submission.version)).scalars().all()
    dec = db.execute(select(Decision).where(Decision.application_id == app.id).order_by(Decision.id.desc())).scalars().first()
    counts = dict(db.execute(select(Finding.status, func.count()).where(Finding.application_id == app.id, OPEN_ISSUE).group_by(Finding.status)).all())
    return {
        **serialize.application_brief(app, p),
        "declared": app.declared, "scenario": app.scenario, "row_version": app.row_version,
        "next_action": review.next_action(db, app, rows),
        "open_counts": counts,
        **rows,
        "runs": [serialize.run(r) for r in runs[:10]],
        "active_run": next((serialize.run(r) for r in runs if r.status in ("queued", "running")), None),
        "notices": [{"id": n.id, "reference": n.reference, "status": n.status, "items": len(n.items),
                     "issued_at": serialize.iso(n.issued_at), "response_deadline": serialize.iso(n.response_deadline)} for n in notices],
        "submissions": [{"version": s.version, "kind": s.kind, "submitted_at": serialize.iso(s.submitted_at), "note": s.note} for s in subs],
        "decision": {"id": dec.id, "outcome": dec.outcome, "decided_at": serialize.iso(dec.decided_at),
                     "decided_by": serialize.user_brief(dec.decided_by), "report_id": dec.report_id} if dec else None,
    }
