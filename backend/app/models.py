"""Relational schema for the scrutiny workflow.

Design notes
- Official history is append-oriented: document versions, finding events, notice
  versions, verification runs, source checks and audit events are never deleted.
- Enumerations are stored as short strings; allowed values live in `app.enums`.
- All timestamps are timezone-aware UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


TS = DateTime(timezone=True)


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[int] = mapped_column(primary_key=True)
    permanent_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(64))
    city: Mapped[str] = mapped_column(String(64))
    institution_type: Mapped[str] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    designation: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))  # reviewer | institution | admin
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    institution: Mapped[Institution | None] = relationship()


class ApplicationCategory(Base):
    __tablename__ = "application_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    checklist: Mapped[list[ChecklistItem]] = relationship(
        back_populates="category", order_by="ChecklistItem.sort_order"
    )


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    __table_args__ = (UniqueConstraint("category_id", "document_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("application_categories.id"))
    document_type: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_validity: Mapped[bool] = mapped_column(Boolean, default=False)
    guidance: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped[ApplicationCategory] = relationship(back_populates="checklist")


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("application_categories.id"))
    academic_year: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    assigned_reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Values the institution declared in the application form (claims under scrutiny)
    declared: Mapped[dict] = mapped_column(JSON, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    scenario: Mapped[str] = mapped_column(String(255), default="")
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    institution: Mapped[Institution] = relationship()
    category: Mapped[ApplicationCategory] = relationship()
    assigned_reviewer: Mapped[User | None] = relationship(foreign_keys=[assigned_reviewer_id])
    documents: Mapped[list[Document]] = relationship(back_populates="application", order_by="Document.id")

    __mapper_args__ = {"version_id_col": row_version}


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("application_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))  # initial | resubmission
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("deficiency_notices.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    application: Mapped[Application] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", order_by="DocumentVersion.version_no"
    )

    @property
    def current(self) -> DocumentVersion | None:
        """Latest version that is part of a submitted application version (drafts excluded)."""
        official = [v for v in self.versions if not v.is_pending]
        return official[-1] if official else None


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    submission_version: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    # queued | processing | processed | failed
    processing_status: Mapped[str] = mapped_column(String(32), default="queued")
    processing_error: Mapped[str] = mapped_column(Text, default="")
    text_method: Mapped[str] = mapped_column(String(32), default="")  # native | ocr | none
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    ocr_mean_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classified_type: Mapped[str] = mapped_column(String(64), default="")
    classification_basis: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    file_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    image_hash: Mapped[str] = mapped_column(String(64), default="")
    processed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    # True while a replacement uploaded by the institution is a draft (not yet resubmitted)
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # Officer decision on this specific version: pending | accepted | rejected | manual
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    review_note: Mapped[str] = mapped_column(Text, default="")
    manually_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    document: Mapped[Document] = relationship(back_populates="versions")
    fields: Mapped[list[ExtractedField]] = relationship(
        back_populates="document_version", order_by="ExtractedField.id"
    )


class DocumentReview(Base):
    """Append-only history of officer decisions on document versions."""

    __tablename__ = "document_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # accepted | rejected | manual
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    actor: Mapped[User] = relationship()


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(64), index=True)
    group_key: Mapped[str] = mapped_column(String(64), default="")  # e.g. row index for tables
    value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int] = mapped_column(Integer, default=1)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [x0,y0,x1,y1] in page fraction
    method: Mapped[str] = mapped_column(String(32))  # native_text | ocr
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="fields")

    @property
    def effective_value(self) -> str:
        return self.confirmed_value if self.confirmed_value is not None else self.value


class RegulatoryRule(Base):
    __tablename__ = "regulatory_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    group: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    versions: Mapped[list[RuleVersion]] = relationship(
        back_populates="rule", order_by="RuleVersion.version"
    )

    @property
    def current(self) -> RuleVersion | None:
        active = [v for v in self.versions if v.is_active]
        return active[-1] if active else None


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("regulatory_rules.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    source_reference: Mapped[str] = mapped_column(Text)
    source_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    categories: Mapped[list] = mapped_column(JSON, default=list)  # category codes, [] = all
    check_type: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    rule: Mapped[RegulatoryRule] = relationship(back_populates="versions")


class VerificationSource(Base):
    __tablename__ = "verification_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(64))
    claim_types: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(16))  # live | simulated | disabled
    base_url: Mapped[str] = mapped_column(String(255), default="")
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=8)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    submission_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))  # initial | reverification | manual
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|completed|failed
    stage: Mapped[str] = mapped_column(String(64), default="")
    triggered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rule_versions: Mapped[dict] = mapped_column(JSON, default=dict)  # rule code -> version applied
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class SourceCheck(Base):
    __tablename__ = "source_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("verification_runs.id"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    source_code: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))  # live | simulated | not_configured | disabled
    claim_type: Mapped[str] = mapped_column(String(64))
    claim: Mapped[dict] = mapped_column(JSON, default=dict)
    query: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    fields_compared: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    reference_url: Mapped[str] = mapped_column(String(512), default="")
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Finding(Base):
    """A claim-level check outcome. Issues have is_issue=True; passing checks are kept for traceability."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("application_id", "fingerprint"),
        Index("ix_findings_app_status", "application_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    first_run_id: Mapped[int | None] = mapped_column(ForeignKey("verification_runs.id"), nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(ForeignKey("verification_runs.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True)
    related_document_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_versions.id"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(String(64), default="")
    field: Mapped[str] = mapped_column(String(128), default="")
    extracted_value: Mapped[str] = mapped_column(Text, default="")
    expected_value: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(255), default="")
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey("rule_versions.id"), nullable=True)
    source_check_id: Mapped[int | None] = mapped_column(ForeignKey("source_checks.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    certainty: Mapped[str] = mapped_column(String(16))  # confirmed | suspected | inconclusive | n/a
    confidence_note: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(16), default="automated")  # automated | manual
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    # Official status (changes to resolved/escalated only through reviewer action)
    status: Mapped[str] = mapped_column(String(32))
    # Most recent automated result for this check
    latest_result: Mapped[str] = mapped_column(String(32), default="")
    is_issue: Mapped[bool] = mapped_column(Boolean, default=True)
    in_notice: Mapped[bool] = mapped_column(Boolean, default=False)
    review_state: Mapped[str] = mapped_column(String(16), default="unreviewed")  # unreviewed|confirmed|dismissed
    review_reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    institution_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    rule_version: Mapped[RuleVersion | None] = relationship()
    source_check: Mapped[SourceCheck | None] = relationship()
    document_version: Mapped[DocumentVersion | None] = relationship(foreign_keys=[document_version_id])
    events: Mapped[list[FindingEvent]] = relationship(order_by="FindingEvent.id")


class FindingEvent(Base):
    __tablename__ = "finding_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("verification_runs.id"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str] = mapped_column(String(32), default="")
    to_status: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ReviewerNote(Base):
    __tablename__ = "reviewer_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    author: Mapped[User] = relationship()


class DeficiencyNotice(Base):
    __tablename__ = "deficiency_notices"
    __table_args__ = (UniqueConstraint("application_id", "sequence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    submission_version: Mapped[int] = mapped_column(Integer)
    # draft | pending_approval | issued | responded | closed | withdrawn
    status: Mapped[str] = mapped_column(String(32), default="draft")
    cover_note: Mapped[str] = mapped_column(Text, default="")
    response_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    prepared_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_for_approval_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    approval_remarks: Mapped[str] = mapped_column(Text, default="")
    returned_remarks: Mapped[str] = mapped_column(Text, default="")
    issued_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    delivery_channel: Mapped[str] = mapped_column(String(255), default="")
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", use_alter=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    items: Mapped[list[NoticeItem]] = relationship(
        back_populates="notice", order_by="NoticeItem.item_no", cascade="all, delete-orphan"
    )
    prepared_by: Mapped[User] = relationship(foreign_keys=[prepared_by_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])

    __mapper_args__ = {"version_id_col": row_version}


class NoticeItem(Base):
    __tablename__ = "notice_items"
    __table_args__ = (UniqueConstraint("notice_id", "item_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("deficiency_notices.id"), index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"))
    item_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    corrective_action: Mapped[str] = mapped_column(Text)
    document_reference: Mapped[str] = mapped_column(String(255), default="")
    rule_reference: Mapped[str] = mapped_column(Text, default="")
    # open | responded | resolved | not_resolved | escalated
    status: Mapped[str] = mapped_column(String(32), default="open")
    outcome_note: Mapped[str] = mapped_column(Text, default="")

    notice: Mapped[DeficiencyNotice] = relationship(back_populates="items")
    finding: Mapped[Finding] = relationship()
    responses: Mapped[list[InstitutionResponse]] = relationship(
        back_populates="item", order_by="InstitutionResponse.id"
    )


class InstitutionResponse(Base):
    __tablename__ = "institution_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    notice_item_id: Mapped[int] = mapped_column(ForeignKey("notice_items.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    response_text: Mapped[str] = mapped_column(Text)
    document_version_id: Mapped[int | None] = mapped_column(ForeignKey("document_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | submitted
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    item: Mapped[NoticeItem] = relationship(back_populates="responses")
    document_version: Mapped[DocumentVersion | None] = relationship()


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(48))
    reasons: Mapped[str] = mapped_column(Text)
    conditions: Mapped[str] = mapped_column(Text, default="")
    decided_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submission_version: Mapped[int] = mapped_column(Integer)
    open_issue_count: Mapped[int] = mapped_column(Integer, default=0)
    acknowledged_open_issues: Mapped[bool] = mapped_column(Boolean, default=False)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", use_alter=True), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    decided_by: Mapped[User] = relationship()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(48), unique=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # deficiency_notice | internal_review | final_decision
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("deficiency_notices.id", use_alter=True), nullable=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id", use_alter=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False)
    confidentiality: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    generated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    link_path: Mapped[str] = mapped_column(String(255), default="")
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditEvent(Base):
    """Append-only audit log with a SHA-256 hash chain for integrity checking (tamper-evident, not tamper-proof)."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(255), default="system")
    actor_role: Mapped[str] = mapped_column(String(32), default="system")
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class SystemConfig(Base):
    __tablename__ = "system_config"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text, default="")
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
