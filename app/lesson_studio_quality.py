from __future__ import annotations

import json

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _job, _schema
from .services.lesson_pdf_renderer import render_lesson_pdf
from .services.storage import put_bytes, storage_configured


def _quality_schema() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved boolean NOT NULL DEFAULT false')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved_at timestamptz')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS quality_snapshot jsonb')


def quality_snapshot(job_id: str) -> dict:
    _quality_schema()
    row, sources = _job(job_id)
    structured = row['structured_json'] or {}
    source_pending = sum(1 for s in sources if s.get('requires_review'))
    uncertain = list(structured.get('uncertain_items') or [])
    diagrams = list(structured.get('diagram_specs') or [])
    diagram_pending = 0
    for d in diagrams:
        engine = d.get('diagram_engine') or {}
        if not engine.get('svg') or engine.get('review_required'):
            diagram_pending += 1
    sections = list(structured.get('sections') or [])
    sections_without_source_refs = sum(1 for s in sections if not (s.get('source_refs') or []))
    checks = [
        {'id': 'source_preserved', 'ok': int(row['source_count'] or 0) == len(sources) and len(sources) > 0, 'value': len(sources)},
        {'id': 'ocr_review_clear', 'ok': source_pending == 0, 'value': source_pending},
        {'id': 'structured_content_ready', 'ok': bool(structured), 'value': bool(structured)},
        {'id': 'uncertainty_clear', 'ok': len(uncertain) == 0, 'value': len(uncertain)},
        {'id': 'diagram_review_clear', 'ok': diagram_pending == 0, 'value': diagram_pending},
        {'id': 'section_provenance', 'ok': sections_without_source_refs == 0 if sections else True, 'value': sections_without_source_refs},
    ]
    preapproval_ready = all(x['ok'] for x in checks)
    snapshot = {
        'job_id': job_id,
        'checks': checks,
        'preapproval_ready': preapproval_ready,
        'teacher_approved': bool(row.get('teacher_approved')),
        'final_ready': preapproval_ready and bool(row.get('teacher_approved')),
        'policy': {
            'no_silent_scientific_correction': True,
            'teacher_is_final_gate': True,
            'precise_diagrams_require_deterministic_or_reviewed_output': True,
        },
    }
    with connect() as con:
        con.execute('UPDATE science_lesson_jobs SET quality_snapshot=%s::jsonb,updated_at=now() WHERE id=%s',
                    (json.dumps(snapshot, ensure_ascii=False), job_id))
    return snapshot


@app.get('/api/admin/lesson-studio/jobs/{job_id}/quality', dependencies=[Depends(require_admin)])
def lesson_quality(job_id: str):
    return quality_snapshot(job_id)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/approve-content', dependencies=[Depends(require_admin)])
def approve_lesson_content(job_id: str):
    snap = quality_snapshot(job_id)
    if not snap['preapproval_ready']:
        failed = [x for x in snap['checks'] if not x['ok']]
        raise HTTPException(409, {'message': 'Lesson failed quality gate', 'failed': failed})
    with connect() as con:
        con.execute('''UPDATE science_lesson_jobs SET teacher_approved=TRUE,teacher_approved_at=now(),
          status='approved_for_export',updated_at=now() WHERE id=%s''', (job_id,))
    return {'approved': True, 'job_id': job_id, 'final_ready': True}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/revoke-content-approval', dependencies=[Depends(require_admin)])
def revoke_lesson_content_approval(job_id: str):
    _quality_schema()
    with connect() as con:
        if not con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone():
            raise HTTPException(404, 'Lesson studio job not found')
        con.execute("UPDATE science_lesson_jobs SET teacher_approved=FALSE,teacher_approved_at=NULL,status='content_review_required',updated_at=now() WHERE id=%s", (job_id,))
    return {'revoked': True, 'job_id': job_id}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/final-pdf', dependencies=[Depends(require_admin)])
def export_final_lesson_pdf(job_id: str):
    snap = quality_snapshot(job_id)
    if not snap['final_ready']:
        failed = [x for x in snap['checks'] if not x['ok']]
        if not snap['teacher_approved']:
            failed.append({'id': 'teacher_approval', 'ok': False, 'value': False})
        raise HTTPException(409, {'message': 'Final PDF export blocked by quality gate', 'failed': failed})
    row, _ = _job(job_id)
    data = render_lesson_pdf(row['structured_json'])
    key = f'lesson-studio/{job_id}/final-approved.pdf'
    if storage_configured():
        put_bytes(key, data, 'application/pdf')
        with connect() as con:
            con.execute("UPDATE science_lesson_jobs SET pdf_object_key=%s,status='final_pdf_ready',updated_at=now() WHERE id=%s", (key, job_id))
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="science-lesson-{job_id}.pdf"'})
