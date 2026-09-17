from __future__ import annotations

import io

import fitz

from .lesson_pack_pdf_navigation import (
    add_pdf_navigation,
    final_review_html,
    navigation_css,
    navigation_index_html,
)
from .lesson_pack_student_renderer import (
    MARGIN_X,
    MARGIN_Y,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    _render,
    _stamp,
)


_FRAGMENT_CSS = '''
  @page { size:A4; margin:0; }
  body { font-family:sans-serif; font-size:11.5pt; line-height:1.68; color:#172033; }
  article { direction:rtl; }
  h2 { font-size:15.5pt; margin:12px 0 8px; padding-bottom:5px; border-bottom:1.4px solid #98a2b3; }
  h3 { font-size:12.5pt; margin:5px 0 7px; }
  ul { margin:6px 20px 10px 0; }
'''


def _render_fragment(fragment: str) -> bytes:
    media = fitz.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)
    content = fitz.Rect(MARGIN_X, MARGIN_Y, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - MARGIN_Y)

    def rectfn(rect_num, filled):
        if rect_num > 12:
            raise RuntimeError("Lesson Pack navigation fragment exceeded safe page limit")
        return media, content, None

    def contentfn(_positions):
        return f'<article dir="rtl" lang="ar">{fragment}</article>'

    out = io.BytesIO()
    writer = fitz.DocumentWriter(out)
    try:
        fitz.Story.write_stabilized(
            writer,
            contentfn,
            rectfn,
            user_css=_FRAGMENT_CSS + navigation_css(),
            em=11,
            add_header_ids=False,
        )
    finally:
        writer.close()
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Invalid Lesson Pack navigation fragment PDF")
    return data


def _find_notes_page(doc: fitz.Document) -> int | None:
    for page_index, page in enumerate(doc):
        if page.search_for("ملاحظاتي وأسئلتي"):
            return page_index
    return None


def _insert_pdf(out: fitz.Document, src: fitz.Document, start: int, end: int) -> None:
    if start <= end and start < src.page_count:
        out.insert_pdf(src, from_page=start, to_page=min(end, src.page_count - 1))


def render_enhanced_student_handout_pdf(pack: dict) -> bytes:
    """Add a dedicated index and final-review page around the approved student handout."""
    base_data = _render(pack)
    index_data = _render_fragment(navigation_index_html(pack))
    review_data = _render_fragment(final_review_html(pack))

    base = fitz.open(stream=base_data, filetype="pdf")
    index_doc = fitz.open(stream=index_data, filetype="pdf")
    review_doc = fitz.open(stream=review_data, filetype="pdf")
    out = fitz.open()
    try:
        notes_page = _find_notes_page(base)
        if base.page_count:
            _insert_pdf(out, base, 0, 0)
        out.insert_pdf(index_doc)

        if notes_page is None:
            _insert_pdf(out, base, 1, base.page_count - 1)
            out.insert_pdf(review_doc)
        else:
            _insert_pdf(out, base, 1, notes_page - 1)
            out.insert_pdf(review_doc)
            _insert_pdf(out, base, notes_page, base.page_count - 1)

        merged = out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()
        review_doc.close()
        index_doc.close()
        base.close()

    merged = add_pdf_navigation(merged, pack)
    return _stamp(merged, str(pack.get("title") or "ملزمة الدرس"))
