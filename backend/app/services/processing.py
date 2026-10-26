"""Per-document processing: extraction, classification, field persistence."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import storage
from ..models import DocumentVersion, ExtractedField, utcnow
from . import classification, extraction

CRITICAL_FIELDS = {
    "institution_name", "permanent_id", "certificate_number", "issue_date", "expiry_date",
    "holder_name", "degree", "approved_intake", "faculty_name", "faculty_qualification",
    "pub_doi", "pub_title", "transaction_id", "room_label",
}


def get_threshold(db: Session) -> float:
    from ..models import SystemConfig

    cfg = db.get(SystemConfig, "ocr_confirmation_threshold")
    return float((cfg.value or {}).get("value", 75)) if cfg else 75.0


def process_version(db: Session, dv: DocumentVersion) -> DocumentVersion:
    dv.processing_status = "processing"
    db.flush()
    try:
        data = storage.read_bytes(dv.storage_key)
        res = extraction.extract(data, dv.mime_type)
        threshold = get_threshold(db)
        dv.text_method = res.method
        dv.extracted_text = res.text[:200_000]
        dv.page_count = res.page_count
        dv.ocr_mean_confidence = res.mean_conf
        dv.quality = res.quality | {"overlay_boxes": res.overlay_boxes, "page_fonts": res.page_fonts, "font_outliers": res.font_outliers}
        dv.file_metadata = res.file_metadata
        dv.image_hash = res.image_hash
        declared = dv.document.document_type
        if declared in {"infrastructure_photo"}:
            dv.classified_type, dv.classification_basis = declared, {"method": "declared (image evidence)", "matches": {}}
        else:
            dv.classified_type, dv.classification_basis = classification.classify(res.text, declared)
        for f in dv.fields:
            db.delete(f)
        db.flush()
        for fo in extraction.extract_fields(res.lines):
            needs = res.method == "ocr" and fo.name in CRITICAL_FIELDS and (fo.conf is None or fo.conf < threshold)
            db.add(
                ExtractedField(
                    document_version_id=dv.id,
                    field_name=fo.name,
                    group_key=fo.group,
                    value=fo.value[:2000],
                    normalized_value=extraction.normalize_field(fo.name, fo.value)[:2000],
                    page=fo.page,
                    bbox=fo.bbox,
                    method="ocr" if res.method == "ocr" else "native_text",
                    ocr_confidence=fo.conf,
                    needs_confirmation=needs,
                )
            )
        dv.processing_status = "processed"
        dv.processing_error = ""
    except Exception as e:  # recorded, surfaced in UI and as an extraction finding
        dv.processing_status = "failed"
        dv.processing_error = f"{type(e).__name__}: {str(e)[:300]}"
    dv.processed_at = utcnow()
    db.flush()
    db.refresh(dv)
    return dv
