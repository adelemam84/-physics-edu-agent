from __future__ import annotations

import io

import fitz

from .lesson_pack_practice_layout import practice_suite_css, teacher_self_test_key_html
from .lesson_pack_student_renderer import MARGIN_X, MARGIN_Y, PAGE_HEIGHT, PAGE_WIDTH, _css


TEACHER_SELF_TEST_BOOKMARK = "نموذج إجابة «اختبر نفسك»"


def _render_appendix(pack: dict) -> bytes:
    fragment = teacher_self_test_key_html(pack)
    if not fragment:
        return b""
    media = fitz.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)
    content = fitz.Rect(MARGIN_X, MARGIN_Y, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - MARGIN_Y)

    def rectfn(rect_num, filled):
        if rect_num > 12:
            raise RuntimeError("Teacher self-test answer appendix exceeded safe page limit")
        return media, content, None

    def contentfn(_positions):
        return fragment

    out = io.BytesIO()
    writer = fitz.DocumentWriter(out)
    try:
        fitz.Story.write_stabilized(
            writer,
            contentfn,
            rectfn,
            user_css=_css() + practice_suite_css(),
            em=11,
            add_header_ids=False,
        )
    finally:
        writer.close()
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Invalid teacher self-test answer appendix PDF")
    return data


def append_teacher_practice_key(base_data: bytes, pack: dict) -> bytes:
    appendix_data = _render_appendix(pack)
    if not appendix_data:
        return base_data
    base = fitz.open(stream=base_data, filetype="pdf")
    appendix = fitz.open(stream=appendix_data, filetype="pdf")
    try:
        appendix_start_page = base.page_count + 1
        toc = base.get_toc(simple=True)
        base.insert_pdf(appendix)
        toc.append([1, TEACHER_SELF_TEST_BOOKMARK, appendix_start_page])
        base.set_toc(toc)
        return base.tobytes(garbage=3, deflate=True)
    finally:
        appendix.close()
        base.close()
