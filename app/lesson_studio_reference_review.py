from __future__ import annotations

import json
import os

from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .science_lesson_studio import _gemini_text, _job, _schema
from .science_reference_library import reference_context
from .security import require_admin
from .services.lesson_integrity import review_source_hash

REQUIRE_REFERENCE_REVIEW = os.getenv('LESSON_STUDIO_REQUIRE_REFERENCE_REVIEW', 'false').strip().lower() in {'1','true','yes','on'}


def _reference_review_schema() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS reference_review jsonb')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS reference_review_hash text')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS reference_review_at timestamptz')


def _review_counts(review: dict | None) -> dict:
    findings = (review or {}).get('findings') or []
    return {
        'critical': sum(1 for x in findings if x.get('severity') == 'critical'),
        'review': sum(1 for x in findings if x.get('severity') == 'review'),
        'info': sum(1 for x in findings if x.get('severity') == 'info'),
    }


def reference_review_state(job_id: str) -> dict:
    _reference_review_schema()
    row, _ = _job(job_id)
    current_hash = review_source_hash(row.get('raw_transcript') or '', row.get('structured_json') or {})
    stored_hash = row.get('reference_review_hash')
    review = row.get('reference_review') or None
    fresh = bool(review and stored_hash and stored_hash == current_hash)
    counts = _review_counts(review)
    clear = fresh and review.get('verdict') == 'aligned' and counts['critical'] == 0 and counts['review'] == 0
    return {
        'job_id': job_id,
        'configured_as_required': REQUIRE_REFERENCE_REVIEW,
        'available': bool(review),
        'fresh': fresh,
        'clear': clear,
        'verdict': review.get('verdict') if review else None,
        'counts': counts,
        'review': review,
        'policy': 'reference_is_validation_context_not_authoring_source',
    }


@app.get('/api/admin/lesson-studio/jobs/{job_id}/reference-review', dependencies=[Depends(require_admin)])
def get_reference_review(job_id: str):
    return reference_review_state(job_id)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/reference-review', dependencies=[Depends(require_admin)])
def run_reference_review(job_id: str):
    _reference_review_schema()
    row, sources = _job(job_id)
    if any(s.get('requires_review') for s in sources):
        raise HTTPException(409, 'Resolve OCR review items before scientific reference review')
    structured = row.get('structured_json') or {}
    transcript = row.get('raw_transcript') or ''
    if not structured or not transcript:
        raise HTTPException(409, 'Structured lesson and reviewed transcript are required')
    query = f"{row.get('title') or ''}\n{transcript[:12000]}"
    context = reference_context(row.get('subject') or '', row.get('grade_label') or '', query, 10)
    pages = context.get('pages') or []
    if not pages:
        review = {
            'verdict': 'insufficient_reference',
            'findings': [],
            'summary': 'لا توجد صفحات مرجعية كافية مطابقة للدرس في مكتبة المراجع الحالية.',
            'reference_pages': [],
        }
    else:
        excerpts = []
        total_chars = 0
        for p in pages:
            text = str(p.get('text') or '')
            remaining = max(0, 26000 - total_chars)
            if remaining <= 0:
                break
            text = text[:remaining]
            total_chars += len(text)
            excerpts.append(
                f"[مرجع: {p.get('document_title')} | صفحة {p.get('page_number')} | score={p.get('score')}]\n{text}"
            )
        expected = {
            'verdict': 'aligned|review_required|insufficient_reference',
            'findings': [{
                'severity': 'critical|review|info',
                'category': 'contradiction|not_covered|scientific_notation|diagram_relationship|grade_scope|other',
                'lesson_location': 'string',
                'description': 'string',
                'reference_document': 'string',
                'reference_page': 1,
                'reference_evidence': 'short paraphrase only',
            }],
            'summary': 'string',
        }
        instruction = (
            'أنت محرك مطابقة مرجعية علمية داخل منصة تعليمية. قارن شرح المدرس والنسخة المنظمة فقط بالمقاطع المرجعية المرفقة. '
            'ممنوع استخدام المعرفة العامة أو الذاكرة الخارجية. لا تصحح الدرس ولا تعيد كتابته ولا تضف معلومة جديدة إلى محتواه. '
            'إذا لم تغط المراجع نقطة في شرح المدرس، صنفها not_covered ولا تعتبرها خاطئة تلقائيًا. '
            'إذا وجدت تعارضًا صريحًا مدعومًا بصفحة مرجعية فاذكره مع رقم الصفحة. '
            'المعادلات والأرقام والوحدات وعلاقات الرسومات تحتاج حساسية عالية. أخرج JSON صالحًا فقط.'
        )
        prompt = (
            'شرح المدرس المنسوخ من المصدر:\n' + transcript + '\n\n'
            'النسخة المنظمة:\n' + json.dumps(structured, ensure_ascii=False) + '\n\n'
            'المراجع العلمية المختارة:\n' + '\n\n'.join(excerpts) + '\n\n'
            'قالب الإخراج:\n' + json.dumps(expected, ensure_ascii=False)
        )
        raw = _gemini_text([{'text': prompt}], instruction, json_mode=True)
        try:
            review = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(502, 'Scientific reference reviewer returned invalid JSON') from exc
        review['reference_pages'] = [
            {
                'document_id': p.get('document_id'),
                'document_title': p.get('document_title'),
                'page_number': p.get('page_number'),
                'score': p.get('score'),
            }
            for p in pages
        ]
    current_hash = review_source_hash(transcript, structured)
    with connect() as con:
        con.execute('''UPDATE science_lesson_jobs SET reference_review=%s::jsonb,reference_review_hash=%s,
          reference_review_at=now(),updated_at=now() WHERE id=%s''',
          (json.dumps(review, ensure_ascii=False), current_hash, job_id))
    counts = _review_counts(review)
    return {
        'job_id': job_id,
        'advisory_only': True,
        'auto_modified': False,
        'auto_approved': False,
        'verdict': review.get('verdict'),
        'counts': counts,
        'review': review,
        'reference_policy': 'validation_context_only',
    }
