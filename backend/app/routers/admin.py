"""Administrator: users, rules (versioned), categories & checklists, verification sources, system status, audit.
Administrators manage configuration; they do not get access to application documents or reviewer workflows."""
from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import audit, serialize
from ..config import settings
from ..db import get_db
from ..enums import DOCUMENT_TYPES, ROLES
from ..models import (
    ApplicationCategory,
    AuditEvent,
    ChecklistItem,
    DocumentVersion,
    Institution,
    RegulatoryRule,
    RuleVersion,
    SystemConfig,
    User,
    VerificationRun,
    VerificationSource,
)
from ..security import client_ip, hash_password, require_admin
from ..services.checks.rules import CHECKS
from .reviewer_notices import audit_row

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------------ users


@router.get("/users")
def users(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [serialize.user(u) for u in db.execute(select(User).order_by(User.role, User.full_name)).scalars()]


@router.get("/institutions")
def institutions(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": i.id, "name": i.name, "permanent_id": i.permanent_id} for i in db.execute(select(Institution).order_by(Institution.name)).scalars()]


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    designation: str = Field(default="", max_length=128)
    role: str
    institution_id: int | None = None
    password: str = Field(min_length=10, max_length=128)


def _validate_role(role: str, institution_id: int | None, db: Session):
    if role not in ROLES:
        raise HTTPException(422, "Unknown role")
    if role == "institution":
        if not institution_id or not db.get(Institution, institution_id):
            raise HTTPException(422, "Institution users must be linked to an institution")
    elif institution_id:
        raise HTTPException(422, "Only institution users are linked to an institution")


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    _validate_role(body.role, body.institution_id, db)
    if db.execute(select(User).where(func.lower(User.email) == body.email.lower())).scalar_one_or_none():
        raise HTTPException(409, "A user with this email already exists")
    u = User(email=body.email.lower(), full_name=body.full_name.strip(), designation=body.designation.strip(), role=body.role,
             institution_id=body.institution_id, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    audit.record(db, "admin.user_created", "user", u.id, actor=user, summary=f"User {u.email} created ({u.role})", ip=client_ip(request))
    db.commit()
    return serialize.user(u)


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    designation: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None
    new_password: str | None = Field(default=None, min_length=10, max_length=128)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == user.id and body.is_active is False:
        raise HTTPException(409, "You cannot deactivate your own account")
    changes = {}
    for k in ("full_name", "designation", "is_active"):
        v = getattr(body, k)
        if v is not None and getattr(u, k) != v:
            changes[k] = {"from": getattr(u, k), "to": v}
            setattr(u, k, v)
    if body.new_password:
        u.password_hash = hash_password(body.new_password)
        changes["password"] = "reset"
    audit.record(db, "admin.user_updated", "user", u.id, actor=user, summary=f"User {u.email} updated", details={"changes": str(changes)}, ip=client_ip(request))
    db.commit()
    return serialize.user(u)


# ------------------------------------------------------------------ rules


@router.get("/rules")
def rules(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for r in db.execute(select(RegulatoryRule).order_by(RegulatoryRule.group, RegulatoryRule.code)).scalars():
        out.append({"id": r.id, "code": r.code, "title": r.title, "group": r.group, "current": serialize.rule_version(r.current),
                    "versions": [serialize.rule_version(v) for v in reversed(r.versions)]})
    return {"rules": out, "check_types": sorted(CHECKS)}


class RuleVersionIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)
    source_reference: str = Field(min_length=5, max_length=2000)
    source_verified: bool = False
    categories: list[str] = []
    check_type: str
    params: dict = {}
    severity: str = Field(pattern="^(high|medium|low)$")
    effective_from: date
    effective_to: date | None = None
    change_note: str = Field(min_length=5, max_length=2000)


class RuleIn(RuleVersionIn):
    code: str = Field(pattern=r"^[A-Z]{2,6}-\d{3}$")
    title: str = Field(min_length=5, max_length=255)
    group: str = Field(min_length=3, max_length=64)


def _check_rule(body: RuleVersionIn, db: Session):
    if body.check_type not in CHECKS:
        raise HTTPException(422, "Unknown check type")
    codes = {c.code for c in db.execute(select(ApplicationCategory)).scalars()}
    bad = [c for c in body.categories if c not in codes]
    if bad:
        raise HTTPException(422, f"Unknown categories: {', '.join(bad)}")
    if body.effective_to and body.effective_to < body.effective_from:
        raise HTTPException(422, "Effective-to must be after effective-from")
    if body.check_type == "field_consistency" and body.params.get("field") not in ("institution_name", "permanent_id"):
        raise HTTPException(422, "field_consistency requires params.field = institution_name or permanent_id")


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_rule(body, db)
    if db.execute(select(RegulatoryRule).where(RegulatoryRule.code == body.code)).scalar_one_or_none():
        raise HTTPException(409, "Rule code already exists")
    r = RegulatoryRule(code=body.code, title=body.title, group=body.group)
    db.add(r)
    db.flush()
    rv = RuleVersion(rule_id=r.id, version=1, created_by_id=user.id, **body.model_dump(exclude={"code", "title", "group"}))
    db.add(rv)
    audit.record(db, "rule.created", "rule", r.id, actor=user, summary=f"Rule {r.code} v1 created", details={"change_note": body.change_note}, ip=client_ip(request))
    db.commit()
    return {"id": r.id}


@router.post("/rules/{rule_id}/versions", status_code=201)
def new_version(rule_id: int, body: RuleVersionIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(RegulatoryRule, rule_id)
    if not r:
        raise HTTPException(404, "Rule not found")
    _check_rule(body, db)
    prev = r.current
    n = max((v.version for v in r.versions), default=0) + 1
    for v in r.versions:
        v.is_active = False  # earlier versions stay on record and remain linked to past findings
    rv = RuleVersion(rule_id=r.id, version=n, created_by_id=user.id, **body.model_dump())
    db.add(rv)
    audit.record(db, "rule.versioned", "rule", r.id, actor=user, summary=f"Rule {r.code} v{n} created (supersedes v{prev.version if prev else '-'})",
                 details={"change_note": body.change_note, "params": body.params, "severity": body.severity}, ip=client_ip(request))
    db.commit()
    return {"id": rv.id, "version": n}


class ActiveIn(BaseModel):
    active: bool
    reason: str = Field(min_length=5, max_length=500)


@router.post("/rules/{rule_id}/active")
def set_rule_active(rule_id: int, body: ActiveIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(RegulatoryRule, rule_id)
    if not r or not r.versions:
        raise HTTPException(404, "Rule not found")
    latest = r.versions[-1]
    latest.is_active = body.active
    audit.record(db, "rule.activated" if body.active else "rule.deactivated", "rule", r.id, actor=user,
                 summary=f"Rule {r.code} v{latest.version} {'activated' if body.active else 'deactivated'}", details={"reason": body.reason}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ categories & checklists


@router.get("/categories")
def categories(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for c in db.execute(select(ApplicationCategory).order_by(ApplicationCategory.id)).scalars():
        out.append({"id": c.id, "code": c.code, "name": c.name, "description": c.description, "is_active": c.is_active,
                    "checklist": [{"id": i.id, "document_type": i.document_type, "document_type_label": DOCUMENT_TYPES.get(i.document_type),
                                   "label": i.label, "mandatory": i.mandatory, "requires_validity": i.requires_validity,
                                   "guidance": i.guidance, "sort_order": i.sort_order} for i in c.checklist]})
    return {"categories": out, "document_types": DOCUMENT_TYPES}


class CategoryIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{2,10}$")
    name: str = Field(min_length=3, max_length=255)
    description: str = Field(default="", max_length=2000)


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.execute(select(ApplicationCategory).where(ApplicationCategory.code == body.code)).scalar_one_or_none():
        raise HTTPException(409, "Category code exists")
    c = ApplicationCategory(code=body.code, name=body.name, description=body.description)
    db.add(c)
    db.flush()
    audit.record(db, "category.created", "category", c.id, actor=user, summary=f"Category {c.code} created", ip=client_ip(request))
    db.commit()
    return {"id": c.id}


class ChecklistIn(BaseModel):
    document_type: str
    label: str = Field(min_length=3, max_length=255)
    mandatory: bool = True
    requires_validity: bool = False
    guidance: str = Field(default="", max_length=1000)


@router.post("/categories/{category_id}/checklist", status_code=201)
def add_item(category_id: int, body: ChecklistIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(ApplicationCategory, category_id)
    if not c:
        raise HTTPException(404, "Category not found")
    if body.document_type not in DOCUMENT_TYPES:
        raise HTTPException(422, "Unknown document type")
    if any(i.document_type == body.document_type for i in c.checklist):
        raise HTTPException(409, "This document type is already on the checklist")
    it = ChecklistItem(category_id=c.id, sort_order=len(c.checklist) + 1, **body.model_dump())
    db.add(it)
    audit.record(db, "checklist.item_added", "category", c.id, actor=user, summary=f"{c.code}: added '{body.label}'", ip=client_ip(request))
    db.commit()
    return {"ok": True}


class ChecklistPatch(BaseModel):
    label: str | None = Field(default=None, min_length=3, max_length=255)
    mandatory: bool | None = None
    requires_validity: bool | None = None
    guidance: str | None = Field(default=None, max_length=1000)


@router.patch("/checklist-items/{item_id}")
def update_item(item_id: int, body: ChecklistPatch, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    it = db.get(ChecklistItem, item_id)
    if not it:
        raise HTTPException(404, "Checklist item not found")
    ch = {}
    for k, v in body.model_dump(exclude_none=True).items():
        if getattr(it, k) != v:
            ch[k] = {"from": getattr(it, k), "to": v}
            setattr(it, k, v)
    audit.record(db, "checklist.item_updated", "checklist_item", it.id, actor=user, summary=f"Checklist item '{it.label}' updated",
                 details={"changes": str(ch)}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.delete("/checklist-items/{item_id}")
def delete_item(item_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    it = db.get(ChecklistItem, item_id)
    if not it:
        raise HTTPException(404, "Checklist item not found")
    audit.record(db, "checklist.item_removed", "checklist_item", it.id, actor=user,
                 summary=f"Checklist item '{it.label}' removed (affects future verification runs only)", ip=client_ip(request))
    db.delete(it)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ sources


@router.get("/sources")
def sources(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for s in db.execute(select(VerificationSource).order_by(VerificationSource.id)).scalars():
        creds = {"scopus": bool(settings.scopus_api_key), "crossref": True, "aicte_records": False}.get(s.code, False)
        out.append({"id": s.id, "code": s.code, "name": s.name, "source_type": s.source_type, "claim_types": s.claim_types, "mode": s.mode,
                    "base_url": s.base_url, "requires_credentials": s.requires_credentials, "credentials_configured": creds,
                    "rate_limit_per_minute": s.rate_limit_per_minute, "timeout_seconds": s.timeout_seconds, "notes": s.notes,
                    "updated_at": serialize.iso(s.updated_at)})
    return out


class SourcePatch(BaseModel):
    mode: str | None = Field(default=None, pattern="^(live|simulated|disabled)$")
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=600)
    timeout_seconds: float | None = Field(default=None, ge=1, le=60)


@router.patch("/sources/{code}")
def update_source(code: str, body: SourcePatch, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.execute(select(VerificationSource).where(VerificationSource.code == code)).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Source not found")
    if code == "aicte_records" and body.mode == "live":
        raise HTTPException(422, "No authorised AICTE records integration exists in this prototype")
    if code == "scopus" and body.mode == "simulated":
        raise HTTPException(422, "Indexing claims cannot be simulated; use live (with credentials) or disabled")
    ch = {}
    for k, v in body.model_dump(exclude_none=True).items():
        if getattr(s, k) != v:
            ch[k] = {"from": getattr(s, k), "to": v}
            setattr(s, k, v)
    audit.record(db, "source.updated", "verification_source", s.id, actor=user, summary=f"Source {s.name} updated", details={"changes": str(ch)}, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/sources/{code}/test")
def test_source(code: str, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from ..services.connectors import crossref, scopus

    s = db.execute(select(VerificationSource).where(VerificationSource.code == code)).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Source not found")
    if code == "crossref":
        res = crossref.check_publication({"doi": "10.1038/nature14539", "title": "Deep learning", "authors": "Y. LeCun, Y. Bengio, G. Hinton", "year": "2015"},
                                         s.mode, timeout=s.timeout_seconds)
    elif code == "scopus":
        res = scopus.check_indexing({"doi": "10.1038/nature14539", "title": "Deep learning"}, s.mode)
    else:
        from ..services.connectors import aicte_records

        res = aicte_records.check_previous_approval({})
    audit.record(db, "source.tested", "verification_source", s.id, actor=user, summary=f"Connectivity test for {s.name}: {res.status} ({res.mode})", ip=client_ip(request))
    db.commit()
    return {"status": res.status, "mode": res.mode, "http_status": res.http_status, "explanation": res.explanation, "duration_ms": res.duration_ms, "query": res.query}


# ------------------------------------------------------------------ system


@router.get("/system")
def system(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from ..services import extraction

    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    try:
        import pytesseract

        tver = str(pytesseract.get_tesseract_version())
    except Exception as e:
        tver = f"unavailable ({type(e).__name__})"
    du = shutil.disk_usage(settings.storage_dir)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    failed_runs = db.execute(select(VerificationRun).where(VerificationRun.status == "failed").order_by(VerificationRun.id.desc()).limit(10)).scalars().all()
    failed_docs = db.execute(select(DocumentVersion).where(DocumentVersion.processing_status == "failed").limit(20)).scalars().all()
    active = db.execute(select(func.count(VerificationRun.id)).where(VerificationRun.status.in_(["queued", "running"]))).scalar()
    cfg = {c.key: {"value": c.value.get("value"), "description": c.description, "updated_at": serialize.iso(c.updated_at)}
           for c in db.execute(select(SystemConfig)).scalars()}
    return {
        "checks": [
            {"name": "Database", "ok": db_ok, "detail": "PostgreSQL reachable" if db_ok else "Database query failed"},
            {"name": "OCR engine", "ok": extraction.TESSERACT_AVAILABLE and not tver.startswith("unavailable"), "detail": f"Tesseract {tver}"},
            {"name": "Document storage", "ok": settings.storage_dir.exists(), "detail": f"{round(du.free / 1e9, 1)} GB free"},
            {"name": "Secret key", "ok": not settings.secret_key.startswith("dev-only"), "detail": "Configured" if not settings.secret_key.startswith("dev-only") else "Development fallback key in use — set SECRET_KEY"},
            {"name": "Scopus credentials", "ok": bool(settings.scopus_api_key), "detail": "Configured" if settings.scopus_api_key else "Not configured — indexing claims go to manual review"},
            {"name": "Job worker", "ok": True, "detail": f"Mode '{settings.jobs_mode}'; {active} run(s) queued or running"},
        ],
        "failed_runs": [serialize.run(r) for r in failed_runs],
        "failed_documents": [{"id": d.id, "document_id": d.document_id, "filename": d.original_filename, "error": d.processing_error} for d in failed_docs],
        "recent_activity": db.execute(select(func.count(AuditEvent.id)).where(AuditEvent.created_at >= since)).scalar(),
        "audit_chain": audit.verify_chain(db),
        "config": cfg,
        "environment": settings.env,
    }


class ConfigPatch(BaseModel):
    key: str = Field(pattern="^(ocr_confirmation_threshold|expiry_reference_date|notice_response_days)$")
    value: str = Field(max_length=32)


@router.patch("/config")
def set_config(body: ConfigPatch, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.key == "ocr_confirmation_threshold":
        v = float(body.value)
        if not 0 <= v <= 100:
            raise HTTPException(422, "Threshold must be 0–100")
        val = v
    elif body.key == "notice_response_days":
        val = int(body.value)
        if not 1 <= val <= 120:
            raise HTTPException(422, "Response window must be 1–120 days")
    else:
        if body.value:
            try:
                date.fromisoformat(body.value)
            except ValueError:
                raise HTTPException(422, "Use YYYY-MM-DD, or empty for today")
        val = body.value
    c = db.get(SystemConfig, body.key)
    old = c.value.get("value") if c else None
    if c:
        c.value, c.updated_by_id = {"value": val}, user.id
    else:
        db.add(SystemConfig(key=body.key, value={"value": val}, updated_by_id=user.id))
    audit.record(db, "config.updated", "system_config", body.key, actor=user, summary=f"{body.key}: {old} → {val}", ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/audit")
def admin_audit(action: str | None = None, actor: str | None = None, q: str | None = Query(None, max_length=100),
                application_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if actor:
        stmt = stmt.where(AuditEvent.actor_label.ilike(f"%{actor}%"))
    if application_id:
        stmt = stmt.where(AuditEvent.application_id == application_id)
    if q:
        stmt = stmt.where(AuditEvent.summary.ilike(f"%{q}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.execute(stmt.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [audit_row(db, e) for e in rows]}
