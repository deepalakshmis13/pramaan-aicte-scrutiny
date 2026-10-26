"""Writes the synthetic files used by the Playwright journey (frontend/e2e/fixtures/northfield)."""
from datetime import date, timedelta
from pathlib import Path

from . import docgen as G
from .seed import build_documents

OUT = Path(__file__).resolve().parents[2] / "frontend" / "e2e" / "fixtures" / "northfield"
NAME, PID = "Northfield Institute of Technology", "1-5521093344"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    today = date.today()
    docs = build_documents("B", NAME, PID, "Pune", "Maharashtra")
    noc_expired = G.certificate("Southern Technological University (synthetic)", "Registrar", "NO OBJECTION CERTIFICATE",
                                [("Certificate No", "STU/NOC/3344/2024"), ("Institution Name", NAME), ("Date of Issue", G.d(today - timedelta(days=500))),
                                 ("Valid Until", G.d(today - timedelta(days=30)))], "No objection.", issued=today - timedelta(days=500))
    fire = G.certificate("District Fire and Rescue Services, Pune (synthetic)", "Fire Safety Wing", "FIRE SAFETY CERTIFICATE",
                         [("Certificate No", "FSC/PUN/2026/3344"), ("Institution Name", NAME), ("Issuing Authority", "District Fire Officer, Pune"),
                          ("Date of Issue", G.d(today - timedelta(days=20))), ("Valid Until", G.d(today + timedelta(days=700)))], "Inspected.", issued=today)
    counts: dict[str, int] = {}
    for dtype, _title, data, mime in docs + [("fire_safety_certificate", "", fire, "application/pdf")]:
        if dtype == "noc":
            data = noc_expired
        counts[dtype] = counts.get(dtype, 0) + 1
        ext = "pdf" if mime == "application/pdf" else "png"
        (OUT / f"{dtype}-{counts[dtype]}.{ext}").write_bytes(data)
    valid = G.certificate("Southern Technological University (synthetic)", "Registrar", "NO OBJECTION CERTIFICATE",
                          [("Certificate No", "STU/NOC/3344/2026"), ("Institution Name", NAME), ("Date of Issue", G.d(today - timedelta(days=5))),
                           ("Valid Until", G.d(today + timedelta(days=700)))], "No objection.", issued=today)
    (OUT.parent / "noc-corrected.pdf").write_bytes(valid)
    print(f"Wrote {len(list(OUT.glob('*')))} files to {OUT}")


if __name__ == "__main__":
    main()
