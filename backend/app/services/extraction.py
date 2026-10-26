"""Text extraction (native PDF text or Tesseract OCR), line reconstruction,
image-quality metrics and structured field extraction.

Every extracted field keeps its page number and a normalised bounding box so the
reviewer UI can highlight where a value came from. OCR output is never treated as
verified truth: low-confidence values are flagged for manual confirmation.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

import cv2
import numpy as np
import pymupdf
from PIL import Image

from ..config import settings

try:
    import pytesseract

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    TESSERACT_AVAILABLE = True
except Exception:  # pragma: no cover
    TESSERACT_AVAILABLE = False

OCR_DPI = 200
COLUMN_GAP_FRACTION = 0.02  # horizontal gap (fraction of page width) treated as a table column break


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None = None
    font: str = ""


@dataclass
class Line:
    text: str
    page: int
    bbox: list[float]  # normalised [x0,y0,x1,y1]
    conf: float | None
    fonts: set[str] = field(default_factory=set)


@dataclass
class ExtractionResult:
    method: str  # native | ocr | none
    text: str
    lines: list[Line]
    page_count: int
    mean_conf: float | None
    quality: dict
    file_metadata: dict
    image_hash: str = ""
    page_fonts: dict = field(default_factory=dict)  # font -> span count
    overlay_boxes: list = field(default_factory=list)  # white filled rects overlapping text
    font_outliers: list = field(default_factory=list)  # key-value lines set in a rare font


# ---------------------------------------------------------------- line building

def _group_lines(words: list[Word], page_no: int, pw: float, ph: float) -> list[Line]:
    if not words:
        return []
    words = sorted(words, key=lambda w: ((w.y0 + w.y1) / 2, w.x0))
    rows: list[list[Word]] = []
    for w in words:
        cy = (w.y0 + w.y1) / 2
        h = max(w.y1 - w.y0, 1)
        if rows:
            last = rows[-1]
            lcy = sum((x.y0 + x.y1) / 2 for x in last) / len(last)
            if abs(cy - lcy) < h * 0.55:
                last.append(w)
                continue
        rows.append([w])
    out: list[Line] = []
    gap_thr = pw * COLUMN_GAP_FRACTION
    for row in rows:
        row.sort(key=lambda w: w.x0)
        parts: list[str] = []
        prev: Word | None = None
        for w in row:
            if prev is not None:
                parts.append(" | " if (w.x0 - prev.x1) > gap_thr else " ")
            parts.append(w.text)
            prev = w
        text = "".join(parts).strip()
        confs = [w.conf for w in row if w.conf is not None and w.conf >= 0]
        out.append(
            Line(
                text=text,
                page=page_no,
                bbox=[
                    round(min(w.x0 for w in row) / pw, 4),
                    round(min(w.y0 for w in row) / ph, 4),
                    round(max(w.x1 for w in row) / pw, 4),
                    round(max(w.y1 for w in row) / ph, 4),
                ],
                conf=round(sum(confs) / len(confs), 1) if confs else None,
                fonts={w.font for w in row if w.font},
            )
        )
    return out


# ---------------------------------------------------------------- image helpers

def image_quality(img_bgr: np.ndarray) -> dict:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    h, w = gray.shape[:2]
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {
        "width_px": int(w),
        "height_px": int(h),
        "sharpness_laplacian_var": round(blur, 1),
        "mean_brightness": round(float(gray.mean()), 1),
        "low_resolution": bool(min(w, h) < 600),
        "blurry": bool(blur < 60.0),
    }


def dhash(img_bgr: np.ndarray, size: int = 8) -> str:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = "".join("1" if b else "0" for b in diff.flatten())
    return f"{int(bits, 2):016x}"


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _ocr_words(img: Image.Image) -> list[Word]:
    if not TESSERACT_AVAILABLE:
        return []
    data = pytesseract.image_to_data(img, lang="eng", config="--psm 4", output_type=pytesseract.Output.DICT)
    words = []
    for i, t in enumerate(data["text"]):
        t = (t or "").strip()
        if not t:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        conf = float(data["conf"][i])
        words.append(Word(t, x, y, x + w, y + h, conf if conf >= 0 else None))
    return words


def _to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------- main entry

def extract(data: bytes, mime: str) -> ExtractionResult:
    if mime == "application/pdf":
        return _extract_pdf(data)
    return _extract_image(data)


def _extract_image(data: bytes) -> ExtractionResult:
    img = Image.open(io.BytesIO(data))
    img.load()
    bgr = _to_bgr(img)
    words = _ocr_words(img)
    lines = _group_lines(words, 1, img.width, img.height)
    confs = [w.conf for w in words if w.conf is not None]
    exif = {}
    try:
        raw = img.getexif()
        exif = {str(k): str(v)[:80] for k, v in list(raw.items())[:20]}
    except Exception:
        pass
    return ExtractionResult(
        method="ocr" if words else "none",
        text="\n".join(l.text for l in lines),
        lines=lines,
        page_count=1,
        mean_conf=round(sum(confs) / len(confs), 1) if confs else None,
        quality=image_quality(bgr),
        file_metadata={"format": img.format or "", "exif": exif},
        image_hash=dhash(bgr),
    )


def _extract_pdf(data: bytes) -> ExtractionResult:
    doc = pymupdf.open(stream=data, filetype="pdf")
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    all_lines: list[Line] = []
    page_fonts: dict[str, int] = {}
    overlay_boxes: list = []
    native_chars = 0
    for pno, page in enumerate(doc, start=1):
        native_chars += len(page.get_text("text").strip())
    method = "native" if native_chars > 40 else "ocr"
    confs: list[float] = []
    quality: dict = {}
    for pno, page in enumerate(doc, start=1):
        pw, ph = page.rect.width, page.rect.height
        if method == "native":
            words: list[Word] = []
            d = page.get_text("dict")
            for block in d.get("blocks", []):
                for ln in block.get("lines", []):
                    for span in ln.get("spans", []):
                        font = span.get("font", "")
                        if span.get("text", "").strip():
                            page_fonts[font] = page_fonts.get(font, 0) + 1
                        # split span into words keeping bbox proportionally
                        txt = span.get("text", "")
                        x0, y0, x1, y1 = span["bbox"]
                        if not txt.strip():
                            continue
                        n = max(len(txt), 1)
                        cw = (x1 - x0) / n
                        for m in re.finditer(r"\S+", txt):
                            words.append(
                                Word(m.group(), x0 + m.start() * cw, y0, x0 + m.end() * cw, y1, None, font)
                            )
            all_lines.extend(_group_lines(words, pno, pw, ph))
            # White filled rectangles drawn over text are a classic "cover-up" pattern.
            text_rects = [pymupdf.Rect(b["bbox"]) for b in d.get("blocks", []) if b.get("type") == 0]
            for dr in page.get_drawings():
                fill = dr.get("fill")
                if fill and all(c > 0.97 for c in fill[:3]):
                    r = dr.get("rect")
                    if r is None or r.width < 8 or r.height < 4:
                        continue
                    if r.width > pw * 0.9 and r.height > ph * 0.9:
                        continue  # page background
                    if any(r.intersects(tr) for tr in text_rects):
                        overlay_boxes.append(
                            {"page": pno, "bbox": [round(r.x0 / pw, 4), round(r.y0 / ph, 4), round(r.x1 / pw, 4), round(r.y1 / ph, 4)]}
                        )
            if pno == 1:
                pix = page.get_pixmap(dpi=72)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                quality = {"source": "native_pdf", "pages": doc.page_count}
                quality["mean_brightness"] = round(float(np.array(img.convert("L")).mean()), 1)
        else:
            pix = page.get_pixmap(dpi=OCR_DPI)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            words = _ocr_words(img)
            confs.extend(w.conf for w in words if w.conf is not None)
            all_lines.extend(_group_lines(words, pno, pix.width, pix.height))
            if pno == 1:
                quality = image_quality(_to_bgr(img))
                quality["source"] = "scanned_pdf"
                quality["pages"] = doc.page_count
    font_outliers: list = []
    if method == "native" and page_fonts:
        total = sum(page_fonts.values())
        dominant = max(page_fonts.items(), key=lambda kv: kv[1])[0]
        rare = {f for f, n in page_fonts.items() if n <= max(2, 0.1 * total) and _family(f) != _family(dominant)}
        for ln in all_lines:
            if ln.fonts & rare and ":" in ln.text and re.search(r"\d", ln.text):
                font_outliers.append({"page": ln.page, "bbox": ln.bbox, "text": ln.text[:160],
                                      "fonts": sorted(ln.fonts), "dominant_font": dominant})
    result = ExtractionResult(
        method=method if all_lines else "none",
        text="\n".join(l.text for l in all_lines),
        lines=all_lines,
        page_count=doc.page_count,
        mean_conf=round(sum(confs) / len(confs), 1) if confs else None,
        quality=quality,
        file_metadata=meta,
        page_fonts=page_fonts,
        overlay_boxes=overlay_boxes,
        font_outliers=font_outliers,
    )
    doc.close()
    return result


def _family(font: str) -> str:
    return re.split(r"[-,]", font or "")[0].lower()


def render_page_png(data: bytes, mime: str, page: int, dpi: int = 110) -> bytes:
    if mime == "application/pdf":
        doc = pymupdf.open(stream=data, filetype="pdf")
        if page < 1 or page > doc.page_count:
            raise ValueError("Page out of range")
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        out = pix.tobytes("png")
        doc.close()
        return out
    if page != 1:
        raise ValueError("Page out of range")
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1400, 1400))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- field extraction

LABEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("institution_name", re.compile(r"^(?:name of (?:the )?institution|institution name|institute name|name of institute)\s*[:\-]\s*(.+)$", re.I)),
    ("permanent_id", re.compile(r"(?:aicte\s+)?permanent\s+id\s*[:\-]?\s*([0-9]-[0-9]{6,12})", re.I)),
    ("certificate_number", re.compile(r"^(?:certificate|registration|reference|ref\.?|approval|letter)\s*(?:no\.?|number)\s*[:\-]\s*([A-Z0-9/\-\.]+)", re.I)),
    ("issuing_authority", re.compile(r"^(?:issuing authority|issued by|authority)\s*[:\-]\s*(.+)$", re.I)),
    ("issue_date", re.compile(r"^(?:date of issue|issue date|issued on|date of award)\s*[:\-]\s*(.+)$", re.I)),
    ("expiry_date", re.compile(r"^(?:valid until|valid upto|valid up to|expiry date|date of expiry|validity)\s*[:\-]\s*(.+)$", re.I)),
    ("holder_name", re.compile(r"^(?:awarded to|name of the candidate|holder name)\s*[:\-]\s*(.+?)(?:\s+has\b.*)?$", re.I)),
    ("degree", re.compile(r"^(?:degree|qualification|degree awarded)\s*[:\-]\s*(.+)$", re.I)),
    ("awarding_body", re.compile(r"^(?:university|awarding body|awarded by)\s*[:\-]\s*(.+)$", re.I)),
    ("approved_intake", re.compile(r"^(?:total approved intake|approved intake|sanctioned intake|total intake)\s*[:\-]\s*(\d{1,5})", re.I)),
    ("academic_year", re.compile(r"^(?:academic year)\s*[:\-]\s*(\d{4}\s*-\s*\d{2,4})", re.I)),
    ("transaction_id", re.compile(r"^(?:transaction id|transaction reference|utr)\s*[:\-]\s*([A-Z0-9\-]+)", re.I)),
    ("amount", re.compile(r"^(?:amount(?: paid)?)\s*[:\-]\s*(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.\d{2})?)", re.I)),
    ("room_label", re.compile(r"^(?:room|facility|location)\s*[:\-]\s*([A-Z]{1,4}-\d{2,4})\b(.*)$", re.I)),
    ("accreditation_body", re.compile(r"^(?:accrediting body|accreditation body)\s*[:\-]\s*(.+)$", re.I)),
    ("programme_accredited", re.compile(r"^(?:programme|program)\s*[:\-]\s*(.+)$", re.I)),
]

PUB_FIELDS = {
    "title": "pub_title",
    "authors": "pub_authors",
    "journal": "pub_venue",
    "conference": "pub_venue",
    "venue": "pub_venue",
    "year": "pub_year",
    "doi": "pub_doi",
    "indexed in": "pub_indexing",
    "indexing": "pub_indexing",
    "volume": "pub_volume",
    "pages": "pub_pages",
}

FACULTY_ROW = re.compile(r"(FID-\d{3,6})")
PROGRAMME_ROW = re.compile(r"^(?:\d+\s*\|\s*)?((?:B\.?E\.?|B\.?Tech\.?|M\.?E\.?|M\.?Tech\.?|MBA|MCA)[^|]*?)\s*\|\s*(\d{1,4})\s*$", re.I)
FLOOR_ROOM_ROW = re.compile(r"^([A-Z]{1,4}-\d{2,4})\s*\|\s*([^|]+?)\s*\|\s*(\d+(?:\.\d+)?)\s*(?:sq\.?\s?m|m2|sqm)", re.I)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s|]+", re.I)


@dataclass
class FieldOut:
    name: str
    value: str
    page: int
    bbox: list[float]
    conf: float | None
    group: str = ""
    fonts: set[str] = field(default_factory=set)


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", v.replace(" | ", " ")).strip(" .;,")


def extract_fields(lines: list[Line]) -> list[FieldOut]:
    out: list[FieldOut] = []
    pub_idx = 0
    in_pub = False
    for ln in lines:
        text = ln.text.strip()
        flat = text.replace(" | ", " ")
        # Publication entries ("Publication 1", then "Title: ...")
        m = re.match(r"^publication\s*(?:no\.?\s*)?(\d+)\b", flat, re.I)
        if m:
            pub_idx = int(m.group(1))
            in_pub = True
            continue
        if in_pub:
            m = re.match(r"^([A-Za-z ]{3,12})\s*[:\-]\s*(.+)$", flat)
            if m and m.group(1).strip().lower() in PUB_FIELDS:
                name = PUB_FIELDS[m.group(1).strip().lower()]
                val = _clean(m.group(2))
                if name == "pub_doi":
                    d = DOI_RE.search(val)
                    val = d.group(0).rstrip(".") if d else val
                out.append(FieldOut(name, val, ln.page, ln.bbox, ln.conf, f"pub-{pub_idx}", ln.fonts))
                continue
        # Faculty table rows: Name | Qualification | Designation | FID-xxxx
        fm = FACULTY_ROW.search(text)
        if fm and "|" in text:
            cells = [c.strip() for c in text.split("|") if c.strip()]
            cells = [c for c in cells if not re.fullmatch(r"\d{1,3}\.?", c)]
            fid = fm.group(1)
            rest = [c for c in cells if fid not in c]
            if len(rest) >= 2:
                g = fid
                out.append(FieldOut("faculty_name", _clean(rest[0]), ln.page, ln.bbox, ln.conf, g, ln.fonts))
                out.append(FieldOut("faculty_qualification", _clean(rest[1]), ln.page, ln.bbox, ln.conf, g, ln.fonts))
                if len(rest) >= 3:
                    out.append(FieldOut("faculty_designation", _clean(rest[2]), ln.page, ln.bbox, ln.conf, g, ln.fonts))
                out.append(FieldOut("faculty_id", fid, ln.page, ln.bbox, ln.conf, g, ln.fonts))
                continue
        pm = PROGRAMME_ROW.match(text)
        if pm:
            g = re.sub(r"[^a-z]", "", pm.group(1).lower())[:40]
            out.append(FieldOut("programme_name", _clean(pm.group(1)), ln.page, ln.bbox, ln.conf, g, ln.fonts))
            out.append(FieldOut("programme_intake", pm.group(2), ln.page, ln.bbox, ln.conf, g, ln.fonts))
            continue
        rm = FLOOR_ROOM_ROW.match(text)
        if rm:
            g = rm.group(1).upper()
            out.append(FieldOut("floor_room", g, ln.page, ln.bbox, ln.conf, g, ln.fonts))
            out.append(FieldOut("floor_room_use", _clean(rm.group(2)), ln.page, ln.bbox, ln.conf, g, ln.fonts))
            out.append(FieldOut("floor_room_area_sqm", rm.group(3), ln.page, ln.bbox, ln.conf, g, ln.fonts))
            continue
        for name, pat in LABEL_PATTERNS:
            mm = pat.search(flat)
            if mm:
                val = _clean(mm.group(1))
                if name == "room_label":
                    val = mm.group(1).upper()
                    tail = _clean(mm.group(2) or "")
                    out.append(FieldOut(name, val, ln.page, ln.bbox, ln.conf, val, ln.fonts))
                    if tail:
                        out.append(FieldOut("room_label_use", tail.strip(" -–"), ln.page, ln.bbox, ln.conf, val, ln.fonts))
                    break
                if val:
                    out.append(FieldOut(name, val, ln.page, ln.bbox, ln.conf, "", ln.fonts))
                break
    return out


# ---------------------------------------------------------------- normalisation

_HONORIFICS = re.compile(r"^(?:dr|prof|mr|mrs|ms|shri|smt|er)\.?\s+", re.I)


def norm_text(v: str) -> str:
    v = (v or "").lower().replace("&", " and ")
    v = re.sub(r"[^a-z0-9 ]", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def norm_person(v: str) -> str:
    v = (v or "").strip()
    while True:
        nv = _HONORIFICS.sub("", v)
        if nv == v:
            break
        v = nv
    return norm_text(v)


def degree_level(v: str) -> str:
    t = norm_text(v).replace(" ", "")
    if t.startswith("phd") or "doctorofphilosophy" in t:
        return "PhD"
    if t.startswith(("me", "mtech", "ms", "mba", "mca", "msc")) or "masterof" in t:
        return "Masters"
    if t.startswith(("be", "btech", "bsc")) or "bachelorof" in t:
        return "Bachelors"
    return "Unknown"


_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y")


def parse_date(v: str) -> date | None:
    v = re.sub(r"\s+", " ", (v or "").strip().rstrip("."))
    v = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", v)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", v)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def normalize_field(name: str, value: str) -> str:
    if name in {"issue_date", "expiry_date"}:
        d = parse_date(value)
        return d.isoformat() if d else ""
    if name in {"holder_name", "faculty_name"}:
        return norm_person(value)
    if name in {"faculty_qualification", "degree"}:
        return degree_level(value)
    if name == "pub_doi":
        return value.lower().strip()
    if name in {"approved_intake", "programme_intake", "pub_year"}:
        d = re.sub(r"[^0-9]", "", value)
        return d
    return norm_text(value)


def shingles(text: str, k: int = 5) -> set[str]:
    toks = norm_text(text).split()
    return {" ".join(toks[i : i + k]) for i in range(max(len(toks) - k + 1, 0))}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
