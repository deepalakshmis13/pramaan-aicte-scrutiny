from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date

from sqlalchemy.orm import Session

from ...enums import DOCUMENT_TYPES
from ...models import Application, Document, DocumentVersion, ExtractedField, RuleVersion, VerificationRun


@dataclass
class Outcome:
    fingerprint: str
    category: str
    title: str
    status: str
    is_issue: bool
    reason: str
    certainty: str = "confirmed"  # confirmed | suspected | inconclusive | n/a
    severity: str = "medium"
    document_version_id: int | None = None
    related_document_version_id: int | None = None
    document_type: str = ""
    field: str = ""
    extracted_value: str = ""
    expected_value: str = ""
    method: str = ""
    limitations: str = ""
    evidence: list = dc_field(default_factory=list)
    recommended_action: str = ""
    institution_text: str = ""
    confidence_note: str = ""
    source_check_id: int | None = None


@dataclass
class Ctx:
    db: Session
    app: Application
    run: VerificationRun
    ref_date: date
    docs: list[tuple[Document, DocumentVersion]]
    sources: dict  # code -> VerificationSource

    def of_type(self, t: str) -> list[tuple[Document, DocumentVersion]]:
        return [(d, v) for d, v in self.docs if d.document_type == t]

    @staticmethod
    def fields(v: DocumentVersion, name: str) -> list[ExtractedField]:
        return [f for f in v.fields if f.field_name == name]

    @staticmethod
    def first(v: DocumentVersion, name: str) -> ExtractedField | None:
        for f in v.fields:
            if f.field_name == name:
                return f
        return None


def doc_label(d: Document) -> str:
    return f"{d.title} (DOC-{d.id})"


def ev_field(d: Document, v: DocumentVersion, f: ExtractedField) -> dict:
    return {
        "type": "field", "document_id": d.id, "document_version_id": v.id, "version_no": v.version_no,
        "document_title": d.title, "field_id": f.id, "field": f.field_name, "value": f.effective_value,
        "page": f.page, "bbox": f.bbox, "method": f.method, "ocr_confidence": f.ocr_confidence,
        "confirmed": f.confirmed_value is not None,
    }


def ev_doc(d: Document, v: DocumentVersion, note: str = "", page: int | None = None, bbox=None) -> dict:
    return {"type": "document", "document_id": d.id, "document_version_id": v.id, "version_no": v.version_no,
            "document_title": d.title, "note": note, "page": page, "bbox": bbox}


def ev_declared(field_name: str, value: str) -> dict:
    return {"type": "declared", "field": field_name, "value": value, "note": "Value declared in the application form"}


def ev_rule(rv: RuleVersion) -> dict:
    return {"type": "rule", "rule_code": rv.rule.code, "version": rv.version, "rule_version_id": rv.id}


def type_label(t: str) -> str:
    return DOCUMENT_TYPES.get(t, t)
