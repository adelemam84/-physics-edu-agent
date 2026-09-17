from __future__ import annotations

from . import lesson_pack_studio
from .services.lesson_pack_core import render_pdf as _base_render_pdf
from .services.lesson_pack_practice_layout import prepare_practice_pack
from .services.lesson_pack_student_handout_v2 import (
    render_enhanced_student_handout_pdf as render_student_handout_pdf,
)
from .services.lesson_pack_teacher_practice_appendix import append_teacher_practice_key


def _render_lesson_pack_pdf(pack: dict, edition: str) -> bytes:
    if edition == "student":
        return render_student_handout_pdf(pack)
    render_pack = prepare_practice_pack(pack)
    base = _base_render_pdf(render_pack, edition)
    if edition == "teacher":
        return append_teacher_practice_key(base, render_pack)
    return base


# Register the enhanced printable student/teacher Lesson Pack renderers after routes
# are loaded. The route resolves render_pdf from its module globals at request time.
lesson_pack_studio.render_pdf = _render_lesson_pack_pdf
