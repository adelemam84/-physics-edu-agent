from __future__ import annotations

import json

from fastapi import Depends, Form, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _job, _schema
from .services.science_notation import classify_notation
from .lesson_studio_diagram_spec_history import save_diagram_spec
from .lesson_studio_version_history import snapshot_job


def _content_review_schema() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved boolean NOT NULL DEFAULT false')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved_at timestamptz')


def _load_structured(job_id: str) -> tuple[dict, dict]:
    _content_review_schema()
    with connect() as con:
        row = con.execute('SELECT * FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson studio job not found')
    structured = dict(row['structured_json'] or {})
    if not structured:
        raise HTTPException(409, 'Structured lesson is not ready')
    return dict(row), structured


def _save_structured(job_id: str, structured: dict) -> None:
    _content_review_schema()
    snapshot_job(job_id, 'structured_content_edit')
    with connect() as con:
        con.execute('''UPDATE science_lesson_jobs SET structured_json=%s::jsonb,
          teacher_approved=FALSE,teacher_approved_at=NULL,status='content_review_required',updated_at=now()
          WHERE id=%s''', (json.dumps(structured, ensure_ascii=False), job_id))


def _recount_notation_quality(structured: dict) -> None:
    items = list(structured.get('equations_or_rules') or [])
    pending = sum(1 for x in items if (x.get('notation') or {}).get('requires_review'))
    quality = dict(structured.get('notation_quality') or {})
    quality['review_required'] = pending
    quality['policy'] = quality.get('policy') or 'classification_only_no_semantic_rewrite'
    structured['notation_quality'] = quality


@app.get('/api/admin/lesson-studio/jobs/{job_id}/content-review', dependencies=[Depends(require_admin)])
def content_review(job_id: str):
    _, structured = _load_structured(job_id)
    diagrams = structured.get('diagram_specs') or []
    uncertain = structured.get('uncertain_items') or []
    sections = structured.get('sections') or []
    notations = structured.get('equations_or_rules') or []
    return {
        'job_id': job_id,
        'sections': sections,
        'uncertain_items': uncertain,
        'diagram_specs': diagrams,
        'equations_or_rules': notations,
        'summary': {
            'sections': len(sections),
            'uncertain_items': len(uncertain),
            'notations_pending_review': sum(1 for x in notations if (x.get('notation') or {}).get('requires_review')),
            'diagrams_pending_review': sum(1 for d in diagrams if (d.get('diagram_engine') or {}).get('review_required')),
            'sections_without_source_refs': sum(1 for s in sections if not (s.get('source_refs') or [])),
        },
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/parameters', dependencies=[Depends(require_admin)])
def update_diagram_parameters(job_id: str, diagram_index: int, parameters_json: str = Form(...)):
    try:
        parameters = json.loads(parameters_json or '{}')
    except json.JSONDecodeError as exc:
        raise HTTPException(400, 'parameters_json must be valid JSON') from exc
    if not isinstance(parameters, dict):
        raise HTTPException(400, 'parameters_json must be a JSON object')
    _content_review_schema()
    return save_diagram_spec(
        job_id,
        diagram_index,
        parameters,
        'Updated from the legacy Workspace parameters endpoint',
    )


@app.post('/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/approve', dependencies=[Depends(require_admin)])
def approve_diagram(job_id: str, diagram_index: int, teacher_note: str = Form('')):
    _, structured = _load_structured(job_id)
    diagrams = list(structured.get('diagram_specs') or [])
    if diagram_index < 0 or diagram_index >= len(diagrams):
        raise HTTPException(404, 'Diagram not found')
    diagram = dict(diagrams[diagram_index])
    engine = dict(diagram.get('diagram_engine') or {})
    if not engine.get('svg'):
        raise HTTPException(409, 'Diagram has no deterministic render to approve')
    engine['review_required'] = False
    engine['teacher_reviewed'] = True
    engine['teacher_note'] = teacher_note.strip()
    diagram['diagram_engine'] = engine
    diagrams[diagram_index] = diagram
    structured['diagram_specs'] = diagrams
    _save_structured(job_id, structured)
    return {'approved': True, 'diagram_index': diagram_index, 'diagram': diagram}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/uncertain/{item_index}/resolve', dependencies=[Depends(require_admin)])
def resolve_uncertain_item(job_id: str, item_index: int, resolution: str = Form(...)):
    resolution = resolution.strip()
    if not resolution:
        raise HTTPException(400, 'Resolution is required')
    _, structured = _load_structured(job_id)
    uncertain = list(structured.get('uncertain_items') or [])
    if item_index < 0 or item_index >= len(uncertain):
        raise HTTPException(404, 'Uncertain item not found')
    original = uncertain.pop(item_index)
    resolved = list(structured.get('resolved_review_items') or [])
    resolved.append({'original': original, 'resolution': resolution, 'teacher_resolved': True})
    structured['uncertain_items'] = uncertain
    structured['resolved_review_items'] = resolved
    _save_structured(job_id, structured)
    return {'resolved': True, 'remaining_uncertain_items': len(uncertain)}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/notations/{notation_index}/approve', dependencies=[Depends(require_admin)])
def approve_notation(
    job_id: str,
    notation_index: int,
    approved_expression: str = Form(...),
    teacher_note: str = Form(''),
):
    expression = approved_expression.strip()
    if not expression:
        raise HTTPException(400, 'Approved expression cannot be empty')
    _, structured = _load_structured(job_id)
    items = list(structured.get('equations_or_rules') or [])
    if notation_index < 0 or notation_index >= len(items):
        raise HTTPException(404, 'Notation item not found')
    item = dict(items[notation_index])
    original_expression = str(item.get('expression') or '')
    classification = classify_notation(expression).as_dict()
    classification['requires_review'] = False
    classification['teacher_reviewed'] = True
    classification['teacher_note'] = teacher_note.strip()
    item['expression'] = expression
    item['notation'] = classification
    item['teacher_review'] = {
        'original_expression': original_expression,
        'approved_expression': expression,
        'teacher_note': teacher_note.strip(),
        'approved': True,
    }
    items[notation_index] = item
    structured['equations_or_rules'] = items
    _recount_notation_quality(structured)
    _save_structured(job_id, structured)
    return {
        'approved': True,
        'notation_index': notation_index,
        'item': item,
        'remaining_notation_reviews': structured['notation_quality']['review_required'],
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sections/{section_index}/update', dependencies=[Depends(require_admin)])
def update_lesson_section(
    job_id: str,
    section_index: int,
    heading: str = Form(...),
    body: str = Form(...),
    source_refs_json: str = Form('[]'),
):
    heading = heading.strip()
    body = body.strip()
    if not heading or not body:
        raise HTTPException(400, 'Section heading and body are required')
    try:
        source_refs = json.loads(source_refs_json or '[]')
    except json.JSONDecodeError as exc:
        raise HTTPException(400, 'source_refs_json must be valid JSON') from exc
    if not isinstance(source_refs, list) or any(not isinstance(x, str) for x in source_refs):
        raise HTTPException(400, 'source_refs_json must be an array of strings')
    _, structured = _load_structured(job_id)
    sections = list(structured.get('sections') or [])
    if section_index < 0 or section_index >= len(sections):
        raise HTTPException(404, 'Section not found')
    section = dict(sections[section_index])
    section.update({
        'heading': heading,
        'body': body,
        'source_refs': [x.strip() for x in source_refs if x.strip()],
        'teacher_edited': True,
    })
    sections[section_index] = section
    structured['sections'] = sections
    _save_structured(job_id, structured)
    return {'updated': True, 'section_index': section_index, 'section': section}
