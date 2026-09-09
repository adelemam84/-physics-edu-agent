from __future__ import annotations

import json
import uuid

from fastapi import Depends, Form, HTTPException
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import OUTPUT_MODES, _gemini_text, _organize, _schema
from .lesson_studio_version_history import snapshot_job
from .services.lesson_integrity import review_source_hash
from .services.lesson_release_state import invalidate_release_state

STYLE_KEY = 'lesson_studio_style_profile'


class TeacherStyleProfile(BaseModel):
    heading_style: str = Field(default='clear_hierarchy', max_length=80)
    example_style: str = Field(default='step_by_step', max_length=80)
    summary_style: str = Field(default='concise_points', max_length=80)
    visual_density: str = Field(default='balanced', max_length=40)
    language_tone: str = Field(default='clear_educational_arabic', max_length=80)
    preferred_callouts: list[str] = Field(default_factory=lambda: ['definition', 'law', 'example', 'warning'], max_length=12)
    custom_notes: str = Field(default='', max_length=2000)


def _enhancement_schema() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS ai_suggestions jsonb')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS ai_suggestions_source_hash text')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS approved_additions jsonb')
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_editions(
          id uuid PRIMARY KEY,
          job_id uuid NOT NULL REFERENCES science_lesson_jobs(id) ON DELETE CASCADE,
          output_mode text NOT NULL,
          grade_label text,
          structured_json jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_science_lesson_editions_job ON science_lesson_editions(job_id,created_at DESC)')


def _style_profile() -> dict:
    with connect() as con:
        row = con.execute('SELECT value FROM settings WHERE key=%s', (STYLE_KEY,)).fetchone()
    if not row or not row.get('value'):
        return TeacherStyleProfile().model_dump()
    try:
        return TeacherStyleProfile.model_validate(json.loads(row['value'])).model_dump()
    except Exception:
        return TeacherStyleProfile().model_dump()


def _normalize_suggestion_payload(value, *, error_status: int = 502) -> dict:
    """Accept only a mapping with a list of mapping suggestions and return a safe normalized copy."""
    if not isinstance(value, dict):
        raise HTTPException(error_status, 'Suggestion engine returned an unexpected payload shape')
    items = value.get('suggestions')
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise HTTPException(error_status, 'Suggestion engine returned an unexpected payload shape')
    normalized = dict(value)
    normalized['suggestions'] = [dict(item) for item in items]
    return normalized


@app.get('/api/admin/lesson-studio/style-profile', dependencies=[Depends(require_admin)])
def get_teacher_style_profile():
    return {'profile': _style_profile(), 'affects_scientific_meaning': False}


@app.put('/api/admin/lesson-studio/style-profile', dependencies=[Depends(require_admin)])
def update_teacher_style_profile(profile: TeacherStyleProfile):
    payload = profile.model_dump()
    with connect() as con:
        con.execute('''INSERT INTO settings(key,value) VALUES(%s,%s)
          ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
          (STYLE_KEY, json.dumps(payload, ensure_ascii=False)))
    return {'saved': True, 'profile': payload, 'affects_scientific_meaning': False}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/suggestions', dependencies=[Depends(require_admin)])
def generate_lesson_suggestions(job_id: str):
    _enhancement_schema()
    with connect() as con:
        job = con.execute('SELECT id,title,subject,grade_label,output_mode,status,raw_transcript,structured_json FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, 'Lesson studio job not found')
    if not job['structured_json'] or not job['raw_transcript']:
        raise HTTPException(409, 'Process and review the lesson before generating suggestions')
    structured_at_start = dict(job['structured_json'] or {})
    source_hash = review_source_hash(str(job['raw_transcript'] or ''), structured_at_start)
    profile = _style_profile()
    schema = {
        'suggestions': [{
            'type': 'example|diagram|definition|common_mistake|transition|summary_improvement|pedagogy',
            'location': 'section heading or description',
            'proposal': 'string',
            'reason': 'string',
            'requires_new_scientific_content': True,
        }]
    }
    prompt = (
        'اقترح تحسينات تعليمية فقط ولا تعدّل النص الأصلي. كل اقتراح يجب أن يبقى منفصلًا حتى يعتمد المدرس. '
        'إذا كان الاقتراح يضيف حقيقة أو مثالًا أو معلومة غير موجودة في المصدر فضع requires_new_scientific_content=true. '
        'لا تعتبر الاقتراح معتمدًا ولا تدمجه في الشرح. أخرج JSON صالحًا فقط.'
    )
    raw = _gemini_text([{'text': 'النمط المفضل للمدرس:\n' + json.dumps(profile, ensure_ascii=False) +
        '\n\nالمحتوى المنظم:\n' + json.dumps(structured_at_start, ensure_ascii=False) +
        '\n\nقالب الإخراج:\n' + json.dumps(schema, ensure_ascii=False)}], prompt, json_mode=True)
    try:
        suggestions = _normalize_suggestion_payload(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(502, 'Suggestion engine returned invalid JSON') from exc
    with connect() as con:
        current = con.execute('SELECT raw_transcript,structured_json FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not current:
            raise HTTPException(404, 'Lesson studio job not found')
        current_hash = review_source_hash(
            str(current.get('raw_transcript') or ''),
            dict(current.get('structured_json') or {}),
        )
        if current_hash != source_hash:
            raise HTTPException(409, 'Lesson changed while suggestions were generated; generate suggestions again')
        con.execute('''UPDATE science_lesson_jobs SET ai_suggestions=%s::jsonb,
          ai_suggestions_source_hash=%s,updated_at=now() WHERE id=%s''',
          (json.dumps(suggestions, ensure_ascii=False), source_hash, job_id))
    return {
        'job_id': job_id,
        'advisory_only': True,
        'auto_merged': False,
        'bound_to_content_hash': source_hash,
        **suggestions,
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/suggestions/{suggestion_index}/approve', dependencies=[Depends(require_admin)])
def approve_lesson_suggestion(job_id: str, suggestion_index: int, teacher_note: str = Form('')):
    _enhancement_schema()
    snapshot_job(job_id, 'approved_ai_suggestion', metadata={'suggestion_index': suggestion_index})
    with connect() as con:
        job = con.execute('''SELECT ai_suggestions,ai_suggestions_source_hash,approved_additions,
          raw_transcript,structured_json FROM science_lesson_jobs WHERE id=%s FOR UPDATE''',
          (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        structured = dict(job['structured_json'] or {})
        current_hash = review_source_hash(str(job.get('raw_transcript') or ''), structured)
        if not job.get('ai_suggestions_source_hash') or job.get('ai_suggestions_source_hash') != current_hash:
            raise HTTPException(409, 'Suggestions are stale for the current lesson; generate them again before approval')
        payload = _normalize_suggestion_payload(job.get('ai_suggestions'), error_status=409)
        suggestions = payload['suggestions']
        if suggestion_index < 0 or suggestion_index >= len(suggestions):
            raise HTTPException(404, 'Suggestion not found')
        selected = dict(suggestions[suggestion_index])
        selected['teacher_approved'] = True
        selected['teacher_note'] = teacher_note.strip()
        approved = list(job['approved_additions'] or [])
        approved.append(selected)
        structured['approved_additions'] = approved
        con.execute('''UPDATE science_lesson_jobs SET approved_additions=%s::jsonb,
          structured_json=%s::jsonb,ai_suggestions_source_hash=NULL WHERE id=%s''',
          (json.dumps(approved, ensure_ascii=False), json.dumps(structured, ensure_ascii=False), job_id))
        invalidate_release_state(con, job_id, status='content_review_required')
    return {
        'approved': True,
        'suggestion': selected,
        'approved_additions_count': len(approved),
        'previous_approval_invalidated': True,
        'previous_pdf_invalidated': True,
        'remaining_suggestions_require_regeneration': True,
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/editions', dependencies=[Depends(require_admin)])
def create_lesson_edition(job_id: str, output_mode: str = Form(...), grade_label: str = Form('')):
    _enhancement_schema()
    if output_mode not in OUTPUT_MODES:
        raise HTTPException(400, 'Invalid output mode')
    with connect() as con:
        job = con.execute('SELECT id,title,subject,grade_label,raw_transcript FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
        pending = con.execute('SELECT count(*) n FROM science_lesson_sources WHERE job_id=%s AND requires_review=TRUE', (job_id,)).fetchone()['n']
    if not job:
        raise HTTPException(404, 'Lesson studio job not found')
    if int(pending or 0) > 0:
        raise HTTPException(409, 'Resolve OCR review items before creating editions')
    if not job['raw_transcript']:
        raise HTTPException(409, 'Lesson transcript is not ready')
    target_grade = grade_label.strip() or (job['grade_label'] or '')
    structured = _organize(job['raw_transcript'], job['subject'], target_grade, job['title'], output_mode)
    edition_id = str(uuid.uuid4())
    with connect() as con:
        con.execute('''INSERT INTO science_lesson_editions(id,job_id,output_mode,grade_label,structured_json)
          VALUES(%s,%s,%s,%s,%s::jsonb)''',
          (edition_id, job_id, output_mode, target_grade, json.dumps(structured, ensure_ascii=False)))
    return {'id': edition_id, 'job_id': job_id, 'output_mode': output_mode, 'grade_label': target_grade, 'structured': structured}


@app.get('/api/admin/lesson-studio/jobs/{job_id}/editions', dependencies=[Depends(require_admin)])
def list_lesson_editions(job_id: str):
    _enhancement_schema()
    with connect() as con:
        if not con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone():
            raise HTTPException(404, 'Lesson studio job not found')
        rows = list(con.execute('SELECT id,output_mode,grade_label,created_at FROM science_lesson_editions WHERE job_id=%s ORDER BY created_at DESC', (job_id,)).fetchall())
    return {'job_id': job_id, 'editions': [dict(x) for x in rows]}