"""Repeatable demo seed: synthetic institutions, users, rules and twelve scenarios.

Usage:  python -m seed.seed --reset

Workflow states (notices, approvals, institution responses, reverification) are
produced by calling the real HTTP API through FastAPI's TestClient, so every seeded
record went through the same backend logic a user would trigger.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import date, datetime, timedelta

os.environ["JOBS_MODE"] = "sync"

from sqlalchemy import select, text  # noqa: E402

from app import audit  # noqa: E402
from app.config import BASE_DIR, settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Application,
    ApplicationCategory,
    ChecklistItem,
    Document,
    Institution,
    RegulatoryRule,
    RuleVersion,
    Submission,
    SystemConfig,
    User,
    VerificationSource,
)
from app.security import hash_password  # noqa: E402
from app.services.processing import process_version  # noqa: E402
from app.services.uploads import add_version  # noqa: E402

from . import docgen as G  # noqa: E402

TODAY = date.today()
DEMO_PASSWORDS = {"reviewer": "Reviewer@2026", "institution": "Institution@2026", "admin": "Admin@2026"}
UNIV = "Southern Technological University (synthetic)"


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


# ------------------------------------------------------------------ reference data

CATEGORIES = [
    ("EOA", "Extension of Approval", "Continuation of approval for an existing institution and its approved intake."),
    ("INC", "Increase in Intake", "Request to increase intake in existing programmes."),
]

CHECKLIST = [
    ("registration_certificate", "Society / Trust registration certificate", True, False, "Certified copy of the registration of the sponsoring body."),
    ("affidavit", "Affidavit cum undertaking", True, False, "Notarised affidavit on non-judicial stamp paper."),
    ("previous_approval", "Previous approval (EoA) letter", True, False, "Most recent approval letter."),
    ("noc", "No Objection Certificate from affiliating university", True, True, "NOC valid for the academic year."),
    ("fire_safety_certificate", "Fire safety certificate", True, True, "Certificate from the competent fire authority, valid for the academic year."),
    ("accreditation_certificate", "Accreditation certificate (if accredited)", False, True, "Only if the institution claims accreditation."),
    ("faculty_list", "Faculty list", True, False, "List of faculty with qualification, designation and faculty ID."),
    ("qualification_certificate", "Faculty qualification certificates", True, False, "Degree certificate for each listed faculty member."),
    ("publication_list", "Research publication list", False, False, "Optional: publications claimed for faculty."),
    ("intake_details", "Programme-wise intake details", True, False, "Programme-wise intake with total."),
    ("floor_plan", "Floor plan", True, False, "Floor plan listing rooms and carpet area."),
    ("infrastructure_photo", "Infrastructure photographs", True, False, "Labelled photographs of laboratories and classrooms."),
    ("fee_receipt", "Processing fee receipt", True, False, "Receipt showing transaction ID and amount."),
]

PROTO_SRC = ("Prototype configuration for demonstration. Must be confirmed against the current AICTE Approval Process Handbook "
             "and applicable notifications before operational use.")

RULES = [
    ("CHK-001", "Mandatory documents per category checklist", "Completeness", "checklist_completeness", {}, "high",
     "Every mandatory checklist item for the application category must be present."),
    ("EXT-001", "Legibility and extraction confidence", "Document quality", "extraction_quality", {"min_ocr_confidence": 70}, "medium",
     "Documents must yield readable text; low-confidence OCR values are confirmed by a reviewer before use."),
    ("FLD-001", "Fire certificate mandatory details", "Completeness", "required_fields",
     {"document_type": "fire_safety_certificate", "fields": ["certificate_number", "issuing_authority", "expiry_date"]}, "medium",
     "The fire safety certificate must show certificate number, issuing authority and validity."),
    ("FLD-002", "Fee receipt mandatory details", "Completeness", "required_fields",
     {"document_type": "fee_receipt", "fields": ["transaction_id", "amount"]}, "medium",
     "The fee receipt must show a transaction ID and amount."),
    ("XDOC-001", "Institution name consistent across documents", "Cross-document consistency", "field_consistency",
     {"field": "institution_name"}, "high", "The institution name on each document must match the name declared in the application."),
    ("XDOC-002", "Permanent ID consistent across documents", "Cross-document consistency", "field_consistency",
     {"field": "permanent_id"}, "high", "The AICTE permanent ID on each document must match the application."),
    ("XDOC-003", "Intake consistent with previous approval", "Cross-document consistency", "intake_consistency", {}, "high",
     "Declared intake must agree with the intake statement and must not exceed the previously approved intake under EoA."),
    ("FAC-001", "Faculty qualifications supported by certificates", "Faculty", "faculty_qualification", {}, "high",
     "Each listed faculty member's qualification must be supported by a certificate naming that person."),
    ("PUB-001", "Publication metadata verifiable", "Research", "publication_metadata", {}, "medium",
     "Claimed publications are compared with DOI registration metadata (Crossref)."),
    ("PUB-002", "Scopus indexing claims supported by authoritative record", "Research", "publication_indexing", {"index": "Scopus"}, "medium",
     "A claim of Scopus indexing is accepted only on an authoritative Scopus record."),
    ("DUP-001", "Duplicate and near-duplicate evidence", "Integrity", "duplicates", {"image_max_hamming": 5, "text_jaccard": 0.92}, "medium",
     "The same file or image must not be used as evidence for different items."),
    ("ANM-001", "Document anomaly indicators", "Integrity", "document_anomaly", {"metadata_gap_days": 30}, "medium",
     "Indicators such as covered text, inconsistent typefaces and metadata gaps are referred for human examination."),
    ("INF-001", "Infrastructure photographic evidence", "Infrastructure", "infrastructure_evidence", {"min_photos": 2}, "medium",
     "At least two labelled photographs whose room labels appear on the floor plan."),
]

SOURCES = [
    ("crossref", "Crossref REST API", "Publication metadata registry", ["publication_metadata"], settings.crossref_mode, "https://api.crossref.org", False, 40,
     "Public API. Confirms DOI registration metadata only — not indexing or authorship by a specific person."),
    ("scopus", "Elsevier Scopus Search API", "Bibliographic index", ["publication_indexing"], "live", "https://api.elsevier.com/content/search/scopus", True, 9,
     "Requires an institutional API key (SCOPUS_API_KEY). Without it, indexing claims are routed to manual review."),
    ("aicte_records", "AICTE approval records", "Regulator records", ["previous_approval"], "disabled", "", True, 30,
     "Planned integration. No authorised connection to AICTE systems exists in this prototype."),
]


# ------------------------------------------------------------------ institutions & scenarios

def faculty_default(prefix: int):
    return [
        ("Dr. Meera Raghavan", "Ph.D. (Computer Science)", "Professor", f"FID-{prefix}01", "Doctor of Philosophy (Ph.D.) in Computer Science"),
        ("Arun Prakash", "M.E. (Computer Science)", "Assistant Professor", f"FID-{prefix}02", "Master of Engineering (M.E.) in Computer Science"),
        ("Dr. Kavitha Iyer", "Ph.D. (Electronics)", "Associate Professor", f"FID-{prefix}03", "Doctor of Philosophy (Ph.D.) in Electronics"),
    ]


PROGRAMMES = [("B.E. Computer Science and Engineering", 120), ("B.E. Electronics and Communication Engineering", 60),
              ("B.E. Mechanical Engineering", 60), ("B.E. Civil Engineering", 60), ("B.Tech. Information Technology", 60)]

INSTITUTIONS = [
    # key, name, permanent_id, city, state, type, email
    ("A", "Kaveri Valley College of Engineering", "1-4412398765", "Tiruchirappalli", "Tamil Nadu", "Private self-financing", "principal@kaveri-valley.test"),
    ("B", "Northfield Institute of Technology", "1-5521093344", "Pune", "Maharashtra", "Private self-financing", "director@northfield.test"),
    ("C", "Aranya School of Engineering", "1-6630284410", "Bhopal", "Madhya Pradesh", "Private self-financing", "principal@aranya.test"),
    ("D", "Coromandel Technical Institute", "1-7741526601", "Visakhapatnam", "Andhra Pradesh", "Private self-financing", "principal@coromandel.test"),
    ("E", "Deccan Ridge Institute of Technology", "1-8852637712", "Hyderabad", "Telangana", "Private self-financing", "principal@deccanridge.test"),
    ("F", "Lotus Bay College of Engineering", "1-9963748823", "Kochi", "Kerala", "Private self-financing", "principal@lotusbay.test"),
    ("G", "Himgiri Institute of Technology", "1-3374859934", "Dehradun", "Uttarakhand", "Private self-financing", "director@himgiri.test"),
    ("H", "Saffron Hills Institute of Technology", "1-2285960045", "Jaipur", "Rajasthan", "Private self-financing", "principal@saffronhills.test"),
]

SCENARIOS = {
    "A": "S1 complete application, all documents accepted, ready for decision; S5 publication with real DOI",
    "B": "S2 missing mandatory fire safety certificate (left un-scrutinised for the end-to-end demo)",
    "C": "S3 expired NOC rejected by the officer; S9 notice sent — institution can respond",
    "D": "S4 institution-name mismatch (NOC rejected, notice not yet sent); faculty qualification conflict; scanned registration certificate",
    "E": "S6 Scopus indexing cannot be confirmed; publication with conflicting authors/title; DOI without a record; S11 source availability",
    "F": "S7 duplicate photograph uploads; S8 potentially altered fire certificate (anomaly indicators)",
    "G": "S10 replacement documents submitted after a notice; reverification shows the checks now pass",
    "H": "S12 manual verification required (poor scan, unlabelled photo, floor plan identical to another institution's)",
}


def build_documents(key: str, name: str, pid: str, city: str, state: str) -> list[tuple[str, str, bytes, str]]:
    """Returns (document_type, title, bytes, mime) tuples for one institution's submission."""
    docs: list[tuple[str, str, bytes, str]] = []
    trust = name.split(" ")[0] + " " + name.split(" ")[1] + " Educational Trust"
    issuer, sub = f"{name}", f"{city}, {state}"
    reg = G.certificate("Registrar of Societies (synthetic)", f"Government of {state}", "CERTIFICATE OF REGISTRATION",
                        [("Registration No", f"SR/{state[:2].upper()}/2009/{pid[-4:]}"), ("Institution Name", name),
                         ("AICTE Permanent ID", pid), ("Date of Issue", "14/07/2009")],
                        f"Certified that {trust} is registered under the Societies Registration Act and has established the above institution.",
                        issued=date(2009, 7, 14), signatory="Registrar of Societies")
    if key == "D":
        reg = G.scanned(reg, seed=11)
    docs.append(("registration_certificate", "Trust registration certificate", reg, "application/pdf"))

    aff = G.certificate("Notary Public (synthetic)", f"{city}", "AFFIDAVIT CUM UNDERTAKING",
                        [("Institution Name", name), ("AICTE Permanent ID", pid), ("Date of Issue", G.d(days(-150)))],
                        "I, the Chairperson of the sponsoring body, do hereby solemnly affirm that the information furnished in the application "
                        "is true and that the institution shall abide by the applicable regulations. Deponent.", issued=days(-150),
                        signatory="Deponent / Notary")
    if key == "H":
        aff = G.scanned(aff, dpi=72, blur=1.4, noise=34, rotate=1.6, seed=5, jpeg_q=25)
    docs.append(("affidavit", "Affidavit cum undertaking", aff, "application/pdf"))

    docs.append(("previous_approval", "Extension of Approval letter 2026-27", G.certificate(
        "Regulator approval letter (synthetic test copy)", "Not issued by AICTE — test fixture", "EXTENSION OF APPROVAL",
        [("Letter No", f"F.No.SYN/1-{pid[-6:]}/2026/EOA"), ("Institution Name", name), ("AICTE Permanent ID", pid),
         ("Academic Year", "2026-27"), ("Total Approved Intake", "360"), ("Date of Issue", G.d(date(TODAY.year, 5, 15) if TODAY.month > 5 else days(-160)))],
        "Approval letter for the extension of approval of the institution and its programmes for the academic year stated above.",
        issued=days(-160), signatory="Approving officer (synthetic)"), "application/pdf"))

    noc_valid = days(-116) if key == "C" else days(400)
    noc_name = "Coromandel Technical Institute of Engineering" if key == "D" else name
    docs.append(("noc", "University NOC", G.certificate(
        UNIV, "Office of the Registrar", "NO OBJECTION CERTIFICATE",
        [("Certificate No", f"STU/NOC/{pid[-4:]}/2025"), ("Institution Name", noc_name), ("Date of Issue", G.d(days(-480) if key == "C" else days(-35))),
         ("Valid Until", G.d(noc_valid))],
        "The University has no objection to the continuation of the programmes listed in the application.",
        issued=days(-480) if key == "C" else days(-35), signatory="Registrar"), "application/pdf"))

    if key not in ("B",):
        fire_fields = [("Certificate No", f"FSC/{city[:3].upper()}/2026/{pid[-4:]}"), ("Institution Name", name),
                       ("Issuing Authority", f"District Fire Officer, {city}"), ("Date of Issue", G.d(days(-60) if key != "G" else days(-420))),
                       ("Valid Until", G.d(days(305) if key != "G" else days(-55)))]
        altered = None
        if key == "F":
            altered = {"label": "Valid Until", "value": G.d(days(670)), "modified": datetime.combine(days(-20), datetime.min.time()),
                       "producer": "QuickPDF Editor 9.2 (synthetic)"}
        docs.append(("fire_safety_certificate", "Fire safety certificate", G.certificate(
            f"District Fire and Rescue Services, {city} (synthetic)", "Fire Safety Wing", "FIRE SAFETY CERTIFICATE", fire_fields,
            "Certified that the premises were inspected and found to comply with the fire safety provisions applicable on the date of inspection.",
            issued=days(-60) if key != "G" else days(-420), altered=altered, signatory="District Fire Officer"), "application/pdf"))

    if key in ("A", "C"):
        docs.append(("accreditation_certificate", "Accreditation certificate (B.E. CSE)", G.certificate(
            "National Accreditation Panel (synthetic)", "Programme accreditation", "CERTIFICATE OF ACCREDITATION",
            [("Certificate No", f"NAP/{pid[-5:]}/CSE"), ("Institution Name", name), ("Programme", "B.E. Computer Science and Engineering"),
             ("Date of Issue", G.d(days(-700))), ("Valid Until", G.d(days(37) if key == "C" else days(500)))],
            "The programme named above is accredited for the period stated.", issued=days(-700), signatory="Member Secretary"), "application/pdf"))

    prefix = ord(key) - 60
    fac = faculty_default(prefix)
    if key == "D":
        fac[2] = ("Dr. Kavitha Iyer", "Ph.D. (Electronics)", "Associate Professor", f"FID-{prefix}03", "Master of Engineering (M.E.) in Electronics")
    docs.append(("faculty_list", "Faculty list 2026-27", G.table_doc(
        issuer, sub, "List of Faculty", [("Institution Name", name), ("AICTE Permanent ID", pid)],
        [("S.No", 50), ("Name", 80), ("Qualification", 225), ("Designation", 375), ("Faculty ID", 500)],
        [[str(i + 1), f[0], f[1], f[2], f[3]] for i, f in enumerate(fac)], issued=days(-40)), "application/pdf"))
    for i, f in enumerate(fac):
        if key == "G" and i == 1:
            continue  # certificate for this faculty member is missing in the initial submission
        docs.append(("qualification_certificate", f"Degree certificate — {f[0]}", G.certificate(
            UNIV, "Office of the Controller of Examinations", "DEGREE CERTIFICATE",
            [("Certificate No", f"STU/DEG/{2010 + i}/{4400 + prefix * 10 + i}"), ("Name of the Candidate", f[0].replace("Dr. ", "")),
             ("Degree", f[4]), ("University", UNIV), ("Date of Award", f"1{i}/08/{2012 + i}")],
            "The degree was conferred at the convocation held on the date stated.", issued=date(2012 + i, 8, 10 + i),
            signatory="Controller of Examinations"), "application/pdf"))

    if key == "A":
        pubs = [{"title": "Deep learning", "authors": "Y. LeCun, Y. Bengio, G. Hinton", "venue": "Nature", "year": "2015",
                 "doi": "10.1038/nature14539", "indexed": "Not claimed"}]
        docs.append(("publication_list", "Faculty publication list", G.publication_list(issuer, sub, name, pid, pubs, issued=days(-40)), "application/pdf"))
    if key == "E":
        pubs = [
            {"title": "Deep Residual Learning for Image Recognition", "authors": "K. He, X. Zhang, S. Ren, J. Sun",
             "venue": "2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)", "year": "2016", "doi": "10.1109/CVPR.2016.90",
             "indexed": "Scopus"},
            {"title": "Gradient based learning for handwritten digit recognition", "authors": "S. Prakash, Y. LeCun",
             "venue": "Proceedings of the IEEE", "year": "1998", "doi": "10.1109/5.726791", "indexed": "Scopus, Web of Science"},
            {"title": "Adaptive traffic signal control using edge analytics", "authors": "M. Raghavan, A. Prakash",
             "venue": "Journal of Smart Infrastructure (synthetic)", "year": "2024", "doi": "10.5555/sit.2024.00731", "indexed": "Scopus"},
        ]
        docs.append(("publication_list", "Faculty publication list", G.publication_list(issuer, sub, name, pid, pubs, issued=days(-40)), "application/pdf"))

    docs.append(("intake_details", "Programme-wise intake 2027-28", G.table_doc(
        issuer, sub, "Programme-wise Intake Details", [("Institution Name", name), ("Academic Year", "2027-28")],
        [("S.No", 50), ("Programme", 90), ("Intake", 470)],
        [[str(i + 1), p, str(n)] for i, (p, n) in enumerate(PROGRAMMES)],
        [("Total Approved Intake", "360")], issued=days(-40)), "application/pdf"))

    rooms = [("CL-201", "Computer Lab", 66), ("CR-202", "Classroom", 66), ("LIB-203", "Library", 160), ("SH-204", "Seminar Hall", 132)]
    if key == "F":
        fp = FLOOR_F_CACHE.setdefault("F", G.floor_plan(name, pid, rooms, issued=date(2024, 6, 1)))
        docs.append(("floor_plan", "Floor plan — Block A", fp, "application/pdf"))
    elif key == "H":
        docs.append(("floor_plan", "Floor plan — Block A", FLOOR_F_CACHE["F"], "application/pdf"))  # identical file to F's plan
    else:
        docs.append(("floor_plan", "Floor plan — Block A", G.floor_plan(name, pid, rooms, issued=date(2024, 6, 1)), "application/pdf"))

    if key == "F":
        photo = G.room_photo("CL-201", "Computer Lab", 61)
        docs.append(("infrastructure_photo", "Photograph — Computer Lab CL-201", photo, "image/png"))
        docs.append(("infrastructure_photo", "Photograph — Classroom CR-202", photo, "image/png"))  # same file reused
    elif key == "H":
        docs.append(("infrastructure_photo", "Photograph — Computer Lab", G.room_photo("CL-201", "Computer Lab", 81, blur=9, size=(520, 360), fmt="JPEG"), "image/jpeg"))
        docs.append(("infrastructure_photo", "Photograph — Classroom CR-202", G.room_photo("CR-202", "Classroom", 82), "image/png"))
    elif key == "D":
        docs.append(("infrastructure_photo", "Photograph — Computer Lab CL-201", G.room_photo("CL-201", "Computer Lab", 41), "image/png"))
        docs.append(("infrastructure_photo", "Photograph — Drawing Hall DH-210", G.room_photo("DH-210", "Drawing Hall", 42), "image/png"))
    else:
        docs.append(("infrastructure_photo", "Photograph — Computer Lab CL-201", G.room_photo("CL-201", "Computer Lab", ord(key)), "image/png"))
        docs.append(("infrastructure_photo", "Photograph — Classroom CR-202", G.room_photo("CR-202", "Classroom", ord(key) + 100), "image/png"))

    fee = G.certificate("Payment gateway receipt (synthetic)", "Online processing fee", "PAYMENT RECEIPT",
                        [("Transaction ID", f"TXN{TODAY.year}{pid[-6:]}"), ("Institution Name", name), ("Amount Paid", "Rs. 1,50,000"),
                         ("Date of Issue", G.d(days(-150)))], "Receipt for the processing fee of the application.", issued=days(-150),
                        signatory="System generated")
    if key == "B":
        fee = G.scanned(fee, seed=21)
    docs.append(("fee_receipt", "Processing fee receipt", fee, "application/pdf"))
    return docs


