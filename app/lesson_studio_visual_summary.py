from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from .main import app
from .security import require_admin
from .science_lesson_studio import _job
from .services.visual_summary import build_visual_summary, render_flowchart_svg, render_mindmap_svg, render_slides_pptx


def _summary_for_job(job_id: str) -> dict:
    row, _sources = _job(job_id)
    structured = row.get('structured_json')
    if not structured:
        raise HTTPException(409, 'Process the lesson before creating visual summaries')
    summary = build_visual_summary(dict(structured))
    summary['job_id'] = job_id
    summary['job_status'] = row.get('status')
    return summary


@app.get('/api/admin/lesson-studio/jobs/{job_id}/visual-summary', dependencies=[Depends(require_admin)])
def visual_summary(job_id: str):
    return _summary_for_job(job_id)


@app.get('/api/admin/lesson-studio/jobs/{job_id}/visual-summary/mindmap.svg', dependencies=[Depends(require_admin)])
def visual_summary_mindmap(job_id: str):
    data = render_mindmap_svg(_summary_for_job(job_id)).encode('utf-8')
    return Response(data, media_type='image/svg+xml', headers={'Content-Disposition': f'attachment; filename="lesson-{job_id}-mindmap.svg"'})


@app.get('/api/admin/lesson-studio/jobs/{job_id}/visual-summary/flowchart.svg', dependencies=[Depends(require_admin)])
def visual_summary_flowchart(job_id: str):
    data = render_flowchart_svg(_summary_for_job(job_id)).encode('utf-8')
    return Response(data, media_type='image/svg+xml', headers={'Content-Disposition': f'attachment; filename="lesson-{job_id}-flowchart.svg"'})


@app.get('/api/admin/lesson-studio/jobs/{job_id}/visual-summary/slides.pptx', dependencies=[Depends(require_admin)])
def visual_summary_slides(job_id: str):
    data = render_slides_pptx(_summary_for_job(job_id))
    return Response(
        data,
        media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',
        headers={'Content-Disposition': f'attachment; filename="lesson-{job_id}-summary.pptx"'},
    )
