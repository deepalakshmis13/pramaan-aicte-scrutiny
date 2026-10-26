from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import app_id, inst


def test_login_success_and_failure():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "anitha.raman@scrutiny.test", "password": "wrong"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "ANITHA.raman@scrutiny.test", "password": "Reviewer@2026"})
    assert r.status_code == 200
    assert "password_hash" not in r.json()["user"]
    assert "httponly" in r.headers["set-cookie"].lower()


def test_session_probe_when_signed_out():
    r = TestClient(app).get("/api/auth/me")
    assert r.status_code == 200 and r.json()["user"] is None


def test_unauthenticated_api_rejected():
    assert TestClient(app).get("/api/reviewer/applications").status_code == 401


def test_csrf_header_required_for_mutations(anitha):
    aid = app_id(anitha, "00001")
    r = anitha.c.post(f"/api/reviewer/applications/{aid}/notes", json={"body": "x"})
    assert r.status_code == 403


def test_role_separation(anitha, admin):
    i = inst("principal@aranya.test")
    assert i.get("/api/reviewer/dashboard").status_code == 403
    assert admin.get("/api/reviewer/applications").status_code == 403  # admin has no document access
    assert anitha.get("/api/admin/users").status_code == 403
    assert i.get("/api/admin/rules").status_code == 403


def test_institution_cannot_see_other_institutions(anitha):
    other = app_id(anitha, "00001")  # Kaveri Valley
    i = inst("principal@aranya.test")
    assert i.get(f"/api/institution/applications/{other}").status_code == 404
    mine = i.get("/api/institution/applications").json()
    assert len(mine) == 1 and mine[0]["reference"].endswith("00003")


def test_drafts_are_private_to_the_institution(vikram):
    k = inst("principal@kaveri-valley.test")
    draft = next(a for a in k.get("/api/institution/applications").json() if a["status"] == "draft")
    assert vikram.get(f"/api/reviewer/applications/{draft['id']}").status_code == 404
    assert all(a["status"] != "draft" for a in vikram.get("/api/reviewer/applications", params={"page_size": 100}).json()["items"])
    assert inst("principal@aranya.test").get(f"/api/institution/applications/{draft['id']}").status_code == 404


def test_institution_views_hide_internal_data(anitha):
    i = inst("principal@aranya.test")
    notices = i.get("/api/institution/notices").json()
    n = i.get(f"/api/institution/notices/{notices[0]['id']}").json()
    for it in n["items"]:
        assert "finding" not in it and "outcome_note" not in it
    assert "approval_remarks" not in n and "row_version" not in n
    a = i.get(f"/api/institution/applications/{n['application_id']}").json()
    assert "priority" not in a
    assert all(not ({"extracted_text", "quality", "auto_reason", "open_findings", "history"} & set(d)) for d in a["documents"])


def test_invalid_ids(anitha):
    assert anitha.get("/api/reviewer/applications/999999").status_code == 404
    assert anitha.get("/api/reviewer/findings/999999").status_code == 404
    assert anitha.get("/api/reviewer/notices/999999").status_code == 404
    assert anitha.get("/api/reviewer/applications/abc").status_code == 422


def test_upload_validation(anitha):
    k = inst("principal@kaveri-valley.test")
    draft = next(a for a in k.get("/api/institution/applications").json() if a["status"] == "draft")
    url = f"/api/institution/applications/{draft['id']}/documents"
    bad = k.post(url, data={"document_type": "noc"}, files={"file": ("evil.exe", b"MZ\x90\x00 not a pdf", "application/pdf")})
    assert bad.status_code == 415
    assert k.post(url, data={"document_type": "noc"}, files={"file": ("x.pdf", b"", "application/pdf")}).status_code == 400
    assert k.post(url, data={"document_type": "noc"}, files={"file": ("x.pdf", b"%PDF-1.4 garbage", "application/pdf")}).status_code == 400
    assert k.post(url, data={"document_type": "not_on_checklist"}, files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 422
    # officers cannot upload into an institution's application
    assert anitha.post(url, data={"document_type": "noc"}, files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 403


def test_storage_keys_reject_traversal():
    import pytest

    from app import storage

    with pytest.raises(ValueError):
        storage.path_for("documents/1/../../../etc/passwd")
    assert storage.safe_display_name("../../etc/pa ss<wd>.pdf") == "pa ss_wd_.pdf"


def test_audit_chain_detects_tampering():
    from sqlalchemy import select, text

    from app import audit
    from app.db import SessionLocal
    from app.models import AuditEvent

    with SessionLocal() as db:
        assert audit.verify_chain(db)["ok"]
        ev = db.execute(select(AuditEvent).order_by(AuditEvent.id).limit(1).offset(3)).scalar_one()
        original = ev.summary
        db.execute(text("UPDATE audit_events SET summary='tampered' WHERE id=:i"), {"i": ev.id})
        db.commit()
        res = audit.verify_chain(db)
        assert not res["ok"] and res["broken_at_event_id"] == ev.id
        db.execute(text("UPDATE audit_events SET summary=:s WHERE id=:i"), {"s": original, "i": ev.id})
        db.commit()
        assert audit.verify_chain(db)["ok"]