FLOOR_F_CACHE: dict[str, bytes] = {}


# ------------------------------------------------------------------ seeding


def reset_database() -> None:
    from alembic import command
    from alembic.config import Config

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    command.upgrade(cfg, "head")
    for area in ("documents", "reports"):
        shutil.rmtree(settings.storage_dir / area, ignore_errors=True)


def seed_reference(db) -> dict:
    cats = {}
    for code, nm, desc in CATEGORIES:
        c = ApplicationCategory(code=code, name=nm, description=desc)
        db.add(c)
        db.flush()
        for i, (dt, label, mand, valid, guide) in enumerate(CHECKLIST, start=1):
            db.add(ChecklistItem(category_id=c.id, document_type=dt, label=label, mandatory=mand, requires_validity=valid, guidance=guide, sort_order=i))
        cats[code] = c
    insts = {}
    for key, nm, pid, city, st, typ, _ in INSTITUTIONS:
        i = Institution(permanent_id=pid, name=nm, city=city, state=st, institution_type=typ, is_synthetic=True)
        db.add(i)
        db.flush()
        insts[key] = i
    users = {
        "anitha": User(email="anitha.raman@scrutiny.test", full_name="Anitha Raman", designation="Scrutiny Officer", role="reviewer",
                       password_hash=hash_password(DEMO_PASSWORDS["reviewer"])),
        "vikram": User(email="vikram.sethi@scrutiny.test", full_name="Vikram Sethi", designation="Scrutiny Officer", role="reviewer",
                       password_hash=hash_password(DEMO_PASSWORDS["reviewer"])),
        "admin": User(email="admin@scrutiny.test", full_name="Ravi Menon", designation="System Administrator", role="admin",
                      password_hash=hash_password(DEMO_PASSWORDS["admin"])),
    }
    for key, nm, pid, city, st, typ, email in INSTITUTIONS:
        users[f"inst{key}"] = User(email=email, full_name=f"Principal, {nm}", designation="Institution representative", role="institution",
                                   institution_id=insts[key].id, password_hash=hash_password(DEMO_PASSWORDS["institution"]))
    for u in users.values():
        db.add(u)
    db.flush()
    for code, title, group, ctype, params, sev, desc in RULES:
        r = RegulatoryRule(code=code, title=title, group=group)
        db.add(r)
        db.flush()
        cats_for = ["EOA"] if code == "XDOC-003" else []
        if code == "INF-001":
            db.add(RuleVersion(rule_id=r.id, version=1, description=desc.replace("two", "one"), source_reference=PROTO_SRC, categories=cats_for,
                               check_type=ctype, params={"min_photos": 1}, severity=sev, effective_from=date(2024, 1, 1), effective_to=date(2025, 12, 31),
                               is_active=False, change_note="Initial prototype rule", created_by_id=users["admin"].id))
            db.add(RuleVersion(rule_id=r.id, version=2, description=desc, source_reference=PROTO_SRC, categories=cats_for, check_type=ctype,
                               params=params, severity=sev, effective_from=date(2026, 1, 1), change_note="Raised minimum photographs from 1 to 2",
                               created_by_id=users["admin"].id))
        else:
            db.add(RuleVersion(rule_id=r.id, version=1, description=desc, source_reference=PROTO_SRC, categories=cats_for, check_type=ctype,
                               params=params, severity=sev, effective_from=date(2024, 1, 1), change_note="Initial prototype rule",
                               created_by_id=users["admin"].id))
    r = RegulatoryRule(code="VAL-001", title="Time-bound certificates valid on reference date", group="Validity")
    db.add(r)
    db.flush()
    db.add(RuleVersion(rule_id=r.id, version=1, description="Certificates that carry a validity period must be valid on the scrutiny reference date.",
                       source_reference=PROTO_SRC, check_type="validity", params={"expiring_soon_days": 30}, severity="high",
                       effective_from=date(2024, 1, 1), effective_to=date(2025, 12, 31), is_active=False, change_note="Initial prototype rule",
                       created_by_id=users["admin"].id))
    db.add(RuleVersion(rule_id=r.id, version=2, description="Certificates that carry a validity period must be valid on the scrutiny reference date; "
                       "those expiring within 60 days are flagged for follow-up.", source_reference=PROTO_SRC, check_type="validity",
                       params={"expiring_soon_days": 60}, severity="high", effective_from=date(2026, 1, 1),
                       change_note="Expiring-soon window widened from 30 to 60 days", created_by_id=users["admin"].id))
    for code, nm, typ, claims, mode, url, creds, rl, notes in SOURCES:
        db.add(VerificationSource(code=code, name=nm, source_type=typ, claim_types=claims, mode=mode, base_url=url, requires_credentials=creds,
                                  rate_limit_per_minute=rl, timeout_seconds=settings.crossref_timeout, notes=notes))
    db.add(SystemConfig(key="ocr_confirmation_threshold", value={"value": 75}, description="OCR word-confidence below which extracted key values need reviewer confirmation"))
    db.add(SystemConfig(key="expiry_reference_date", value={"value": ""}, description="Reference date for validity checks (empty = today)"))
    db.add(SystemConfig(key="notice_response_days", value={"value": 15}, description="Default response window for deficiency notices"))
    audit.record(db, "seed.reference_data", "system", "seed", summary="Synthetic reference data seeded")
    db.commit()
    return {"cats": cats, "insts": insts, "users": users}


