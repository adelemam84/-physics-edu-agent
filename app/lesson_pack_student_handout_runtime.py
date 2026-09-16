from __future__ import annotations

from . import lesson_pack_studio
from .services.lesson_pack_core import render_pdf as _base_render_pdf
from .services.lesson_pack_student_renderer import render_student_handout_pdf


def _render_lesson_pack_pdf(pack: dict, edition: str) -> bytes:
    if edition == "student":
        return render_student_handout_pdf(pack)
    return _base_render_pdf(pack, edition)


# Register the dedicated printable student renderer after Lesson Pack Studio routes
# are loaded. The route resolves render_pdf from its module globals at request time.
lesson_pack_studio.render_pdf = _render_lesson_pack_pdf
