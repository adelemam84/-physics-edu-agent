from __future__ import annotations

import json
import os

import httpx
from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _job, _schema
from .services.lesson_integrity import review_source_hash

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
REVIEW_MODEL = os.getenv('LESSON_STUDIO_REVIEW_MODEL', 'gpt-5.6-sol').strip() or 'gpt-5.6-sol'


def _schema_review() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review jsonb')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review_provider text')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review_at timestamptz')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review_source_hash text')


def reviewer_status() -> dict:
    return {
        'configured': bool(OPENAI_API_KEY),
        'provider': 'openai' if OPENAI_API_KEY else None,
        'model': REVIEW_MODEL,
        'role': 'independent_advisory_scientific_review',
        'can_modify_lesson': False,
        'can_auto_approve': False,
        'can_publish': False,
    }


def _extract_output_text(payload: dict) -> str:
    texts: list[str] = []
    for item in payload.get('output') or []:
        if item.get('type') != 'message':
            continue
        for block in item.get('content') or []:
            if block.get('type') == 'output_text' and block.get('text'):
                texts.append(str(block['text']))
    return '\n'.join(texts).strip()


def _openai_review(transcript: str, structured: dict, subject: str, grade_label: str) -> dict:
    if not OPENAI_API_KEY:
        raise HTTPException(503, 'Independent OpenAI reviewer is not configured')
    expected = {
        'verdict': 'clear|review_required',
        'findings': [{
            'severity': 'critical|review|info',
            'category': 'source_fidelity|scientific_notation|unsupported_addition|diagram|grade_clarity|other',
            'location': 'string',
            'description': 'string',
            'source_evidence': 'string',
        }],
        'summary': 'string',
    }
    developer = (
        'أنت مراجع علمي ثانٍ مستقل داخل منصة تعليمية. قارن النسخة المنظمة بالنص الأصلي فقط. '
        'لا تضف معرفة خارجية لتصحيح المدرس، ولا تعيد كتابة الدرس، ولا تعتمد المحتوى. '
        'ابحث خصوصًا عن: تغيير المعنى بين الأصل والمنظم، أرقام أو وحدات أو معادلات مختلفة، '
        'حقائق أضافها المنظم ولا يدعمها الأصل، ورسومات مقترحة قد تشفر علاقة غير موجودة في المصدر. '
        'وضوح اللغة للمرحلة يمكن تقييمه كأسلوب، لكن لا تغيّر الحقيقة العلمية. '
        'أخرج JSON صالحًا فقط مطابقًا للقالب المطلوب.'
    )
    user = (
        f'المادة: {subject}\nالمرحلة/الصف: {grade_label}\n\n'
        'النص الأصلي المنسوخ من أوراق المدرس:\n' + transcript + '\n\n'
        'النسخة المنظمة الحالية:\n' + json.dumps(structured, ensure_ascii=False) + '\n\n'
        'قالب الإخراج:\n' + json.dumps(expected, ensure_ascii=False)
    )
    body = {
        'model': REVIEW_MODEL,
        'reasoning': {'effort': 'high'},
        'input': [
            {'role': 'developer', 'content': [{'type': 'input_text', 'text': developer}]},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': user}]},
        ],
    }
    try:
        response = httpx.post(
            'https://api.openai.com/v1/responses',
            headers={'Authorization': f'Bearer {OPENAI_API_KEY}', 'Content-Type': 'application/json'},
            json=body,
            timeout=120,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Independent scientific reviewer is temporarily unavailable') from exc
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[:500]
        raise HTTPException(502, {'message': 'OpenAI reviewer request failed', 'provider_status': response.status_code, 'provider_detail': detail})
    text = _extract_output_text(response.json())
    if not text:
        raise HTTPException(502, 'OpenAI reviewer returned no text')
    try:
        review = json.loads(text)
    except json.JSONDecodeError:
        return {
            'verdict': 'review_required',
            'findings': [{
                'severity': 'review',
                'category': 'reviewer_output_format',
                'location': 'second_reviewer',
                'description': 'تعذر تحليل نتيجة المراجع الثاني كـ JSON؛ يلزم إعادة المراجعة.',
                'source_evidence': '',
            }],
            'summary': text[:1500],
        }
    findings = review.get('findings') if isinstance(review, dict) else None
    if not isinstance(findings, list):
        review = {
            'verdict': 'review_required',
            'findings': [{
                'severity': 'review',
                'category': 'reviewer_output_schema',
                'location': 'second_reviewer',
                'description': 'نتيجة المراجع الثاني لا تطابق البنية المطلوبة.',
                'source_evidence': '',
            }],
            'summary': str(review)[:1500],
        }
    return review


@app.get('/api/admin/lesson-studio/second-reviewer/status', dependencies=[Depends(require_admin)])
def second_reviewer_status():
    return reviewer_status()


@app.post('/api/admin/lesson-studio/jobs/{job_id}/second-review', dependencies=[Depends(require_admin)])
def run_second_review(job_id: str):
    _schema_review()
    row, sources = _job(job_id)
    if any(s.get('requires_review') for s in sources):
        raise HTTPException(409, 'Resolve OCR review items before independent scientific review')
    structured = row['structured_json'] or {}
    transcript = row['raw_transcript'] or ''
    if not structured or not transcript:
        raise HTTPException(409, 'Structured lesson and transcript are required')
    source_hash = review_source_hash(transcript, structured)
    review = _openai_review(transcript, structured, row['subject'], row['grade_label'] or '')
    with connect() as con:
        con.execute('''UPDATE science_lesson_jobs SET second_review=%s::jsonb,
          second_review_provider=%s,second_review_at=now(),second_review_source_hash=%s,
          updated_at=now() WHERE id=%s''',
          (json.dumps(review, ensure_ascii=False), f'openai:{REVIEW_MODEL}', source_hash, job_id))
    critical = sum(1 for x in review.get('findings', []) if x.get('severity') == 'critical')
    needs_review = sum(1 for x in review.get('findings', []) if x.get('severity') in {'critical', 'review'})
    return {
        'job_id': job_id,
        'provider': 'openai',
        'model': REVIEW_MODEL,
        'source_hash': source_hash,
        'advisory_only': True,
        'auto_modified': False,
        'auto_approved': False,
        'critical_findings': critical,
        'review_findings': needs_review,
        'review': review,
    }
