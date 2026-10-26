"""Server-side PDF generation (ReportLab) from persisted records only.

Reports never include signatures, approvals or source confirmations that are not
recorded in the database. Approval is shown as an electronic record reference.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import DECISION_OUTCOMES, FINDING_CATEGORIES, RESULT_STATES
from ..models import (
    Application,
    Decision,
    DeficiencyNotice,
    Document,
    DocumentVersion,
    Finding,
    ReviewerNote,
    SourceCheck,
    User,
    VerificationRun,
)

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
try:
    pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Serif", str(FONT_DIR / "DejaVuSerif.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Bold", str(FONT_DIR / "DejaVuSerif-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", str(FONT_DIR / "DejaVuSansMono.ttf")))
    SANS, SANS_B, SERIF, SERIF_B, MONO = "Sans", "Sans-Bold", "Serif", "Serif-Bold", "Mono"
except Exception:  # pragma: no cover
    SANS, SANS_B, SERIF, SERIF_B, MONO = "Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold", "Courier"

INK = colors.HexColor("#0E1A2E")
MUTED = colors.HexColor("#5B6577")
RULE = colors.HexColor("#C9CED6")
TINT = colors.HexColor("#F3F1EC")
AMBER = colors.HexColor("#9A6200")
RED = colors.HexColor("#A3271F")
TEAL = colors.HexColor("#0F6E66")

S = {
    "title": ParagraphStyle("title", fontName=SERIF_B, fontSize=15, leading=19, textColor=INK, spaceAfter=2),
    "subtitle": ParagraphStyle("subtitle", fontName=SANS, fontSize=8.5, leading=11, textColor=MUTED),
    "h2": ParagraphStyle("h2", fontName=SANS_B, fontSize=10.5, leading=14, textColor=INK, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName=SERIF, fontSize=9.5, leading=13.5, textColor=INK, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName=SANS, fontSize=7.8, leading=10, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName=SANS, fontSize=8, leading=10.5, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName=SANS_B, fontSize=8, leading=10.5, textColor=INK),
    "mono": ParagraphStyle("mono", fontName=MONO, fontSize=7.4, leading=9.5, textColor=INK),
}


def _p(text: str, style: str = "body") -> Paragraph:
    from xml.sax.saxutils import escape

    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), S[style])


def _fmt(dt) -> str:
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%d %b %Y, %H:%M UTC")
    return dt.strftime("%d %b %Y")


class _Frame:
    def __init__(self, header: str, confidentiality: str, preview: bool, synthetic: bool, ref: str):
        self.header, self.conf, self.preview, self.synthetic, self.ref = header, confidentiality, preview, synthetic, ref

    def __call__(self, canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(INK)
        canvas.rect(0, h - 9 * mm, w, 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont(SANS_B, 7.5)
        canvas.drawString(15 * mm, h - 6 * mm, "PRAMAAN · APPLICATION SCRUTINY PROTOTYPE")
        canvas.drawRightString(w - 15 * mm, h - 6 * mm, self.conf.upper())
        canvas.setFillColor(MUTED)
        canvas.setFont(SANS, 7)
        canvas.drawString(15 * mm, 9 * mm, f"{self.ref} · {self.header}")
        canvas.drawRightString(w - 15 * mm, 9 * mm, f"Page {doc.page}")
        if self.synthetic:
            canvas.setFillColor(AMBER)
            canvas.drawCentredString(w / 2, 4.5 * mm, "SYNTHETIC TEST DATA — NOT AN OFFICIAL AICTE RECORD")
        if self.preview:
            canvas.setFillColor(colors.Color(0.64, 0.15, 0.12, alpha=0.10))
            canvas.setFont(SANS_B, 54)
            canvas.translate(w / 2, h / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "PREVIEW · NOT ISSUED")
        canvas.restoreState()


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table([[_p(k, "cellb"), _p(v, "cell")] for k, v in rows], colWidths=[42 * mm, 128 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
        ("BACKGROUND", (0, 0), (0, -1), TINT),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _build(story, header, conf, preview, synthetic, ref) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
                            title=f"{header} {ref}", author="PRAMAAN prototype", subject=header)
    fr = _Frame(header, conf, preview, synthetic, ref)
    doc.build(story, onFirstPage=fr, onLaterPages=fr)
    return buf.getvalue()


def _doc_ref(db: Session, dv_id: int | None) -> str:
    if not dv_id:
        return "—"
    dv = db.get(DocumentVersion, dv_id)
    if not dv:
        return "—"
    d = db.get(Document, dv.document_id)
    return f"DOC-{d.id} v{dv.version_no} · {d.title}"


def _evidence_lines(f: Finding, internal: bool) -> str:
    out = []
    for e in f.evidence or []:
        t = e.get("type")
        if t == "field":
            out.append(f"{e.get('document_title')} (v{e.get('version_no')}), p.{e.get('page')}: {e.get('field')} = “{e.get('value')}”")
        elif t == "declared":
            out.append(f"Application form: {e.get('field')} = “{e.get('value')}”")
        elif t == "document":
            out.append(f"{e.get('document_title')} (v{e.get('version_no')})" + (f" — {e.get('note')}" if internal and e.get("note") else ""))
        elif t == "source_check" and internal:
            out.append(f"Source check #{e.get('source_check_id')}: {e.get('source')} [{e.get('mode')}] → {RESULT_STATES.get(e.get('status', ''), e.get('status', ''))}")
        elif t == "external_application" and internal:
            out.append(f"Also in application {e.get('application_reference')}: {e.get('document_title')}")
        elif t == "checklist":
            out.append(f"Checklist item: {e.get('label')}")
    return "\n".join(out) or "—"


def deficiency_notice_pdf(db: Session, notice: DeficiencyNotice, preview: bool) -> bytes:
    app = db.get(Application, notice.application_id)
    inst = app.institution
    preparer = db.get(User, notice.prepared_by_id)
    approver = db.get(User, notice.approved_by_id) if notice.approved_by_id else None
    story = [
        _p("Deficiency / Clarification Notice", "title"),
        _p(f"Notice {notice.reference} · Version {notice.sequence} · Generated {_fmt(datetime.now(timezone.utc))}", "subtitle"),
        Spacer(1, 6),
        _kv_table([
            ("Application reference", app.reference),
            ("Institution", f"{inst.name} (Permanent ID {inst.permanent_id})"),
            ("Address", f"{inst.city}, {inst.state}"),
            ("Application category", app.category.name),
            ("Academic year", app.academic_year),
            ("Submission version", f"v{notice.submission_version}"),
            ("Response deadline", _fmt(notice.response_deadline) if notice.response_deadline else "Not specified"),
            ("Notice status", "PREVIEW — not issued" if preview else notice.status.replace("_", " ").title()),
        ]),
        Spacer(1, 8),
    ]
    if notice.cover_note:
        story += [_p("Note from the scrutiny officer", "h2"), _p(notice.cover_note)]
    story += [
        _p("Summary", "h2"),
        _p(f"Preliminary scrutiny of the above application identified {len(notice.items)} item(s) requiring correction, "
           "clarification or additional evidence. Each item below states the document concerned, the reason, and the action required. "
           "This notice is issued for clarification; it is not a decision on the application."),
        _p("Numbered deficiency items", "h2"),
    ]
    for it in notice.items:
        f = it.finding
        rows = [
            [_p(f"{it.item_no}.", "cellb"), _p(it.title, "cellb")],
            [_p("Category", "small"), _p(FINDING_CATEGORIES.get(f.category, f.category), "cell")],
            [_p("Document", "small"), _p(it.document_reference or "—", "cell")],
            [_p("Observation", "small"), _p(it.description, "cell")],
            [_p("Evidence considered", "small"), _p(_evidence_lines(f, internal=False), "cell")],
            [_p("Applicable rule", "small"), _p(it.rule_reference or "—", "cell")],
            [_p("Action required", "small"), _p(it.corrective_action, "cellb")],
            [_p("Item status", "small"), _p(it.status.replace("_", " ").title(), "cell")],
        ]
        t = Table(rows, colWidths=[30 * mm, 140 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), TINT),
            ("LINEABOVE", (0, 0), (-1, 0), 0.8, INK),
            ("LINEBELOW", (0, -1), (-1, -1), 0.3, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        story += [KeepTogether([t, Spacer(1, 6)])]
    story += [
        _p("How to respond", "h2"),
        _p("Log in to the institution workspace, open this notice, respond to each numbered item and upload corrected or additional "
           "documents where requested, then submit the response. Earlier versions of documents remain on record."),
        _p("Authorisation", "h2"),
        _kv_table([
            ("Prepared by", f"{preparer.full_name}, {preparer.designation}"),
            ("Approved by", f"{approver.full_name}, {approver.designation} — electronically on {_fmt(notice.approved_at)}" if approver else "Not yet approved"),
            ("Issued", _fmt(notice.issued_at) if notice.issued_at else "Not yet issued"),
            ("Delivery", notice.delivery_channel or "Internal portal notification and PDF download (external e-mail/portal dispatch is a planned integration)"),
        ]),
        Spacer(1, 6),
        _p("This notice was generated from recorded verification findings. Approval is recorded electronically in the system audit trail; "
           "no handwritten or digital signature is represented.", "small"),
    ]
    conf = "Confidential — addressed institution only"
    return _build(story, "Deficiency notice", conf, preview, app.is_synthetic, notice.reference)


def internal_review_pdf(db: Session, app: Application, generated_by: User) -> bytes:
    fs = db.execute(select(Finding).where(Finding.application_id == app.id).order_by(Finding.id)).scalars().all()
    runs = db.execute(select(VerificationRun).where(VerificationRun.application_id == app.id).order_by(VerificationRun.id)).scalars().all()
    checks = db.execute(select(SourceCheck).where(SourceCheck.application_id == app.id).order_by(SourceCheck.id)).scalars().all()
    notes = db.execute(select(ReviewerNote).where(ReviewerNote.application_id == app.id).order_by(ReviewerNote.id)).scalars().all()
    issues = [f for f in fs if f.is_issue]
    story = [
        _p("Internal Reviewer Report", "title"),
        _p(f"{app.reference} · {app.institution.name} · Generated {_fmt(datetime.now(timezone.utc))} by {generated_by.full_name}", "subtitle"),
        Spacer(1, 6),
        _kv_table([
            ("Category", app.category.name), ("Academic year", app.academic_year),
            ("Status", app.status.replace("_", " ")), ("Submission version", f"v{app.current_version}"),
            ("Verification runs", ", ".join(f"#{r.id} {r.kind} {r.status} ({_fmt(r.finished_at)})" for r in runs) or "None"),
            ("Checks recorded", f"{len(fs)} total; {len(issues)} raised as issues"),
        ]),
        _p("Findings", "h2"),
    ]
    data = [[_p(h, "cellb") for h in ("ID", "Finding", "Status", "Certainty", "Rule", "Review")]]
    for f in issues:
        data.append([
            _p(f.code, "mono"), _p(f.title, "cell"), _p(RESULT_STATES.get(f.status, f.status), "cell"), _p(f.certainty, "cell"),
            _p(f"{f.rule_version.rule.code} v{f.rule_version.version}" if f.rule_version else "manual", "cell"), _p(f.review_state, "cell"),
        ])
    t = Table(data, colWidths=[20 * mm, 66 * mm, 26 * mm, 20 * mm, 20 * mm, 18 * mm], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE), ("BACKGROUND", (0, 0), (-1, 0), TINT), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)
    story.append(PageBreak())
    story.append(_p("Finding details", "h2"))
    for f in issues:
        story.append(KeepTogether([
            _p(f"{f.code} — {f.title}", "cellb"),
            _kv_table([
                ("Document", _doc_ref(db, f.document_version_id)), ("Field", f.field or "—"),
                ("Extracted / submitted", f.extracted_value or "—"), ("Expected / compared", f.expected_value or "—"),
                ("Method", f.method or "—"), ("Reason", f.reason), ("Limitations", f.limitations or "—"),
                ("Evidence", _evidence_lines(f, internal=True)), ("Recommended action", f.recommended_action or "—"),
                ("Latest automated result", RESULT_STATES.get(f.latest_result, f.latest_result)),
                ("Reviewer", f"{f.review_state}: {f.review_reason}" if f.review_reason else f.review_state),
            ]),
            Spacer(1, 6),
        ]))
    story.append(_p("External source checks", "h2"))
    data = [[_p(h, "cellb") for h in ("#", "Source", "Mode", "Claim", "Result", "Checked")]]
    for c in checks:
        data.append([_p(str(c.id), "mono"), _p(c.source_name, "cell"), _p(c.mode, "cell"), _p(c.claim_type, "cell"),
                     _p(RESULT_STATES.get(c.status, c.status), "cell"), _p(_fmt(c.checked_at), "cell")])
    t = Table(data, colWidths=[10 * mm, 40 * mm, 22 * mm, 34 * mm, 30 * mm, 34 * mm], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE), ("BACKGROUND", (0, 0), (-1, 0), TINT)]))
    story.append(t)
    story.append(_p("Reviewer observations (internal)", "h2"))
    for n in notes:
        story.append(_p(f"{_fmt(n.created_at)} — {n.author.full_name}: {n.body}", "cell"))
    if not notes:
        story.append(_p("No observations recorded.", "small"))
    return _build(story, "Internal reviewer report", "Restricted — AICTE internal use", False, app.is_synthetic, app.reference)


def decision_pdf(db: Session, decision: Decision) -> bytes:
    app = db.get(Application, decision.application_id)
    story = [
        _p("Final Decision Record", "title"),
        _p(f"{app.reference} · Recorded {_fmt(decision.decided_at)}", "subtitle"),
        Spacer(1, 6),
        _kv_table([
            ("Institution", f"{app.institution.name} (Permanent ID {app.institution.permanent_id})"),
            ("Category", app.category.name), ("Academic year", app.academic_year),
            ("Submission version considered", f"v{decision.submission_version}"),
            ("Decision", DECISION_OUTCOMES.get(decision.outcome, decision.outcome)),
            ("Recorded by", f"{decision.decided_by.full_name}, {decision.decided_by.designation}"),
            ("Open issues at decision", f"{decision.open_issue_count}" + (" (acknowledged by the official)" if decision.acknowledged_open_issues else "")),
        ]),
        _p("Reasons recorded by the official", "h2"), _p(decision.reasons),
    ]
    if decision.conditions:
        story += [_p("Conditions", "h2"), _p(decision.conditions)]
    story += [Spacer(1, 8), _p("This decision was recorded by the authorised official named above. The software organised evidence only; "
                               "it did not make or recommend this decision.", "small")]
    return _build(story, "Final decision record", "Official record", False, app.is_synthetic, app.reference)
