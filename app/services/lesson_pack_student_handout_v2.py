from __future__ import annotations

import io

import fitz

from .lesson_pack_pdf_navigation import add_pdf_navigation, enhance_document_html, navigation_css
from .lesson_pack_student_renderer import (
    MARGIN_X,
    MARGIN_Y,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    _css,
    _document_html,
    _stamp,
)


def _render_enhanced(pack: dict) -> bytes:
    media = fitz.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)
    content = fitz.Rect(MARGIN_X, MARGIN_Y, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - MARGIN_Y)

    def rectfn(rect_num, filled):
        if rect_num > 220:
            raise RuntimeError("Enhanced Student handout exceeded safe page limit")
        return media, content, None

    enhanced_html = enhance_document_html(_document_html(pack), pack)

    def contentfn(_positions):
        return enhanced_html

    out = io.BytesIO()
    writer = fitz.DocumentWriter(out)
    try:
        fitz.Story.write_stabilized(
            writer,
            contentfn,
            rectfn,
            user_css=_css() + navigation_css(),
            em=11,
            add_header_ids=False,
        )
    finally:
        writer.close()
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Invalid enhanced Student Handout PDF")
    return data


def render_enhanced_student_handout_pdf(pack: dict) -> bytes:
    """Render one A4 story with native internal links, then add the PDF outline."""
    data = _render_enhanced(pack)
    data = add_pdf_navigation(data, pack)
    return _stamp(data, str(pack.get("title") or "ملزمة الدرس"))
