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
from .lesson_pack_practice_layout import (
    decorate_practice_html,
    practice_layout_settings,
    practice_suite_css,
    prepare_practice_pack,
    self_test_items,
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
    # Navigation markers must be attached to the canonical practice cards before
    # the practice-suite decorator inserts level dividers and the self-test pages.
    # This keeps question bookmarks stable for minimal and full Lesson Packs alike.
    navigable_html = enhance_document_html(_document_html(pack), pack)
    html = decorate_practice_html(navigable_html, pack)
    css = _css() + navigation_css() + practice_suite_css()
    return _render_story(html, css, max_pages=240), []


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


def _stamp_export_contract(data: bytes, pack: dict) -> bytes:
    """Attach machine-readable, non-content export evidence for PDF preflight."""
    settings = practice_layout_settings(pack)
    selected = self_test_items(pack)
    questions = [q for q in (pack.get("practice_questions") or []) if isinstance(q, dict)]
    tokens = [
        "lesson-pack-student-v2",
        f"practice-questions={len(questions)}",
        f"self-test={len(selected)}",
        f"answer-sheet={1 if settings['show_answer_sheet'] and selected else 0}",
        "final-review-last=1",
    ]
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        metadata = dict(doc.metadata or {})
        existing = str(metadata.get("keywords") or "").strip()
        metadata["keywords"] = ";".join(([existing] if existing else []) + tokens)
        doc.set_metadata(metadata)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def render_enhanced_student_handout_pdf(pack: dict) -> bytes:
    """Render the grouped practice suite, append final review, then add PDF navigation."""
    render_pack = prepare_practice_pack(pack)
    data, positions = _render_enhanced(render_pack)
    data = _append_final_review(data, _render_final_review(render_pack))
    data = add_pdf_navigation(data, render_pack, positions)
    data = _stamp(data, str(render_pack.get("title") or "ملزمة الدرس"))
    return _stamp_export_contract(data, render_pack)
