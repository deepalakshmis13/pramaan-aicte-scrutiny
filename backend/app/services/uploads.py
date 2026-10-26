from __future__ import annotations

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import storage
from ..config import settings
from ..enums import ALLOWED_UPLOAD_TYPES
from ..models import Document, DocumentVersion, User


async def read_validated(file: UploadFile) -> tuple[bytes, str, str]:
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File exceeds the {settings.max_upload_mb} MB limit")
    if len(data) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    mime = storage.sniff_mime(data)
    if mime not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF, PNG and JPEG files are accepted")
    if mime == "application/pdf":
        import pymupdf

        try:
            d = pymupdf.open(stream=data, filetype="pdf")
            if d.needs_pass or d.is_encrypted:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password-protected PDFs cannot be processed")
            if d.page_count > 60:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF has more than 60 pages")
            d.close()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The PDF could not be opened; it may be corrupt")
    return data, mime, storage.safe_display_name(file.filename or "upload")


def add_version(db: Session, doc: Document, data: bytes, mime: str, filename: str, user: User | None,
                submission_version: int, pending: bool = False) -> DocumentVersion:
    n = db.execute(select(func.max(DocumentVersion.version_no)).where(DocumentVersion.document_id == doc.id)).scalar() or 0
    key = storage.new_key("documents", doc.application_id, ALLOWED_UPLOAD_TYPES[mime])
    storage.save_bytes(key, data)
    dv = DocumentVersion(
        document_id=doc.id, version_no=n + 1, submission_version=submission_version, storage_key=key,
        original_filename=filename, mime_type=mime, size_bytes=len(data), sha256=storage.sha256(data),
        uploaded_by_id=user.id if user else None, processing_status="queued", is_pending=pending,
    )
    db.add(dv)
    db.flush()
    db.refresh(doc)
    return dv
