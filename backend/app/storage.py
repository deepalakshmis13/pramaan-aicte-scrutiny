"""Protected file storage. Files are stored under server-generated keys; user-supplied
filenames are kept only as metadata and never used to build filesystem paths."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from .config import settings

_KEY_RE = re.compile(r"^(documents|reports)/\d+/[0-9a-f]{32}\.(pdf|png|jpg)$")


def safe_display_name(name: str) -> str:
    name = Path(name or "upload").name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .") or "upload"
    return name[:200]


def new_key(area: str, application_id: int, ext: str) -> str:
    return f"{area}/{int(application_id)}/{uuid.uuid4().hex}{ext}"


def path_for(key: str) -> Path:
    if not _KEY_RE.match(key):
        raise ValueError("Invalid storage key")
    root = settings.storage_dir.resolve()
    p = (root / key).resolve()
    if root not in p.parents:
        raise ValueError("Path escapes storage root")
    return p


def save_bytes(key: str, data: bytes) -> Path:
    p = path_for(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def read_bytes(key: str) -> bytes:
    return path_for(key).read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_mime(data: bytes) -> str | None:
    """Identify type by magic bytes, not by the client-declared content type."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return None
