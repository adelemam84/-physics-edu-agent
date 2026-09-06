from __future__ import annotations

from . import science_lesson_studio
from .services.lesson_pdf_renderer import render_lesson_pdf

# Register the production multi-page renderer after the core Lesson Studio module
# is imported. Existing endpoints resolve _render_pdf at request time, so this
# safely upgrades the renderer without duplicating route definitions.
science_lesson_studio._render_pdf = render_lesson_pdf
