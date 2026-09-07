from __future__ import annotations

from fastapi import Depends

from .main import app
from .security import require_admin
from .lesson_studio_version_diff import compare_versions


GATES = (
    'ocr_review',
    'notation_review',
    'diagram_review',
    'scientific_reference_review',
    'independent_second_review',
    'teacher_approval',
    'final_pdf_export',
)


def change_impact(diff: dict) -> dict:
    transcript_changed = bool((diff.get('transcript') or {}).get('changed'))
    changes = list(((diff.get('structured') or {}).get('changes') or []))
    kinds = {str(x.get('kind') or '') for x in changes}
    keys = {str(x.get('key') or '') for x in changes}

    required = {gate: False for gate in GATES}
    reasons: dict[str, list[str]] = {gate: [] for gate in GATES}

    any_change = transcript_changed or bool(changes)
    if any_change:
        required['teacher_approval'] = True
        required['final_pdf_export'] = True
        reasons['teacher_approval'].append('أي تغيير في محتوى الدرس يتطلب اعتماد المدرس على النسخة الحالية.')
        reasons['final_pdf_export'].append('الـPDF النهائي يجب إعادة توليده من المحتوى المعتمد الحالي.')

    if transcript_changed:
        required['ocr_review'] = True
        required['notation_review'] = True
        required['scientific_reference_review'] = True
        required['independent_second_review'] = True
        reasons['ocr_review'].append('النص المنسوخ من المصدر تغيّر.')
        reasons['notation_review'].append('تغير النص قد يغير معادلات/رموزًا علمية.')
        reasons['scientific_reference_review'].append('المحتوى المصدرّي الذي تتم مقارنته بالمراجع تغيّر.')
        reasons['independent_second_review'].append('مراجعة المحتوى القديمة لم تعد مرتبطة بنفس hash.')

    if 'equation' in kinds:
        required['notation_review'] = True
        required['scientific_reference_review'] = True
        required['independent_second_review'] = True
        reasons['notation_review'].append('تم تغيير قانون أو معادلة.')
        reasons['scientific_reference_review'].append('المعادلات تغيّر المعنى العلمي المحتمل وتحتاج مراجعة مرجعية.')
        reasons['independent_second_review'].append('التغيير في المعادلات يحتاج مراجعة مستقلة جديدة عند تفعيلها.')

    if 'diagram' in kinds:
        required['diagram_review'] = True
        required['scientific_reference_review'] = True
        required['independent_second_review'] = True
        reasons['diagram_review'].append('تم تغيير رسم أو مواصفاته العلمية.')
        reasons['scientific_reference_review'].append('علاقة علمية داخل رسم تغيّرت.')
        reasons['independent_second_review'].append('التغيير في الرسم قد يغيّر التفسير العلمي.')

    if 'section' in kinds or 'approved_additions' in kinds:
        required['scientific_reference_review'] = True
        required['independent_second_review'] = True
        if 'section' in kinds:
            reasons['scientific_reference_review'].append('تم تغيير محتوى قسم من الشرح.')
            reasons['independent_second_review'].append('المحتوى المنظم تغيّر.')
        if 'approved_additions' in kinds:
            reasons['scientific_reference_review'].append('إضافة معتمدة جديدة دخلت المحتوى.')
            reasons['independent_second_review'].append('الإضافات المعتمدة تغيّر المادة التي تُراجع.')

    science_sensitive_fields = {'summary', 'objectives', 'key_terms', 'warnings'}
    if keys & science_sensitive_fields:
        required['scientific_reference_review'] = True
        required['independent_second_review'] = True
        reasons['scientific_reference_review'].append('ملخص/أهداف/مصطلحات/تحذيرات الدرس تغيّرت.')
        reasons['independent_second_review'].append('حقول تعليمية ذات معنى علمي تغيّرت.')

    # Title-only change remains publication/teacher-signoff only.
    severity = 'none'
    if any_change:
        severity = 'low'
    if required['scientific_reference_review'] or required['independent_second_review']:
        severity = 'medium'
    if transcript_changed or required['notation_review'] or required['diagram_review']:
        severity = 'high'

    rerun_order = [
        gate for gate in (
            'ocr_review',
            'notation_review',
            'diagram_review',
            'scientific_reference_review',
            'independent_second_review',
            'teacher_approval',
            'final_pdf_export',
        )
        if required[gate]
    ]

    return {
        'severity': severity,
        'any_change': any_change,
        'changed_kinds': sorted(kinds),
        'changed_keys': sorted(keys),
        'required_gates': required,
        'reasons': {k: v for k, v in reasons.items() if v},
        'recommended_order': rerun_order,
        'policy': {
            'teacher_approval_required_for_any_change': True,
            'scientific_correctness_not_inferred': True,
            'source_files_untouched': True,
            'matrix_is_deterministic': True,
        },
    }


@app.get('/api/admin/lesson-studio/jobs/{job_id}/versions/{from_version}/impact', dependencies=[Depends(require_admin)])
def lesson_version_impact(job_id: str, from_version: int, to_version: int | None = None):
    diff = compare_versions(job_id, from_version, to_version)
    return {
        'job_id': job_id,
        'from_version': from_version,
        'to_version': to_version if to_version is not None else 'current',
        'impact': change_impact(diff),
        'diff_summary': (diff.get('structured') or {}).get('summary') or {},
    }
