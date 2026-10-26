"""Explicit response shaping. Institution-facing serializers omit internal fields."""
from __future__ import annotations

from .enums import APPLICATION_STATUSES, DOCUMENT_TYPES, FINDING_CATEGORIES, NOTICE_STATUSES, RESULT_STATES
from .models import (
    Application,
    DeficiencyNotice,
    Document,
    DocumentVersion,
    ExtractedField,
    Finding,
    FindingEvent,
    InstitutionResponse,
    NoticeItem,
    Report,
    RuleVersion,
    SourceCheck,
    User,
    VerificationRun,
)


def iso(dt):
    return dt.isoformat() if dt else None


def user(u: User | None) -> dict | None:
    if not u:
        return None
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name, "designation": u.designation, "role": u.role,
        "institution_id": u.institution_id, "institution_name": u.institution.name if u.institution else None,
        "is_active": u.is_active, "last_login_at": iso(u.last_login_at),
    }


def user_brief(u: User | None) -> dict | None:
    return {"id": u.id, "full_name": u.full_name, "designation": u.designation} if u else None


def application_brief(a: Application, priority: dict | None = None) -> dict:
    d = {
        "id": a.id, "reference": a.reference, "status": a.status, "status_label": APPLICATION_STATUSES.get(a.status, a.status),
        "institution": {"id": a.institution.id, "name": a.institution.name, "permanent_id": a.institution.permanent_id,
                        "state": a.institution.state, "city": a.institution.city},
        "category": {"id": a.category.id, "code": a.category.code, "name": a.category.name},
        "academic_year": a.academic_year, "submitted_at": iso(a.submitted_at), "current_version": a.current_version,
        "assigned_reviewer": user_brief(a.assigned_reviewer), "is_synthetic": a.is_synthetic, "updated_at": iso(a.updated_at),
    }
    if priority is not None:
        d["priority"] = priority
    return d


def field(f: ExtractedField) -> dict:
    return {
        "id": f.id, "field_name": f.field_name, "group_key": f.group_key, "value": f.value, "normalized_value": f.normalized_value,
        "effective_value": f.effective_value, "page": f.page, "bbox": f.bbox, "method": f.method, "ocr_confidence": f.ocr_confidence,
        "needs_confirmation": f.needs_confirmation, "confirmed_value": f.confirmed_value, "confirmed_at": iso(f.confirmed_at),
    }


def version(v: DocumentVersion, with_fields: bool = False, internal: bool = True) -> dict:
    d = {
        "id": v.id, "version_no": v.version_no, "submission_version": v.submission_version, "original_filename": v.original_filename,
        "mime_type": v.mime_type, "size_bytes": v.size_bytes, "sha256": v.sha256, "page_count": v.page_count,
        "uploaded_at": iso(v.uploaded_at), "processing_status": v.processing_status, "is_pending": v.is_pending,
    }
    if internal:
        d.update({
            "processing_error": v.processing_error, "text_method": v.text_method, "ocr_mean_confidence": v.ocr_mean_confidence,
            "classified_type": v.classified_type, "classification_basis": v.classification_basis,
            "quality": {k: val for k, val in (v.quality or {}).items() if k != "page_fonts"},
            "file_metadata": v.file_metadata, "image_hash": v.image_hash, "processed_at": iso(v.processed_at),
        })
        if with_fields:
            d["fields"] = [field(f) for f in v.fields]
            d["extracted_text"] = v.extracted_text
    return d


def document(doc: Document, internal: bool = True, include_pending: bool = False) -> dict:
    vs = [v for v in doc.versions if include_pending or not v.is_pending]
    cur = doc.current
    return {
        "id": doc.id, "application_id": doc.application_id, "document_type": doc.document_type,
        "document_type_label": DOCUMENT_TYPES.get(doc.document_type, doc.document_type), "title": doc.title,
        "created_at": iso(doc.created_at), "current": version(cur, internal=internal) if cur else None,
        "versions": [version(v, internal=internal) for v in vs],
    }


def rule_version(rv: RuleVersion | None) -> dict | None:
    if not rv:
        return None
    return {
        "id": rv.id, "rule_id": rv.rule_id, "code": rv.rule.code, "title": rv.rule.title, "group": rv.rule.group,
        "version": rv.version, "description": rv.description, "source_reference": rv.source_reference,
        "source_verified": rv.source_verified, "categories": rv.categories, "check_type": rv.check_type, "params": rv.params,
        "severity": rv.severity, "effective_from": iso(rv.effective_from), "effective_to": iso(rv.effective_to),
        "is_active": rv.is_active, "change_note": rv.change_note, "created_at": iso(rv.created_at),
    }


def source_check(c: SourceCheck) -> dict:
    return {
        "id": c.id, "run_id": c.run_id, "source_code": c.source_code, "source_name": c.source_name, "source_type": c.source_type,
        "mode": c.mode, "claim_type": c.claim_type, "claim": c.claim, "query": c.query, "status": c.status,
        "status_label": RESULT_STATES.get(c.status, c.status), "http_status": c.http_status, "response_summary": c.response_summary,
        "fields_compared": c.fields_compared, "explanation": c.explanation, "reference_url": c.reference_url,
        "document_version_id": c.document_version_id, "checked_at": iso(c.checked_at), "duration_ms": c.duration_ms,
    }


