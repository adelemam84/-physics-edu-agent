from __future__ import annotations

from functools import lru_cache
import re
import urllib.request

import fitz

from .storage import get_bytes

_DRIVE_RE = re.compile(r"/file/d/([^/]+)")


def _drive_file_id(storage_url: str) -> str | None:
    m = _DRIVE_RE.search(storage_url)
    return m.group(1) if m else None


def _download_url(storage_url: str) -> str:
    """Resolve a source URL to a direct download URL.

    Large Google Drive files are served through drive.usercontent.google.com.
    Passing confirm=t avoids the browser virus-scan interstitial that otherwise
    returns HTML instead of the authoritative PDF bytes.
    """
    if "drive.google.com" not in storage_url:
        return storage_url
    file_id = _drive_file_id(storage_url)
    if not file_id:
        return storage_url
    return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"


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
        content_type = (response.headers.get("Content-Type") or "").lower()
    if len(raw) > 90 * 1024 * 1024:
        raise RuntimeError("Source PDF exceeds 90 MB runtime limit")
    if not raw.startswith(b"%PDF"):
        raise RuntimeError(f"Source URL did not return a PDF ({content_type or 'unknown content type'})")
    return raw


def render_asset_bytes(row: dict) -> bytes:
    """Return the exact source-backed visual for a question asset.

    Normal uploaded assets keep using object storage. Synthetic `source-drive:`
    assets are rendered directly from the authoritative PDF using the stored
    normalized crop coordinates, so the student never sees a recreated diagram.
    """
    key = str(row["object_key"])
    if not key.startswith("source-drive:"):
        return get_bytes(key)

    storage_url = row.get("storage_url")
    if not storage_url:
        raise RuntimeError("Source-backed asset has no document storage URL")

    raw = _source_pdf(str(storage_url))
    pdf = fitz.open(stream=raw, filetype="pdf")
    try:
        page_number = int(row["page_number"])
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
