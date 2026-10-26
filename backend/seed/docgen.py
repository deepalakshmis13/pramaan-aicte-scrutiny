"""Synthetic document generator for demo scenarios.

Every generated file carries a visible 'SYNTHETIC TEST DOCUMENT' footer. Institutions,
people, certificate numbers and issuing bodies are fictional.
"""
from __future__ import annotations

import io
import random
from datetime import date, datetime

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4
FOOT = "SYNTHETIC TEST DOCUMENT generated for the PRAMAAN prototype. Not a genuine record."
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def d(dt: date) -> str:
    return dt.strftime("%d/%m/%Y")


def _pdf_meta(data: bytes, created: datetime, modified: datetime | None = None, producer: str = "PRAMAAN synthetic document generator") -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    fmt = lambda t: t.strftime("D:%Y%m%d%H%M%S")
    doc.set_metadata({"creator": "PRAMAAN seed", "producer": producer, "creationDate": fmt(created),
                      "modDate": fmt(modified or created), "title": "", "author": "", "subject": "", "keywords": ""})
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


def _frame(c: canvas.Canvas, issuer: str, issuer_sub: str, accent=colors.HexColor("#1f3a5f")):
    c.setFillColor(accent)
    c.rect(0, H - 70, W, 70, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, H - 38, issuer)
    c.setFont("Helvetica", 9)
    c.drawString(50, H - 54, issuer_sub)
    c.setFillColor(colors.HexColor("#8a6d1f"))
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(50, 30, FOOT)
    c.setFillColor(colors.black)


def certificate(issuer: str, issuer_sub: str, title: str, fields: list[tuple[str, str]], body: str = "", *,
                issued: date, altered: dict | None = None, signatory: str = "Authorised Signatory") -> bytes:
    """altered = {"label": "Valid Until", "value": "...", "modified": datetime, "producer": str}"""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _frame(c, issuer, issuer_sub)
    c.setFont("Helvetica-Bold", 17)
    c.drawCentredString(W / 2, H - 120, title)
    c.setStrokeColor(colors.HexColor("#c9ced6"))
    c.line(50, H - 132, W - 50, H - 132)
    y = H - 170
    c.setFont("Helvetica", 11)
    for label, value in fields:
        if altered and label == altered["label"]:
            # Cover-up pattern: white box, value re-typed in a different typeface
            c.setFillColor(colors.white)
            c.rect(48, y - 4, 330, 16, stroke=0, fill=1)
            c.setFillColor(colors.black)
            c.setFont("Courier", 11)
            c.drawString(50, y, f"{label}: {altered['value']}")
            c.setFont("Helvetica", 11)
        else:
            c.drawString(50, y, f"{label}: {value}")
        y -= 24
    if body:
        y -= 10
        text = c.beginText(50, y)
        text.setFont("Helvetica", 10)
        for line in _wrap(body, 92):
            text.textLine(line)
        c.drawText(text)
        y -= 14 * (len(_wrap(body, 92)) + 1)
    c.setFont("Helvetica", 10)
    c.drawString(W - 230, 120, signatory)
    c.setStrokeColor(colors.HexColor("#555555"))
    c.line(W - 230, 135, W - 60, 135)
    c.showPage()
    c.save()
    created = datetime.combine(issued, datetime.min.time()).replace(hour=11)
    if altered:
        return _pdf_meta(buf.getvalue(), created, altered["modified"], altered.get("producer", "PDF editor"))
    return _pdf_meta(buf.getvalue(), created)


def _wrap(s: str, n: int) -> list[str]:
    out, cur = [], ""
    for w in s.split():
        if len(cur) + len(w) + 1 > n:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def table_doc(issuer: str, issuer_sub: str, title: str, header: list[tuple[str, str]], columns: list[tuple[str, int]],
              rows: list[list[str]], footer_fields: list[tuple[str, str]] = (), *, issued: date, note: str = "") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _frame(c, issuer, issuer_sub)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, H - 110, title)
    y = H - 140
    c.setFont("Helvetica", 10.5)
    for label, value in header:
        c.drawString(50, y, f"{label}: {value}")
        y -= 18
    y -= 12
    c.setFont("Helvetica-Bold", 9.5)
    for name, x in columns:
        c.drawString(x, y, name)
    c.setStrokeColor(colors.HexColor("#9aa3b0"))
    c.line(48, y - 5, W - 48, y - 5)
    y -= 22
    c.setFont("Helvetica", 9.5)
    for r in rows:
        for (name, x), val in zip(columns, r):
            c.drawString(x, y, val)
        c.setStrokeColor(colors.HexColor("#e1e4e8"))
        c.line(48, y - 6, W - 48, y - 6)
        y -= 20
    y -= 10
    c.setFont("Helvetica", 10.5)
    for label, value in footer_fields:
        c.drawString(50, y, f"{label}: {value}")
        y -= 18
    if note:
        c.setFont("Helvetica-Oblique", 8.5)
        c.drawString(50, y - 8, note)
    c.showPage()
    c.save()
    return _pdf_meta(buf.getvalue(), datetime.combine(issued, datetime.min.time()).replace(hour=10))


