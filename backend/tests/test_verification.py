import json

import httpx

from app.services import extraction as X
from app.services.connectors import crossref, scopus
from seed import docgen as G
from tests.conftest import app_id

DEEP = {"title": ["Deep learning"], "container-title": ["Nature"], "issued": {"date-parts": [[2015, 5, 27]]},
        "author": [{"family": "LeCun"}, {"family": "Bengio"}, {"family": "Hinton"}], "publisher": "Springer"}


def _transport(status=200, body=None, exc=None):
    def handler(request):
        if exc:
            raise exc
        return httpx.Response(status, json={"message": body} if body else {})
    return httpx.MockTransport(handler)


def test_crossref_live_match():
    claim = {"doi": "10.1038/nature14539", "title": "Deep learning", "authors": "Y. LeCun, Y. Bengio, G. Hinton", "year": "2015", "venue": "Nature"}
    r = crossref.check_publication(claim, "live", transport=_transport(body=DEEP))
    assert r.status == "verified" and r.mode == "live" and all(f["match"] for f in r.fields_compared)


def test_crossref_live_author_mismatch():
    claim = {"doi": "10.1038/nature14539", "title": "Deep learning", "authors": "S. Prakash, Y. LeCun", "year": "2015"}
    r = crossref.check_publication(claim, "live", transport=_transport(body=DEEP))
    assert r.status == "mismatch" and "prakash" in json.dumps(r.fields_compared).lower()


def test_crossref_absence_is_not_a_mismatch():
    r = crossref.check_publication({"doi": "10.5555/none"}, "live", transport=_transport(status=404))
    assert r.status == "manual_review" and "does not prove" in r.explanation


def test_crossref_unreachable_is_source_unavailable():
    r = crossref.check_publication({"doi": "10.1/x"}, "live", transport=_transport(exc=httpx.ConnectError("down")))
    assert r.status == "source_unavailable"
    r = crossref.check_publication({"doi": "10.1/x"}, "live", transport=_transport(status=503))
    assert r.status == "source_unavailable"


def test_simulated_never_verified():
    claim = {"doi": "10.1038/nature14539", "title": "Deep learning", "authors": "Y. LeCun, Y. Bengio, G. Hinton", "year": "2015"}
    r = crossref.check_publication(claim, "simulated")
    assert r.status == "simulated" and r.explanation.startswith("SIMULATED")


def test_scopus_without_credentials():
    r = scopus.check_indexing({"doi": "10.1109/CVPR.2016.90"}, "live")
    assert r.status == "source_unavailable" and r.mode == "not_configured"


def test_indexing_claim_routes_to_manual_review(vikram):
    aid = app_id(vikram, "00005")
    fs = vikram.get(f"/api/reviewer/applications/{aid}/findings", params={"category": "external"}).json()
    idx = [f for f in fs if f["title"].startswith("Indexing claim")]
    assert len(idx) == 3 and all(f["status"] == "manual_review" for f in idx)
    assert not any(f["status"] == "verified" for f in fs if f["title"].startswith("Publication metadata"))


def test_native_extraction_and_bbox():
    pdf = G.certificate("Issuer", "Sub", "NO OBJECTION CERTIFICATE", [("Certificate No", "STU/NOC/1/2025"), ("Institution Name", "Test Institute"),
                        ("Valid Until", "01/02/2030")], issued=__import__("datetime").date(2025, 1, 1))
    res = X.extract(pdf, "application/pdf")
    fields = {f.name: f for f in X.extract_fields(res.lines)}
    assert res.method == "native"
    assert fields["expiry_date"].value == "01/02/2030" and fields["institution_name"].value == "Test Institute"
    x0, y0, x1, y1 = fields["expiry_date"].bbox
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_ocr_extraction_of_scanned_pdf():
    from datetime import date

    pdf = G.scanned(G.certificate("Issuer", "Sub", "FIRE SAFETY CERTIFICATE", [("Certificate No", "FSC/AB/2026/1234"), ("Valid Until", "31/12/2027")],
                                  issued=date(2026, 1, 1)))
    res = X.extract(pdf, "application/pdf")
    fields = {f.name: f for f in X.extract_fields(res.lines)}
    assert res.method == "ocr" and res.mean_conf and res.mean_conf > 60
    assert fields["expiry_date"].value == "31/12/2027"


def test_seeded_scenarios(vikram):
    def issues(suffix):
        aid = app_id(vikram, suffix)
        return [f for f in vikram.get(f"/api/reviewer/applications/{aid}/findings", params={"issues_only": True}).json()
                if f["status"] not in ("verified", "resolved")]

    assert issues("00001") == []                                                     # S1 complete
    assert any(f["status"] == "expired" and "NOC" in f["title"] for f in issues("00003"))  # S3
    d = issues("00004")
    assert any(f["status"] == "mismatch" and f["field"] == "institution_name" for f in d)  # S4
    assert any(f["title"].startswith("Qualification conflict") for f in d)
    f6 = issues("00006")
    assert any(f["title"].startswith("Identical file") for f in f6)                     # S7
    titles = " ".join(f["title"] for f in f6)
    assert "Font inconsistency" in titles and "Opaque box" in titles and "modified long after creation" in titles
    assert any(f["category"] == "anomaly" and f["certainty"] == "suspected" for f in f6)  # S8 indicator, not proof
    h = issues("00008")
    assert any(f["title"].startswith("File also submitted in another application") for f in h)
    assert any(f["category"] == "extraction" for f in h)                               # S12 low-confidence OCR


def test_rule_versioning_preserves_history(admin, vikram):
    rules = admin.get("/api/admin/rules").json()["rules"]
    inf = next(r for r in rules if r["code"] == "INF-001")
    cur = inf["current"]
    r = admin.post(f"/api/admin/rules/{inf['id']}/versions", json={
        "description": cur["description"], "source_reference": cur["source_reference"], "categories": [], "check_type": cur["check_type"],
        "params": {"min_photos": 3}, "severity": "medium", "effective_from": "2026-01-01", "change_note": "Test: three photographs"})
    assert r.status_code == 201 and r.json()["version"] == 3
    aid = app_id(vikram, "00001")
    old = [f for f in vikram.get(f"/api/reviewer/applications/{aid}/findings").json() if f["rule_code"] == "INF-001"]
    assert all(f["rule_version"] == 2 for f in old)
    run = vikram.post(f"/api/reviewer/applications/{aid}/verify").json()
    assert run["rule_versions"]["INF-001"] == 3
    new = [f for f in vikram.get(f"/api/reviewer/applications/{aid}/findings").json() if f["rule_code"] == "INF-001"]
    assert any(f["status"] == "missing" for f in new)
