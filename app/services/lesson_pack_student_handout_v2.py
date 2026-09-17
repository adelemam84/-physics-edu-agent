from __future__ import annotations

import io

import fitz

from .lesson_pack_pdf_navigation import (
    _marker_html,
    add_pdf_navigation,
    enhance_document_html,
    final_review_html,
    navigation_css,
)
from .lesson_pack_student_renderer import (
    MARGIN_X,
    MARGIN_Y,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    _css,
    _document_html,
    _stamp,
)


def _render_story(html: str, css: str, *, max_pages: int) -> bytes:
    media = fitz.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)
    content = fitz.Rect(MARGIN_X, MARGIN_Y, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - MARGIN_Y)

    def rectfn(rect_num, filled):
        if rect_num > max_pages:
            raise RuntimeError("Enhanced Student handout exceeded safe page limit")
        return media, content, None

    def contentfn(_positions):
        return html

    out = io.BytesIO()
    writer = fitz.DocumentWriter(out)
    try:
        fitz.Story.write_stabilized(
            writer,
            contentfn,
            rectfn,
            user_css=css,
            em=11,
            add_header_ids=False,
        )
    finally:
        writer.close()
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Invalid enhanced Student Handout PDF")
    return data


def _render_enhanced(pack: dict) -> tuple[bytes, list]:
    html = enhance_document_html(_document_html(pack), pack)
    return _render_story(html, _css() + navigation_css(), max_pages=220), []


def _render_final_review(pack: dict) -> bytes:
    fragment = final_review_html(pack)
    fragment = fragment.replace(" page-break-before", "")
    fragment = fragment.replace(_marker_html("T", "nav-final-review"), "")
    html = f'<article dir="rtl" lang="ar">{fragment}</article>'
    return _render_story(html, _css() + navigation_css(), max_pages=4)


def _append_final_review(base_data: bytes, review_data: bytes) -> bytes:
    base = fitz.open(stream=base_data, filetype="pdf")
    review = fitz.open(stream=review_data, filetype="pdf")
    try:
        base.insert_pdf(review)
        return base.tobytes(garbage=3, deflate=True)
    finally:
        review.close()
        base.close()


def render_enhanced_student_handout_pdf(pack: dict) -> bytes:
    """Render the handout, append a deterministic final-review page, then add navigation."""
    data, positions = _render_enhanced(pack)
    data = _append_final_review(data, _render_final_review(pack))
    data = add_pdf_navigation(data, pack, positions)
    return _stamp(data, str(pack.get("title") or "ملزمة الدرس"))
