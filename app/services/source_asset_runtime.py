from __future__ import annotations

import base64
from functools import lru_cache
import re
import urllib.request

import fitz

from ..db import connect
from .storage import get_bytes

_DRIVE_RE = re.compile(r"/file/d/([^/]+)")


def _drive_file_id(storage_url: str) -> str | None:
    m = _DRIVE_RE.search(storage_url)
    return m.group(1) if m else None


def _download_url(storage_url: str) -> str:
    if "drive.google.com" not in storage_url:
        return storage_url
    file_id = _drive_file_id(storage_url)
    if not file_id:
        return storage_url
    return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"


@lru_cache(maxsize=64)
def _cached_source_page(document_id: int, page_number: int) -> bytes | None:
    key = f"source_page_image_b64:{document_id}:{page_number}"
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
    if not row:
        return None
    try:
        return base64.b64decode(row["value"], validate=True)
    except Exception as exc:
        raise RuntimeError("Cached source page is corrupt") from exc


@lru_cache(maxsize=4)
def _source_pdf(storage_url: str) -> bytes:
    url = _download_url(storage_url)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 PhysicsEduAgent/1.4",
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=55) as response:
        raw = response.read(90 * 1024 * 1024 + 1)
    if len(raw) > 90 * 1024 * 1024:
        raise RuntimeError("Source PDF exceeds 90 MB runtime limit")
    if not raw.startswith(b"%PDF"):
        raise RuntimeError("Source URL did not return a PDF")
    return raw


def _render_from_image(raw: bytes, row: dict) -> bytes:
    image_doc = fitz.open(stream=raw, filetype="jpeg")
    try:
        page = image_doc.load_page(0)
        r = page.rect
        x = float(row["crop_x"])
        y = float(row["crop_y"])
        w = float(row["crop_width"])
        h = float(row["crop_height"])
        clip = fitz.Rect(
            r.x0 + x * r.width,
            r.y0 + y * r.height,
            r.x0 + (x + w) * r.width,
            r.y0 + (y + h) * r.height,
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
        return pix.tobytes("jpeg", jpg_quality=90)
    finally:
        image_doc.close()


def render_asset_bytes(row: dict) -> bytes:
    """Return an exact source-backed question visual.

    Normal uploaded assets use object storage. Synthetic `source-drive:` assets
    first use a compact cache of the authoritative source page stored in the
    project database. The original Drive PDF remains the provenance/fallback.
    """
    key = str(row["object_key"])
    if not key.startswith("source-drive:"):
        return get_bytes(key)

    parts = key.split(":")
    if len(parts) < 4:
        raise RuntimeError("Invalid source-backed asset key")
    document_id = int(parts[1])
    page_number = int(row["page_number"])

    cached = _cached_source_page(document_id, page_number)
    if cached:
        return _render_from_image(cached, row)

    storage_url = row.get("storage_url")
    if not storage_url:
        raise RuntimeError("Source-backed asset has no document storage URL")

    raw = _source_pdf(str(storage_url))
    pdf = fitz.open(stream=raw, filetype="pdf")
    try:
        if page_number < 1 or page_number > pdf.page_count:
            raise RuntimeError("Source-backed asset page is outside the PDF")
        page = pdf.load_page(page_number - 1)
        r = page.rect
        x = float(row["crop_x"])
        y = float(row["crop_y"])
        w = float(row["crop_width"])
        h = float(row["crop_height"])
        clip = fitz.Rect(
            r.x0 + x * r.width,
            r.y0 + y * r.height,
            r.x0 + (x + w) * r.width,
            r.y0 + (y + h) * r.height,
        )
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
        return pix.tobytes("jpeg", jpg_quality=90)
    finally:
        pdf.close()