def publication_list(issuer: str, issuer_sub: str, institution: str, pid: str, pubs: list[dict], *, issued: date) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _frame(c, issuer, issuer_sub)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, H - 110, "Research Publications of Faculty")
    c.setFont("Helvetica", 10.5)
    c.drawString(50, H - 135, f"Institution Name: {institution}")
    c.drawString(50, H - 153, f"AICTE Permanent ID: {pid}")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(50, H - 170, "Public DOIs are cited only to exercise metadata verification; faculty authorship claims are synthetic.")
    y = H - 200
    for i, p in enumerate(pubs, start=1):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, f"Publication {i}")
        y -= 16
        c.setFont("Helvetica", 9.5)
        for label in ("Title", "Authors", "Journal", "Year", "DOI", "Indexed In"):
            key = {"Title": "title", "Authors": "authors", "Journal": "venue", "Year": "year", "DOI": "doi", "Indexed In": "indexed"}[label]
            if p.get(key):
                c.drawString(64, y, f"{label}: {p[key]}")
                y -= 14
        y -= 12
    c.showPage()
    c.save()
    return _pdf_meta(buf.getvalue(), datetime.combine(issued, datetime.min.time()).replace(hour=9))


def floor_plan(institution: str, pid: str, rooms: list[tuple[str, str, int]], *, issued: date) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _frame(c, "Office of the Architect (synthetic)", "Approved building plan extract", colors.HexColor("#2d4a3e"))
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, H - 110, "Floor Plan - Academic Block A, Second Floor")
    c.setFont("Helvetica", 10.5)
    c.drawString(50, H - 135, f"Institution Name: {institution}")
    c.drawString(50, H - 153, f"AICTE Permanent ID: {pid}")
    # schematic drawing
    x0, y0, w, h = 60, H - 470, W - 120, 270
    c.setStrokeColor(colors.HexColor("#33415c"))
    c.setLineWidth(1.6)
    c.rect(x0, y0, w, h)
    cols = max(len(rooms), 1)
    cw = w / cols
    for i, (code, use, area) in enumerate(rooms):
        c.rect(x0 + i * cw, y0 + 90, cw, h - 90)
    c.setLineWidth(0.6)
    c.line(x0, y0 + 90, x0 + w, y0 + 90)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x0 + 6, y0 + 40, "corridor (schematic, not to scale)")
    y = y0 - 40
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(60, y, "Room")
    c.drawString(180, y, "Use")
    c.drawString(400, y, "Carpet area")
    y -= 20
    c.setFont("Helvetica", 9.5)
    for code, use, area in rooms:
        c.drawString(60, y, code)
        c.drawString(180, y, use)
        c.drawString(400, y, f"{area} sq.m")
        y -= 18
    c.showPage()
    c.save()
    return _pdf_meta(buf.getvalue(), datetime.combine(issued, datetime.min.time()).replace(hour=14))


def scanned(pdf_bytes: bytes, *, dpi: int = 200, blur: float = 0.6, noise: float = 6.0, rotate: float = 0.35, seed: int = 1, jpeg_q: int = 80) -> bytes:
    """Rasterise a PDF and rebuild it as an image-only 'scan' (forces the OCR path)."""
    rnd = np.random.default_rng(seed)
    src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        img = img.rotate(rotate, expand=False, fillcolor=255, resample=Image.BICUBIC)
        if blur:
            img = img.filter(ImageFilter.GaussianBlur(blur))
        arr = np.array(img).astype(np.float32)
        arr += rnd.normal(0, noise, arr.shape)
        arr = np.clip(arr * 0.96 + 6, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
        b = io.BytesIO()
        img.save(b, format="JPEG", quality=jpeg_q)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=b.getvalue())
    data = out.tobytes(deflate=True)
    out.close()
    src.close()
    return _pdf_meta(data, datetime(2026, 5, 2, 15, 0), producer="Office scanner (synthetic)")


def room_photo(code: str, use: str, seed: int, *, blur: int = 0, brightness: float = 1.0, size=(1280, 860), fmt: str = "PNG") -> bytes:
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size, (220, 214, 200))
    dr = ImageDraw.Draw(img)
    wall = tuple(rnd.randint(185, 230) for _ in range(3))
    dr.rectangle([0, 0, w, int(h * 0.55)], fill=wall)
    floor = tuple(rnd.randint(120, 170) for _ in range(3))
    dr.polygon([(0, int(h * 0.55)), (w, int(h * 0.55)), (w, h), (0, h)], fill=floor)
    for i in range(rnd.randint(2, 4)):  # windows
        x = 80 + i * rnd.randint(260, 320)
        dr.rectangle([x, 70, x + 170, 260], fill=(170, 205, 230), outline=(90, 90, 90), width=6)
    rows, cols = rnd.randint(2, 4), rnd.randint(4, 6)
    for r in range(rows):
        for cidx in range(cols):
            x = 70 + cidx * (w - 140) // cols
            y = int(h * 0.6) + r * 70
            dr.rectangle([x, y, x + 120, y + 28], fill=(110, 78, 50))
            if "lab" in use.lower():
                dr.rectangle([x + 30, y - 46, x + 90, y - 4], fill=(35, 35, 40))
    banner_h = 86
    dr.rectangle([0, h - banner_h, w, h], fill=(255, 255, 255))
    font = ImageFont.truetype(FONT_BOLD, 40)
    dr.text((40, h - banner_h + 20), f"Room: {code} {use}", fill=(10, 10, 10), font=font)
    if brightness != 1.0:
        arr = np.clip(np.array(img).astype(np.float32) * brightness, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
    if blur:
        bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        bgr = cv2.GaussianBlur(bgr, (0, 0), blur)
        img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    b = io.BytesIO()
    if fmt == "JPEG":
        img.save(b, format="JPEG", quality=88)
    else:
        img.save(b, format="PNG", optimize=True)
    return b.getvalue()
