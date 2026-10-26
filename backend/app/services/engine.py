"""Verification run orchestration and finding persistence.

Findings are upserted by a stable fingerprint so that reverification updates the
same claim-level record and appends FindingEvents instead of overwriting history.
Official status changes to Resolved/Escalated happen only via reviewer action;
the engine records its latest automated result separately in `latest_result`.
"""
from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import SessionLocal
from ..models import (
    Application,
    Document,
    Finding,
    FindingEvent,
    RegulatoryRule,
    RuleVersion,
    SystemConfig,
    VerificationRun,
    VerificationSource,
    utcnow,
)
from . import notify
from .checks.context import Ctx, Outcome
from .checks.rules import CHECKS
from .processing import process_version

log = logging.getLogger("pramaan.engine")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="verify")

ORDER = [
    "checklist_completeness", "extraction_quality", "required_fields", "validity", "field_consistency",
    "intake_consistency", "faculty_qualification", "publication_metadata", "publication_indexing",
    "duplicates", "document_anomaly", "infrastructure_evidence",
]


def reference_date(db: Session) -> date:
    if settings.expiry_reference_date:
        return date.fromisoformat(settings.expiry_reference_date)
    cfg = db.get(SystemConfig, "expiry_reference_date")
    if cfg and (cfg.value or {}).get("value"):
        return date.fromisoformat(cfg.value["value"])
    return date.today()


def applicable_rules(db: Session, app: Application, on: date) -> list[RuleVersion]:
    out = []
    for rule in db.execute(select(RegulatoryRule)).scalars():
        rv = rule.current
        if not rv:
            continue
        if rv.categories and app.category.code not in rv.categories:
            continue
        if rv.effective_from > on or (rv.effective_to and rv.effective_to < on):
            continue
        out.append(rv)
    return sorted(out, key=lambda r: (ORDER.index(r.check_type) if r.check_type in ORDER else 99, r.rule.code))


def _next_code(db: Session, app: Application) -> str:
    n = db.execute(select(func.count(Finding.id)).where(Finding.application_id == app.id)).scalar() or 0
    return f"F-{app.id:03d}-{n + 1:03d}"


def _upsert(db: Session, app: Application, run: VerificationRun, rv: RuleVersion, o: Outcome) -> tuple[Finding, str]:
    f = db.execute(
        select(Finding).where(Finding.application_id == app.id, Finding.fingerprint == o.fingerprint)
    ).scalar_one_or_none()
    payload = dict(
        category=o.category, title=o.title, document_version_id=o.document_version_id,
        related_document_version_id=o.related_document_version_id, document_type=o.document_type, field=o.field,
        extracted_value=o.extracted_value[:4000], expected_value=o.expected_value[:4000], method=o.method,
        rule_version_id=rv.id, source_check_id=o.source_check_id, reason=o.reason, limitations=o.limitations,
        evidence=o.evidence, certainty=o.certainty, confidence_note=o.confidence_note, severity=o.severity,
        recommended_action=o.recommended_action, institution_text=o.institution_text,
    )
    if f is None:
        f = Finding(application_id=app.id, fingerprint=o.fingerprint, code=_next_code(db, app), first_run_id=run.id,
                    last_run_id=run.id, status=o.status, latest_result=o.status, is_issue=o.is_issue, origin="automated", **payload)
        db.add(f)
        db.flush()
        db.add(FindingEvent(finding_id=f.id, run_id=run.id, action="created", to_status=o.status,
                            detail=f"Run #{run.id}: {o.reason[:300]}"))
        return f, "new"
    prev_result = f.latest_result
    for k, v in payload.items():
        setattr(f, k, v)
    f.last_run_id = run.id
    f.latest_result = o.status
    change = "unchanged"
    if f.status in ("resolved", "escalated"):
        # official status is held by reviewer action; record the new automated result only
        if prev_result != o.status:
            db.add(FindingEvent(finding_id=f.id, run_id=run.id, action="reverified", from_status=prev_result, to_status=o.status,
                                detail=f"Run #{run.id}: automated result now '{o.status}'. Official status '{f.status}' unchanged."))
            change = "changed"
    elif f.in_notice and f.is_issue and not o.is_issue:
        # Issue raised in a notice now passes: keep official status until reviewer confirms closure.
        db.add(FindingEvent(finding_id=f.id, run_id=run.id, action="reverified", from_status=prev_result, to_status=o.status,
                            detail=f"Run #{run.id}: check now passes on new evidence. Awaiting reviewer confirmation to resolve."))
        change = "passes_now"
    else:
        if f.status != o.status:
            db.add(FindingEvent(finding_id=f.id, run_id=run.id, action="status_changed", from_status=f.status, to_status=o.status,
                                detail=f"Run #{run.id}: {o.reason[:300]}"))
            change = "changed"
        f.status = o.status
        if o.is_issue:
            f.is_issue = True
            if f.review_state == "dismissed" and prev_result != o.status:
                f.review_state = "unreviewed"
        # A passing result keeps is_issue as recorded (history); status 'verified' removes it from open work.
    return f, change