def finding(f: Finding, full: bool = False) -> dict:
    d = {
        "id": f.id, "code": f.code, "category": f.category, "category_label": FINDING_CATEGORIES.get(f.category, f.category),
        "title": f.title, "status": f.status, "status_label": RESULT_STATES.get(f.status, f.status), "latest_result": f.latest_result,
        "latest_result_label": RESULT_STATES.get(f.latest_result, f.latest_result), "is_issue": f.is_issue, "in_notice": f.in_notice,
        "severity": f.severity, "certainty": f.certainty, "origin": f.origin, "review_state": f.review_state,
        "document_version_id": f.document_version_id, "related_document_version_id": f.related_document_version_id,
        "document_type": f.document_type, "field": f.field, "extracted_value": f.extracted_value, "expected_value": f.expected_value,
        "reason": f.reason, "rule_code": f.rule_version.rule.code if f.rule_version else None,
        "rule_version": f.rule_version.version if f.rule_version else None, "source_check_id": f.source_check_id,
        "first_run_id": f.first_run_id, "last_run_id": f.last_run_id, "created_at": iso(f.created_at), "updated_at": iso(f.updated_at),
        "confidence_note": f.confidence_note,
    }
    if full:
        d.update({
            "method": f.method, "limitations": f.limitations, "evidence": f.evidence, "recommended_action": f.recommended_action,
            "institution_text": f.institution_text, "review_reason": f.review_reason,
            "rule": rule_version(f.rule_version), "source_check": source_check(f.source_check) if f.source_check else None,
        })
    return d


def finding_event(e: FindingEvent, actor: User | None) -> dict:
    return {"id": e.id, "action": e.action, "from_status": e.from_status, "to_status": e.to_status, "detail": e.detail,
            "run_id": e.run_id, "actor": user_brief(actor), "created_at": iso(e.created_at)}


def run(r: VerificationRun) -> dict:
    return {"id": r.id, "application_id": r.application_id, "submission_version": r.submission_version, "kind": r.kind,
            "status": r.status, "stage": r.stage, "rule_versions": r.rule_versions, "summary": r.summary, "error": r.error,
            "created_at": iso(r.created_at), "started_at": iso(r.started_at), "finished_at": iso(r.finished_at),
            "triggered_by_id": r.triggered_by_id}


def response(r: InstitutionResponse) -> dict:
    return {"id": r.id, "notice_item_id": r.notice_item_id, "response_text": r.response_text, "status": r.status,
            "document_version": version(r.document_version, internal=False) if r.document_version else None,
            "document_id": r.document_version.document_id if r.document_version else None,
            "created_at": iso(r.created_at), "submission_id": r.submission_id}


def notice_item(it: NoticeItem, internal: bool) -> dict:
    d = {"id": it.id, "item_no": it.item_no, "title": it.title, "description": it.description,
         "corrective_action": it.corrective_action, "document_reference": it.document_reference,
         "rule_reference": it.rule_reference, "status": it.status,
         "category": it.finding.category, "category_label": FINDING_CATEGORIES.get(it.finding.category, it.finding.category),
         "document_type": it.finding.document_type, "responses": [response(r) for r in it.responses]}
    if internal:
        d["finding"] = finding(it.finding)
        d["outcome_note"] = it.outcome_note
    else:
        # Institution sees which of its documents the item concerns (needed to upload a replacement), nothing internal.
        dv = it.finding.document_version
        d["target_document_id"] = dv.document_id if dv else None
    return d


def notice(n: DeficiencyNotice, internal: bool) -> dict:
    d = {"id": n.id, "reference": n.reference, "application_id": n.application_id, "sequence": n.sequence,
         "submission_version": n.submission_version, "status": n.status, "status_label": NOTICE_STATUSES.get(n.status, n.status),
         "cover_note": n.cover_note, "response_deadline": iso(n.response_deadline), "issued_at": iso(n.issued_at),
         "approved_at": iso(n.approved_at), "approved_by": user_brief(n.approved_by), "prepared_by": user_brief(n.prepared_by),
         "delivery_channel": n.delivery_channel, "report_id": n.report_id, "created_at": iso(n.created_at),
         "items": [notice_item(i, internal) for i in n.items]}
    if internal:
        d.update({"submitted_for_approval_at": iso(n.submitted_for_approval_at), "approval_remarks": n.approval_remarks,
                  "returned_remarks": n.returned_remarks, "row_version": n.row_version})
    return d


def report(r: Report) -> dict:
    return {"id": r.id, "reference": r.reference, "kind": r.kind, "version": r.version, "is_preview": r.is_preview,
            "confidentiality": r.confidentiality, "sha256": r.sha256, "size_bytes": r.size_bytes,
            "generated_at": iso(r.generated_at), "notice_id": r.notice_id, "decision_id": r.decision_id}
