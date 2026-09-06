from __future__ import annotations

from functools import lru_cache
import re
import urllib.request

import fitz

from .storage import get_bytes

_DRIVE_RE = re.compile(r"/file/d/([^/]+)")


def _download_url(storage_url: str) -> str:
    if "drive.google.com" not in storage_url:
        return storage_url
    m = _DRIVE_RE.search(storage_url)
    if not m:
        return storage_url
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}"


@lru_cache(maxsize=4)
def _source_pdf(storage_url: str) -> bytes:
    url = _download_url(storage_url)
    req = urllib.request.Request(url, headers={"User-Agent": "PhysicsEduAgent/1.4"})
    with urllib.request.urlopen(req, timeout=35) as response:
        raw = response.read(40 * 1024 * 1024 + 1)
    if len(raw) > 40 * 1024 * 1024:
        raise RuntimeError("Source PDF exceeds 40 MB runtime limit")
    if not raw.startswith(b"%PDF"):
        raise RuntimeError("Source URL did not return a PDF")
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
