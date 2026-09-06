from __future__ import annotations

from . import science_lesson_studio
from .services.science_notation import analyze_notation_items

_BASE_ORGANIZE = science_lesson_studio._organize


def _organize_with_notation(transcript: str, subject: str, grade_label: str, title: str, output_mode: str) -> dict:
    structured = _BASE_ORGANIZE(transcript, subject, grade_label, title, output_mode)
    notation = analyze_notation_items(structured.get('equations_or_rules') or [])
    structured['equations_or_rules'] = notation['items']
    structured['notation_quality'] = {
        'review_required': notation['review_required'],
        'policy': notation['policy'],
    }
    return structured


science_lesson_studio._organize = _organize_with_notation