def execute_run(db: Session, run: VerificationRun) -> VerificationRun:
    app = db.get(Application, run.application_id)
    run.status, run.started_at, run.stage = "running", utcnow(), "extraction"
    db.commit()
    try:
        docs = []
        for d in db.execute(select(Document).where(Document.application_id == app.id).order_by(Document.id)).scalars():
            v = d.current
            if v is None:
                continue
            if v.processing_status in ("queued", "processing"):
                process_version(db, v)
            docs.append((d, v))
        db.commit()
        run.stage = "checks"
        on = reference_date(db)
        rules = applicable_rules(db, app, on)
        run.rule_versions = {rv.rule.code: rv.version for rv in rules}
        sources = {s.code: s for s in db.execute(select(VerificationSource)).scalars()}
        ctx = Ctx(db=db, app=app, run=run, ref_date=on, docs=docs, sources=sources)
        counts = {"new": 0, "changed": 0, "unchanged": 0, "passes_now": 0}
        by_status: dict[str, int] = {}
        seen: set[str] = set()
        for rv in rules:
            fn = CHECKS.get(rv.check_type)
            if not fn:
                continue
            run.stage = f"rule {rv.rule.code}"
            db.flush()
            for o in fn(ctx, rv):
                if o.fingerprint in seen:
                    continue
                seen.add(o.fingerprint)
                _, ch = _upsert(db, app, run, rv, o)
                counts[ch] += 1
                by_status[o.status] = by_status.get(o.status, 0) + 1
        # Findings not reproduced by this run (e.g. their document was replaced): note it, keep history.
        for f in db.execute(select(Finding).where(Finding.application_id == app.id, Finding.origin == "automated")).scalars():
            if f.fingerprint not in seen and f.last_run_id != run.id and f.latest_result != "not_reevaluated":
                db.add(FindingEvent(finding_id=f.id, run_id=run.id, action="not_reevaluated", from_status=f.latest_result,
                                    to_status="not_reevaluated", detail=f"Run #{run.id} did not produce this check (evidence changed or rule no longer applies)."))
                f.latest_result = "not_reevaluated"
        run.summary = {"checks": sum(by_status.values()), "by_status": by_status, "changes": counts,
                       "documents": len(docs), "reference_date": on.isoformat()}
        run.status, run.stage, run.finished_at = "completed", "done", utcnow()
        if app.status == "submitted":
            app.status = "under_scrutiny"
        elif app.status == "reverification":
            app.status = "response_received"  # reviewer must now examine the responses
        audit.record(db, "verification.completed", "verification_run", run.id, application_id=app.id,
                     summary=f"Verification run #{run.id} ({run.kind}) completed: {run.summary['checks']} checks",
                     details={"rule_versions": run.rule_versions, "by_status": by_status})
        notify.to_officers(db, app, "verification_completed", f"Verification completed — {app.reference}",
                           f"Run #{run.id} ({run.kind}) evaluated {run.summary['checks']} checks.",
                           f"/reviewer/applications/{app.id}#verification")
        db.commit()
    except Exception as e:
        db.rollback()
        run = db.get(VerificationRun, run.id)
        run.status, run.finished_at = "failed", utcnow()
        run.error = f"{type(e).__name__}: {e}"[:1000]
        log.error("Verification run %s failed\n%s", run.id, traceback.format_exc())
        audit.record(db, "verification.failed", "verification_run", run.id, application_id=run.application_id,
                     summary=f"Verification run #{run.id} failed", details={"error": run.error})
        db.commit()
    return run


