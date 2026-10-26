"""End-to-end API journey: institution creates and submits an application -> officer verifies,
accepts/rejects documents -> sends a notice -> the institution sees it and responds -> officer
accepts the corrected document -> decision. History is preserved throughout."""
from datetime import date, timedelta

from seed import docgen as G
from seed.seed import build_documents
from tests.conftest import inst

NORTHFIELD = ("Northfield Institute of Technology", "1-5521093344", "Pune", "Maharashtra")


def _create_and_submit(i, *, expired_noc: bool):
    r = i.post("/api/institution/applications", json={"category_code": "INC", "academic_year": "2028-29",
               "declared_institution_name": NORTHFIELD[0], "declared_permanent_id": NORTHFIELD[1], "declared_approved_intake": 360})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "draft"
    # submitting an empty draft is refused with a list of what is missing
    r = i.post(f"/api/institution/applications/{a['id']}/submit")
    assert r.status_code == 422 and "Upload the" in r.json()["error"]["message"]
    docs = build_documents("B", *NORTHFIELD)
    if expired_noc:
        noc = G.certificate("Southern Technological University (synthetic)", "Registrar", "NO OBJECTION CERTIFICATE",
                            [("Certificate No", "STU/NOC/3344/2024"), ("Institution Name", NORTHFIELD[0]),
                             ("Date of Issue", G.d(date.today() - timedelta(days=500))), ("Valid Until", G.d(date.today() - timedelta(days=30)))],
                            "No objection.", issued=date.today() - timedelta(days=500))
        docs = [(t, ti, noc if t == "noc" else d, m) for t, ti, d, m in docs]
    # B's set lacks a fire certificate: add one so every mandatory item is present
    docs.append(("fire_safety_certificate", "Fire safety certificate", G.certificate(
        "District Fire and Rescue Services, Pune (synthetic)", "Fire Safety Wing", "FIRE SAFETY CERTIFICATE",
        [("Certificate No", "FSC/PUN/2026/3344"), ("Institution Name", NORTHFIELD[0]), ("Issuing Authority", "District Fire Officer, Pune"),
         ("Date of Issue", G.d(date.today() - timedelta(days=20))), ("Valid Until", G.d(date.today() + timedelta(days=340)))],
        "Inspected.", issued=date.today()), "application/pdf"))
    for dtype, title, data, mime in docs:
        r = i.post(f"/api/institution/applications/{a['id']}/documents", data={"document_type": dtype},
                   files={"file": (f"{dtype}.{'pdf' if mime == 'application/pdf' else 'png'}", data, mime)})
        assert r.status_code == 201, r.text
    rows = r.json()
    assert rows["missing"] == []
    # replace and remove are allowed while still a draft
    fee = next(d for d in rows["documents"] if d["document_type"] == "fee_receipt")
    r = i.post(f"/api/institution/applications/{a['id']}/documents", data={"document_type": "fee_receipt", "replace_document_id": str(fee["document_id"])},
               files={"file": ("fee.pdf", docs[-2][2], "application/pdf")})
    assert next(d for d in r.json()["documents"] if d["document_id"] == fee["document_id"])["version_no"] == 2
    r = i.post(f"/api/institution/applications/{a['id']}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"
    return a["id"]


def test_institution_to_officer_journey(anitha, vikram):
    i = inst("director@northfield.test")
    aid = _create_and_submit(i, expired_noc=True)

    # appears in the officer queue; drafts never do
    queue = anitha.get("/api/reviewer/applications", params={"page_size": 100}).json()["items"]
    row = next(x for x in queue if x["id"] == aid)
    assert row["status"] == "submitted" and row["next_action"] == "Run Verify Application."

    # Verify Application runs the real engine
    run = anitha.post(f"/api/reviewer/applications/{aid}/verify").json()
    assert run["status"] == "completed"
    app = anitha.get(f"/api/reviewer/applications/{aid}").json()
    noc = next(d for d in app["documents"] if d["document_type"] == "noc")
    assert noc["auto_status"] == "expired" and noc["review_status"] == "pending"
    fee = next(d for d in app["documents"] if d["document_type"] == "fee_receipt")
    assert fee["text_method"] == "ocr"  # scanned receipt went through OCR

    # reject needs a meaningful reason; accept of a flagged document needs a note
    v = noc["version_id"]
    assert anitha.post(f"/api/reviewer/document-versions/{v}/review", json={"action": "reject", "note": "bad"}).status_code == 422
    assert anitha.post(f"/api/reviewer/document-versions/{v}/review", json={"action": "accept", "note": ""}).status_code == 422
    r = anitha.post(f"/api/reviewer/document-versions/{v}/review", json={"action": "reject", "note": "The NOC expired before the academic year; submit a valid NOC."})
    assert r.json()["review_status"] == "rejected"
    for d in app["documents"]:
        if d["document_type"] != "noc":
            note = "Checked manually against the original document." if d["open_findings"] else ""
            assert anitha.post(f"/api/reviewer/document-versions/{d['version_id']}/review", json={"action": "accept", "note": note}).status_code == 200
    # cannot move to decision while a document is rejected
    assert anitha.post(f"/api/reviewer/applications/{aid}/ready-for-decision").status_code == 409

    # one-step notice: candidates -> send
    cands = anitha.get(f"/api/reviewer/notice-candidates/{aid}").json()
    rej = next(c for c in cands["items"] if c["status"] == "rejected")
    assert "expired" in rej["suggested_description"]
    items = [{"finding_id": c["finding_id"], "title": c["suggested_title"], "description": c["suggested_description"],
              "corrective_action": c["suggested_action"]} for c in cands["items"]]
    past = anitha.post(f"/api/reviewer/applications/{aid}/notices", json={"items": items, "response_deadline": "2020-01-01"})
    assert past.status_code == 422
    sent = anitha.post(f"/api/reviewer/applications/{aid}/notices", json={"items": items, "response_deadline": cands["default_deadline"]})
    assert sent.status_code == 201, sent.text
    n = sent.json()
    assert n["status"] == "issued" and n["institution"] == NORTHFIELD[0] and n["delivery"]["status"] == "delivered"
    assert anitha.post(f"/api/reviewer/applications/{aid}/notices", json={"items": items, "response_deadline": cands["default_deadline"]}).status_code == 409

    # the notice reaches the correct institution — and only that institution
    notices = i.get("/api/institution/notices").json()
    assert any(x["id"] == n["id"] and x["status"] == "issued" for x in notices)
    dash = i.get("/api/institution/dashboard").json()
    assert any(x.get("notice_id") == n["id"] for x in dash["action_required"])
    assert any(x["link"] == f"/institution/notices/{n['id']}" for x in i.get("/api/notifications").json()["items"])
    assert inst("principal@aranya.test").get(f"/api/institution/notices/{n['id']}").status_code == 404
    view = i.get(f"/api/institution/notices/{n['id']}").json()
    noc_item = next(it for it in view["items"] if "NOC" in it["title"] or "No Objection" in it["document_reference"] or it["document_type"] == "noc")
    assert noc_item["upload_target"]["mode"] == "replace"
    app_view = i.get(f"/api/institution/applications/{aid}").json()
    inst_noc = next(d for d in app_view["documents"] if d["document_type"] == "noc")
    assert inst_noc["status"] == "rejected" and "expired" in inst_noc["status_reason"]
    assert "auto_reason" not in inst_noc and "open_findings" not in inst_noc
    seen = anitha.get("/api/reviewer/notices").json()
    assert next(x for x in seen if x["id"] == n["id"])["delivery"]["status"] in ("delivered", "seen")

    # institution responds with a corrected NOC and resubmits
    good = G.certificate("Southern Technological University (synthetic)", "Registrar", "NO OBJECTION CERTIFICATE",
                         [("Certificate No", "STU/NOC/3344/2026"), ("Institution Name", NORTHFIELD[0]),
                          ("Date of Issue", G.d(date.today() - timedelta(days=5))), ("Valid Until", G.d(date.today() + timedelta(days=400)))],
                         "No objection.", issued=date.today())
    for it in view["items"]:
        files = {"file": ("noc-2026.pdf", good, "application/pdf")} if it["id"] == noc_item["id"] else None
        r = i.post(f"/api/institution/notice-items/{it['id']}/response", data={"response_text": "Corrected document attached."}, files=files)
        assert r.status_code == 201, r.text
    assert i.post(f"/api/institution/notices/{n['id']}/resubmit").json()["submission_version"] == 2

    # officer sees the reverified replacement, accepts it, the notice items close
    app = anitha.get(f"/api/reviewer/applications/{aid}").json()
    assert app["status"] == "response_received"
    noc2 = next(d for d in app["documents"] if d["document_type"] == "noc")
    assert noc2["version_no"] == 2 and noc2["review_status"] == "pending" and noc2["auto_status"] in ("checks_passed", "external_unavailable")
    r = anitha.post(f"/api/reviewer/document-versions/{noc2['version_id']}/review", json={"action": "accept", "note": ""}).json()
    assert r["resolved_findings"]
    for it in [x for x in anitha.get(f"/api/reviewer/applications/{aid}/responses").json()[0]["items"] if x["status"] == "responded"]:
        anitha.post(f"/api/reviewer/notice-items/{it['id']}/outcome", json={"outcome": "resolved", "note": "Clarification accepted after review."})
    app = anitha.get(f"/api/reviewer/applications/{aid}").json()
    assert app["status"] == "under_scrutiny" and app["progress"]["accepted"] == app["progress"]["total"]
    history = next(d for d in app["documents"] if d["document_type"] == "noc")["history"]
    assert [h["action"] for h in history] == ["rejected", "accepted"]  # decision history kept across versions

    # decision is recorded by an officer, never by the automated run
    assert anitha.post(f"/api/reviewer/applications/{aid}/ready-for-decision").status_code == 200
    r = vikram.post(f"/api/reviewer/applications/{aid}/decision", json={"outcome": "approved", "reasons": "All documents verified after correction."})
    if r.status_code == 409:
        r = vikram.post(f"/api/reviewer/applications/{aid}/decision", json={"outcome": "approved", "reasons": "All documents verified after correction.",
                                                                              "acknowledge_open_issues": True})
    assert r.status_code == 201, r.text
    assert i.get(f"/api/institution/applications/{aid}").json()["status"] == "decided"
    pp = anitha.get(f"/api/reviewer/applications/{aid}/passport").json()["events"]
    assert sum(1 for e in pp if e["kind"] == "submission") == 2


def test_manual_verification_and_field_confirmation(vikram):
    from tests.conftest import app_id

    aid = app_id(vikram, "00008")
    app = vikram.get(f"/api/reviewer/applications/{aid}").json()
    manual = [d for d in app["documents"] if d["review_status"] == "manual"]
    assert manual, "seed flags uncertain documents for manual verification"
    d = manual[0]
    detail = vikram.get(f"/api/reviewer/applications/{aid}/documents/{d['document_id']}").json()
    low = [f for f in detail["selected_version"]["fields"] if f["needs_confirmation"]]
    for f in low:
        r = vikram.post(f"/api/reviewer/fields/{f['id']}/confirm", json={"value": f["value"], "reason": "Read from the original"})
        assert r.json()["confirmed_value"] == f["value"]
    note = "Compared with the original; values confirmed manually."
    r = vikram.post(f"/api/reviewer/document-versions/{d['version_id']}/review", json={"action": "accept", "note": note})
    assert r.status_code == 200
    after = next(x for x in vikram.get(f"/api/reviewer/applications/{aid}").json()["documents"] if x["document_id"] == d["document_id"])
    assert after["review_status"] == "accepted" and after["manually_verified"]


def test_internal_report_hidden_from_institution(anitha):
    from tests.conftest import app_id

    aid = app_id(anitha, "00004")
    rep = anitha.post(f"/api/reviewer/applications/{aid}/reports/internal").json()
    assert anitha.get(f"/api/reviewer/reports/{rep['id']}/download").content.startswith(b"%PDF")
    assert inst("principal@coromandel.test").get(f"/api/institution/reports/{rep['id']}/download").status_code == 404


def test_dashboard_and_export(anitha):
    d = anitha.get("/api/reviewer/dashboard").json()
    assert len(d["stages"]) == 6 and d["priority_queue"]
    top = d["priority_queue"][0]
    assert top["priority"]["score"] == sum(r["weight"] for r in top["priority"]["reasons"])  # score is fully explained
    csv = anitha.get("/api/reviewer/applications/export.csv")
    assert csv.status_code == 200 and csv.text.startswith("reference,institution")