def seed_applications(db, ref) -> dict:
    apps = {}
    assign = {"A": "anitha", "B": "anitha", "C": "anitha", "D": "anitha", "G": "anitha", "E": "vikram", "F": "vikram", "H": "vikram"}
    for n, (key, nm, pid, city, st, typ, _) in enumerate(INSTITUTIONS, start=1):
        cat = ref["cats"]["INC" if key == "E" else "EOA"]
        declared_intake = "420" if key == "E" else "360"
        a = Application(reference=f"{cat.code}-2027-{n:05d}", institution_id=ref["insts"][key].id, category_id=cat.id, academic_year="2027-28",
                        status="submitted", assigned_reviewer_id=ref["users"][assign[key]].id, is_synthetic=True, scenario=SCENARIOS[key],
                        declared={"institution_name": nm, "permanent_id": pid, "approved_intake": declared_intake},
                        submitted_at=datetime.combine(days(-30 + n), datetime.min.time()).astimezone())
        db.add(a)
        db.flush()
        db.add(Submission(application_id=a.id, version=1, kind="initial", note="Synthetic demo submission"))
        for dtype, title, data, mime in build_documents(key, nm, pid, city, st):
            doc = Document(application_id=a.id, document_type=dtype, title=title)
            db.add(doc)
            db.flush()
            fname = title.lower().replace(" — ", "-").replace(" ", "-").replace("/", "-") + (".pdf" if mime == "application/pdf" else ".png" if mime == "image/png" else ".jpg")
            process_version(db, add_version(db, doc, data, mime, fname, None, 1))
        audit.record(db, "application.imported", "application", a.id, application_id=a.id,
                     summary=f"{a.reference} imported from synthetic demo fixture ({SCENARIOS[key][:60]})")
        db.commit()
        apps[key] = a
        print(f"  {a.reference}  {nm}: {len(a.documents)} documents")
    return apps