def _run_in_thread(run_id: int) -> None:
    db = SessionLocal()
    try:
        run = db.get(VerificationRun, run_id)
        if run:
            execute_run(db, run)
    finally:
        db.close()


def enqueue(db: Session, app: Application, kind: str, actor_id: int | None) -> VerificationRun:
    active = db.execute(
        select(VerificationRun).where(VerificationRun.application_id == app.id, VerificationRun.status.in_(["queued", "running"]))
    ).scalar_one_or_none()
    if active:
        return active
    run = VerificationRun(application_id=app.id, submission_version=app.current_version, kind=kind, triggered_by_id=actor_id)
    db.add(run)
    db.flush()
    db.commit()
    if settings.jobs_mode == "sync":
        execute_run(db, run)
    else:
        _executor.submit(_run_in_thread, run.id)
    return run


# ------------------------------------------------------------------ explainable priority


def priority(db: Session, app: Application, ref: date | None = None) -> dict:
    ref = ref or reference_date(db)
    fs = db.execute(select(Finding).where(Finding.application_id == app.id)).scalars().all()
    open_issues = [f for f in fs if f.is_issue and f.status not in ("resolved", "verified") and f.review_state != "dismissed"]
    reasons: list[dict] = []
    score = 0
    hi = [f for f in open_issues if f.severity == "high" and f.status in ("mismatch", "missing", "expired", "rejected")]
    if hi:
        kinds = sorted({f.status for f in hi})
        score += 30 + 5 * len(hi)
        reasons.append({"code": "mandatory_deficiencies", "text": f"{len(hi)} serious finding(s): " + ", ".join(k.replace('_', ' ') for k in kinds), "weight": 30 + 5 * len(hi)})
    manual = [f for f in open_issues if f.status in ("manual_review", "inconclusive")]
    if manual:
        score += 6
        reasons.append({"code": "manual_verification", "text": f"{len(manual)} item(s) need manual verification", "weight": 6})
    mism = [f for f in open_issues if f.category == "external" and f.status == "mismatch"]
    if mism:
        score += 15
        reasons.append({"code": "source_mismatch", "text": f"{len(mism)} external-source mismatch(es)", "weight": 15})
    anomalies = [f for f in open_issues if f.category in ("anomaly", "duplicate")]
    if anomalies:
        score += 10
        reasons.append({"code": "anomalies", "text": f"{len(anomalies)} anomaly/duplicate indicator(s) need human review", "weight": 10})
    soon = [f for f in fs if f.confidence_note == "expiring_soon"]
    if soon:
        score += 8
        reasons.append({"code": "expiring", "text": f"{len(soon)} document(s) expiring within the warning window", "weight": 8})
    pend = [f for f in fs if f.status in ("source_unavailable", "pending")]
    if pend:
        score += 4
        reasons.append({"code": "pending_sources", "text": f"{len(pend)} source check(s) unavailable or pending", "weight": 4})
    if app.status == "response_received":
        score += 25
        reasons.append({"code": "response_waiting", "text": "Institution response awaiting reverification", "weight": 25})
    if app.status == "awaiting_decision":
        score += 12
        reasons.append({"code": "decision_waiting", "text": "Ready for official decision", "weight": 12})
    if app.status == "submitted":
        score += 6
        reasons.append({"code": "not_started", "text": "Verification not yet run", "weight": 6})
    level = "high" if score >= 45 else "medium" if score >= 15 else "low"
    return {"score": score, "level": level, "reasons": reasons, "open_issues": len(open_issues),
            "note": "Rule-based workload ordering only. Priority never determines approval or rejection."}
