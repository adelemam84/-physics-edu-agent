from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from .db import connect
from .main import app
from .security import require_admin
from .lesson_studio_quality import quality_snapshot
from .science_lesson_studio import _job
from .services.lesson_pdf_renderer import PDF_PRESETS, render_lesson_pdf
from .services.storage import put_bytes, storage_configured


@app.get('/api/admin/lesson-studio/pdf-presets', dependencies=[Depends(require_admin)])
def lesson_pdf_presets():
    return {
        'presets': [
            {'id': 'a4', 'label': 'A4 للطباعة', 'width': PDF_PRESETS['a4']['width'], 'height': PDF_PRESETS['a4']['height']},
            {'id': 'mobile', 'label': 'نسخة قراءة للموبايل', 'width': PDF_PRESETS['mobile']['width'], 'height': PDF_PRESETS['mobile']['height']},
        ],
        'same_scientific_content': True,
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/final-pdf/{preset}', dependencies=[Depends(require_admin)])
def export_lesson_pdf_preset(job_id: str, preset: str):
    if preset not in PDF_PRESETS:
        raise HTTPException(400, 'Unsupported PDF preset')
    snap = quality_snapshot(job_id)
    if not snap['final_ready']:
        failed = [x for x in snap['checks'] if not x['ok']]
        if not snap['teacher_approved']:
            failed.append({'id': 'teacher_approval', 'ok': False, 'value': False})
        raise HTTPException(409, {'message': 'Final PDF export blocked by quality gate', 'failed': failed})
    row, _ = _job(job_id)
    data = render_lesson_pdf(row['structured_json'], preset=preset)
    key = f'lesson-studio/{job_id}/final-approved-{preset}.pdf'
    if storage_configured():
        put_bytes(key, data, 'application/pdf')
        with connect() as con:
            con.execute("UPDATE science_lesson_jobs SET pdf_object_key=%s,status='final_pdf_ready',updated_at=now() WHERE id=%s", (key, job_id))
    filename = f'science-lesson-{job_id}-{preset}.pdf'
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{filename}"'})