class Api:
    def __init__(self, client, email, password):
        self.c = client
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text  # the client keeps the session cookie

    def _h(self):
        return {"X-Requested-With": "pramaan"}

    def get(self, path, **kw):
        r = self.c.get(path, **kw)
        assert r.status_code < 400, (path, r.status_code, r.text[:400])
        return r.json()

    def post(self, path, json=None, **kw):
        r = self.c.post(path, json=json, headers=self._h(), **kw)
        assert r.status_code < 400, (path, r.status_code, r.text[:600])
        return r.json()


def drive_workflows(apps) -> None:
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    anitha = Api(TestClient(fastapi_app), "anitha.raman@scrutiny.test", DEMO_PASSWORDS["reviewer"])
    vikram = Api(TestClient(fastapi_app), "vikram.sethi@scrutiny.test", DEMO_PASSWORDS["reviewer"])

    for key in ("A", "C", "D", "G"):
        anitha.post(f"/api/reviewer/applications/{apps[key].id}/verify")
    for key in ("E", "F", "H"):
        vikram.post(f"/api/reviewer/applications/{apps[key].id}/verify")
    print("  initial verification runs completed")

    def send_notice(api, app_id, statuses):
        cands = api.get(f"/api/reviewer/notice-candidates/{app_id}")
        items = [{"finding_id": c["finding_id"], "title": c["suggested_title"], "description": c["suggested_description"],
                  "corrective_action": c["suggested_action"]} for c in cands["items"] if c["status"] in statuses]
        return api.post(f"/api/reviewer/applications/{app_id}/notices", json={"items": items, "response_deadline": cands["default_deadline"],
                        "cover_note": "Please address the item(s) below within the response window."})

    def docs(api, app_id):
        return api.get(f"/api/reviewer/applications/{app_id}")["documents"]

    # A: every document accepted by the officer -> moved to decision
    for d in docs(anitha, apps["A"].id):
        anitha.post(f"/api/reviewer/document-versions/{d['version_id']}/review", json={"action": "accept", "note": ""})
    anitha.post(f"/api/reviewer/applications/{apps['A'].id}/ready-for-decision")
    print("  Kaveri Valley: all documents accepted, ready for decision")

    # C: expired NOC rejected with a reason and sent in a notice (S3, S9)
    noc = next(d for d in docs(anitha, apps["C"].id) if d["document_type"] == "noc")
    anitha.post(f"/api/reviewer/document-versions/{noc['version_id']}/review",
                json={"action": "reject", "note": "The NOC expired before the academic year under consideration; a currently valid NOC is required."})
    n = send_notice(anitha, apps["C"].id, ("rejected", "missing"))
    print(f"  {n['reference']} sent to Aranya (awaiting response)")

    # D: name mismatch on the NOC rejected; notice not yet sent (officer demo)
    noc = next(d for d in docs(anitha, apps["D"].id) if d["document_type"] == "noc")
    anitha.post(f"/api/reviewer/document-versions/{noc['version_id']}/review",
                json={"action": "reject", "note": "The institution name on the NOC differs from the name declared in the application."})
    anitha.post(f"/api/reviewer/applications/{apps['D'].id}/notes", json={"body": "Check whether the institution was renamed."})

    # G: notice sent, institution responds with replacement documents, reverification (S10)
    n = send_notice(anitha, apps["G"].id, ("expired", "missing", "mismatch"))
    inst = Api(TestClient(fastapi_app), "director@himgiri.test", DEMO_PASSWORDS["institution"])
    notice = inst.get(f"/api/institution/notices/{n['id']}")
    name, pid, city = INSTITUTIONS[6][1], INSTITUTIONS[6][2], INSTITUTIONS[6][3]
    for it in notice["items"]:
        if it["document_type"] == "fire_safety_certificate":
            data = G.certificate(f"District Fire and Rescue Services, {city} (synthetic)", "Fire Safety Wing", "FIRE SAFETY CERTIFICATE",
                                 [("Certificate No", f"FSC/{city[:3].upper()}/2026/{pid[-4:]}R"), ("Institution Name", name),
                                  ("Issuing Authority", f"District Fire Officer, {city}"), ("Date of Issue", G.d(days(-6))), ("Valid Until", G.d(days(359)))],
                                 "Certified that the premises were re-inspected and found to comply.", issued=days(-6), signatory="District Fire Officer")
            inst.post(f"/api/institution/notice-items/{it['id']}/response", data={"response_text": "Renewed fire safety certificate attached."},
                      files={"file": ("fire-certificate-renewed.pdf", data, "application/pdf")}, json=None)
        elif it["document_type"] == "qualification_certificate":
            fac = faculty_default(ord("G") - 60)[1]
            data = G.certificate(UNIV, "Office of the Controller of Examinations", "DEGREE CERTIFICATE",
                                 [("Certificate No", "STU/DEG/2011/4512"), ("Name of the Candidate", fac[0]), ("Degree", fac[4]),
                                  ("University", UNIV), ("Date of Award", "11/08/2013")], "The degree was conferred at the convocation.",
                                 issued=date(2013, 8, 11), signatory="Controller of Examinations")
            inst.post(f"/api/institution/notice-items/{it['id']}/response", data={"response_text": "Degree certificate of Arun Prakash attached."},
                      files={"file": ("degree-arun-prakash.pdf", data, "application/pdf")}, json=None)
        else:
            inst.post(f"/api/institution/notice-items/{it['id']}/response", data={"response_text": "Clarification provided."}, json=None)
    inst.post(f"/api/institution/notices/{n['id']}/resubmit")
    print(f"  {n['reference']}: Himgiri responded and reverification completed")

    # H: uncertain documents flagged for manual verification (S12)
    for d in docs(vikram, apps["H"].id):
        if d["auto_status"] in ("manual_verification_required", "unreadable"):
            vikram.post(f"/api/reviewer/document-versions/{d['version_id']}/review",
                        json={"action": "manual", "note": "Scan quality is poor; compare with the original before deciding."})
    vikram.post(f"/api/reviewer/applications/{apps['H'].id}/notes", json={"body": "Floor plan is byte-identical to another institution's submission."})
    print("  Saffron Hills: documents flagged for manual verification")

    # Kaveri Valley: a second application left as a draft to show the institution's own workflow
    k = Api(TestClient(fastapi_app), "principal@kaveri-valley.test", DEMO_PASSWORDS["institution"])
    draft = k.post("/api/institution/applications", json={"category_code": "INC", "academic_year": "2027-28",
                   "declared_institution_name": INSTITUTIONS[0][1], "declared_permanent_id": INSTITUTIONS[0][2], "declared_approved_intake": 420})
    for dtype, title, data, mime in build_documents("A", INSTITUTIONS[0][1], INSTITUTIONS[0][2], INSTITUTIONS[0][3], INSTITUTIONS[0][4])[:3]:
        k.post(f"/api/institution/applications/{draft['id']}/documents", data={"document_type": dtype},
               files={"file": (title.lower().replace(" ", "-")[:40] + ".pdf", data, mime)}, json=None)
    print(f"  {draft['reference']}: draft created by Kaveri Valley (3 documents uploaded, not submitted)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop all tables and storage, then seed")
    args = ap.parse_args(argv)
    if not args.reset:
        with SessionLocal() as db:
            if db.execute(select(User).limit(1)).first():
                print("Database already contains data. Re-run with --reset to rebuild the demo data set.")
                return 1
    print("Resetting database and storage…")
    reset_database()
    with SessionLocal() as db:
        ref = seed_reference(db)
        print("Seeding synthetic applications…")
        apps = seed_applications(db, ref)
    print("Driving workflows through the API…")
    drive_workflows(apps)
    print("\nDemo accounts (synthetic):")
    print(f"  Scrutiny officer        anitha.raman@scrutiny.test / {DEMO_PASSWORDS['reviewer']}")
    print(f"  Scrutiny officer        vikram.sethi@scrutiny.test / {DEMO_PASSWORDS['reviewer']}")
    print(f"  Administrator           admin@scrutiny.test / {DEMO_PASSWORDS['admin']}")
    for key, nm, *_rest, email in INSTITUTIONS:
        print(f"  Institution ({key})       {email} / {DEMO_PASSWORDS['institution']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
