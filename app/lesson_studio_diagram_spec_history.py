from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import Body, Depends, Form, HTTPException

from .db import connect
from .lesson_studio_version_history import snapshot_job
from .main import app
from .science_lesson_studio import _schema
from .security import require_admin
from .services.lesson_release_state import invalidate_release_state
from .services.science_diagram_parameterized import PARAMETERIZED_KINDS
from .services.science_diagram_specs import preview_diagram_spec, schema_catalog, validate_diagram_spec


def _diagram_history_schema() -> None:
    """Ensure diagram-version persistence exists; release-state columns migrate at startup."""
    _schema()
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_diagram_spec_versions(
          id uuid PRIMARY KEY,
          job_id uuid NOT NULL REFERENCES science_lesson_jobs(id) ON DELETE CASCADE,
          diagram_index integer NOT NULL,
          version_no integer NOT NULL,
          action text NOT NULL,
          note text,
          kind text NOT NULL,
          title text,
          parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
          diagram_hash text NOT NULL,
          metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(job_id,diagram_index,version_no)
        )''')
        con.execute('''CREATE INDEX IF NOT EXISTS idx_science_lesson_diagram_spec_versions
          ON science_lesson_diagram_spec_versions(job_id,diagram_index,version_no DESC)''')
        con.execute('''CREATE INDEX IF NOT EXISTS idx_science_lesson_diagram_spec_kind_versions
          ON science_lesson_diagram_spec_versions(job_id,diagram_index,kind,version_no DESC)''')


def _diagram_hash(kind: str, parameters: dict) -> str:
    payload = json.dumps(
        {'kind': kind, 'parameters': parameters or {}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _diagram_from_structured(structured: dict, diagram_index: int) -> tuple[list[dict], dict, str]:
    diagrams = [dict(x) for x in (structured.get('diagram_specs') or [])]
    if diagram_index < 0 or diagram_index >= len(diagrams):
        raise HTTPException(404, 'Diagram not found')
    diagram = dict(diagrams[diagram_index])
    kind = str(diagram.get('normalized_kind') or diagram.get('kind') or '')
    if kind not in PARAMETERIZED_KINDS:
        raise HTTPException(400, 'This diagram kind does not support explicit parameter editing')
    return diagrams, diagram, kind


def _load_job_diagram(job_id: str, diagram_index: int) -> tuple[dict, dict, list[dict], dict]:
    _diagram_history_schema()
    with connect() as con:
        row = con.execute('''SELECT id,structured_json,status,teacher_approved
          FROM science_lesson_jobs WHERE id=%s''', (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson studio job not found')
    structured = dict(row.get('structured_json') or {})
    diagrams, diagram, _ = _diagram_from_structured(structured, diagram_index)
    return dict(row), structured, diagrams, diagram


def prepare_diagram_spec(kind: str, title: str, parameters: dict | None) -> dict:
    validation = validate_diagram_spec(kind, parameters)
    if not validation.get('valid'):
        return {
            'valid': False,
            'kind': kind,
            'title': title,
            'validation': validation,
            'renderer_called': False,
            'render': None,
            'normalized': None,
        }
    preview = preview_diagram_spec(kind, title, validation['normalized'])
    if not preview.get('valid') or not preview.get('render'):
        return {
            'valid': False,
            'kind': kind,
            'title': title,
            'validation': validation,
            'renderer_called': bool(preview.get('renderer_called')),
            'render': preview.get('render'),
            'normalized': validation['normalized'],
        }
    render = dict(preview['render'])
    render['schema_validated'] = True
    render['spec_validation'] = validation
    render['review_required'] = True
    render['teacher_reviewed'] = False
    render.pop('teacher_note', None)
    return {
        'valid': True,
        'kind': kind,
        'title': title,
        'validation': validation,
        'renderer_called': True,
        'render': render,
        'normalized': validation['normalized'],
        'svg': preview.get('svg'),
        'review_required': True,
        'approval_state_changed': False,
    }


def _insert_snapshot(
    con,
    job_id: str,
    diagram_index: int,
    diagram: dict,
    action: str,
    note: str = '',
    metadata: dict | None = None,
) -> dict:
    kind = str(diagram.get('normalized_kind') or diagram.get('kind') or '')
    params = dict(diagram.get('parameters') or {})
    title = str(diagram.get('title') or '')
    digest = _diagram_hash(kind, params)
    next_no = int(con.execute(
        '''SELECT COALESCE(max(version_no),0)+1 n
           FROM science_lesson_diagram_spec_versions
           WHERE job_id=%s AND diagram_index=%s''',
        (job_id, diagram_index),
    ).fetchone()['n'])
    version_id = str(uuid.uuid4())
    engine = dict(diagram.get('diagram_engine') or {})
    engine.pop('svg', None)
    meta = {
        'normalized_kind': diagram.get('normalized_kind'),
        'teacher_parameter_edit': bool(diagram.get('teacher_parameter_edit')),
        'engine': engine,
        **(metadata or {}),
    }
    con.execute('''INSERT INTO science_lesson_diagram_spec_versions(
      id,job_id,diagram_index,version_no,action,note,kind,title,parameters,diagram_hash,metadata)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)''',
      (
          version_id,
          job_id,
          diagram_index,
          next_no,
          action[:120],
          note[:1000],
          kind,
          title[:500],
          json.dumps(params, ensure_ascii=False),
          digest,
          json.dumps(meta, ensure_ascii=False),
      ),
    )
    return {
        'id': version_id,
        'job_id': job_id,
        'diagram_index': diagram_index,
        'version_no': next_no,
        'diagram_hash': digest,
        'action': action,
    }


def _snapshot_diagram(
    job_id: str,
    diagram_index: int,
    diagram: dict,
    action: str,
    note: str = '',
    metadata: dict | None = None,
) -> dict:
    _diagram_history_schema()
    with connect() as con:
        # Serialize allocation of version_no for all writes touching this job.
        locked = con.execute(
            'SELECT id FROM science_lesson_jobs WHERE id=%s FOR UPDATE',
            (job_id,),
        ).fetchone()
        if not locked:
            raise HTTPException(404, 'Lesson studio job not found')
        return _insert_snapshot(
            con,
            job_id,
            diagram_index,
            diagram,
            action,
            note,
            metadata,
        )


def ensure_diagram_baseline(job_id: str, diagram_index: int) -> dict:
    _diagram_history_schema()
    with connect() as con:
        row = con.execute(
            'SELECT structured_json FROM science_lesson_jobs WHERE id=%s FOR UPDATE',
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson studio job not found')
        structured = dict(row.get('structured_json') or {})
        _, diagram, kind = _diagram_from_structured(structured, diagram_index)
        existing = con.execute('''SELECT id,version_no,diagram_hash
          FROM science_lesson_diagram_spec_versions
          WHERE job_id=%s AND diagram_index=%s AND kind=%s
          ORDER BY version_no ASC LIMIT 1''',
          (job_id, diagram_index, kind)).fetchone()
        if existing:
            return dict(existing)
        return _insert_snapshot(
            con,
            job_id,
            diagram_index,
            diagram,
            'initial_diagram_spec',
            'Automatic baseline before diagram-spec version tracking',
            {'baseline_for_kind': kind},
        )


def _persist_diagram_spec(
    job_id: str,
    diagram_index: int,
    prepared: dict,
    note: str,
    *,
    action: str,
    restored_from_version: int | None = None,
    capture_pre_action: str | None = None,
    capture_pre_note: str = '',
    capture_pre_metadata: dict | None = None,
) -> dict:
    _diagram_history_schema()
    ensure_diagram_baseline(job_id, diagram_index)
    snapshot_job(
        job_id,
        f'{action}_prechange',
        note or f'Diagram {diagram_index} specification changed',
        {
            'diagram_index': diagram_index,
            'diagram_kind': prepared.get('kind'),
            'restored_from_version': restored_from_version,
        },
    )

    pre_change_version = None
    with connect() as con:
        # One row lock protects both against lost updates while editing the same
        # lesson and against duplicate version numbers. The job mutation and its
        # immutable diagram-version record commit or roll back together.
        row = con.execute(
            'SELECT structured_json FROM science_lesson_jobs WHERE id=%s FOR UPDATE',
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson studio job not found')
        structured = dict(row.get('structured_json') or {})
        diagrams, diagram, kind = _diagram_from_structured(structured, diagram_index)
        if kind != prepared.get('kind'):
            raise HTTPException(409, 'Diagram kind changed while editing; reload the workspace and retry')

        if capture_pre_action:
            pre_change_version = _insert_snapshot(
                con,
                job_id,
                diagram_index,
                diagram,
                capture_pre_action,
                capture_pre_note,
                capture_pre_metadata,
            )

        updated = dict(diagram)
        updated['parameters'] = dict(prepared['normalized'] or {})
        updated['diagram_engine'] = dict(prepared['render'] or {})
        updated['teacher_parameter_edit'] = True
        updated['diagram_spec_schema'] = 'diagram-specs-v1'
        updated['diagram_spec_versioned'] = True
        if restored_from_version is not None:
            updated['diagram_spec_restored_from_version'] = restored_from_version
        else:
            updated.pop('diagram_spec_restored_from_version', None)
        diagrams[diagram_index] = updated
        structured['diagram_specs'] = diagrams

        con.execute(
            '''UPDATE science_lesson_jobs SET structured_json=%s::jsonb,updated_at=now()
               WHERE id=%s''',
            (json.dumps(structured, ensure_ascii=False), job_id),
        )
        invalidate_release_state(con, job_id, status='content_review_required')

        version = _insert_snapshot(
            con,
            job_id,
            diagram_index,
            updated,
            action,
            note,
            {
                'schema_version': 'diagram-specs-v1',
                'approval_invalidated': True,
                'external_reviews_invalidated': True,
                'previous_pdf_invalidated': True,
                'restored_from_version': restored_from_version,
            },
        )

    return {
        'updated': True,
        'job_id': job_id,
        'diagram_index': diagram_index,
        'diagram': updated,
        'spec_version': version,
        'pre_change_spec_version': pre_change_version,
        'valid': True,
        'issues': [],
        'teacher_approval_invalidated': True,
        'second_review_invalidated': True,
        'reference_review_invalidated': True,
        'previous_pdf_invalidated': True,
    }


def save_diagram_spec(job_id: str, diagram_index: int, parameters: dict, note: str = '') -> dict:
    _, _, _, diagram = _load_job_diagram(job_id, diagram_index)
    kind = str(diagram.get('normalized_kind') or diagram.get('kind') or '')
    title = str(diagram.get('title') or 'رسم توضيحي')
    prepared = prepare_diagram_spec(kind, title, parameters)
    if not prepared.get('valid'):
        raise HTTPException(
            422,
            detail={
                'message': 'Diagram specification failed strict validation; nothing was saved',
                'validation': prepared.get('validation'),
                'renderer_called': prepared.get('renderer_called'),
            },
        )
    return _persist_diagram_spec(
        job_id,
        diagram_index,
        prepared,
        note.strip(),
        action='diagram_spec_saved',
    )


@app.get('/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec-history', dependencies=[Depends(require_admin)])
def diagram_spec_history(job_id: str, diagram_index: int):
    ensure_diagram_baseline(job_id, diagram_index)
    _, _, _, diagram = _load_job_diagram(job_id, diagram_index)
    kind = str(diagram.get('normalized_kind') or diagram.get('kind') or '')
    current_params = dict(diagram.get('parameters') or {})
    current_hash = _diagram_hash(kind, current_params)
    catalog = schema_catalog()['kinds'].get(kind) or {}
    with connect() as con:
        rows = list(con.execute('''SELECT id,version_no,action,note,kind,title,parameters,
          diagram_hash,metadata,created_at
          FROM science_lesson_diagram_spec_versions
          WHERE job_id=%s AND diagram_index=%s AND kind=%s
          ORDER BY version_no DESC''',
          (job_id, diagram_index, kind)).fetchall())
    return {
        'job_id': job_id,
        'diagram_index': diagram_index,
        'kind': kind,
        'title': diagram.get('title'),
        'current': {
            'parameters': current_params,
            'diagram_hash': current_hash,
            'schema_validated': bool((diagram.get('diagram_engine') or {}).get('schema_validated')),
            'review_required': bool((diagram.get('diagram_engine') or {}).get('review_required')),
        },
        'schema': catalog,
        'versions': [dict(x) for x in rows],
        'policy': {
            'immutable_versions': True,
            'invalid_new_specs_never_persist': True,
            'history_scoped_to_current_diagram_kind': True,
            'serialized_version_allocation': True,
            'job_update_and_version_insert_are_atomic': True,
            'restore_is_diagram_only': True,
            'restore_revalidates_with_current_schema': True,
            'restore_invalidates_lesson_approval_and_external_reviews': True,
        },
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec/preview', dependencies=[Depends(require_admin)])
def preview_job_diagram_spec(job_id: str, diagram_index: int, payload: dict = Body(...)):
    _, _, _, diagram = _load_job_diagram(job_id, diagram_index)
    kind = str(diagram.get('normalized_kind') or diagram.get('kind') or '')
    title = str(diagram.get('title') or 'رسم توضيحي')
    parameters = payload.get('parameters')
    prepared = prepare_diagram_spec(kind, title, parameters)
    return {
        **prepared,
        'job_id': job_id,
        'diagram_index': diagram_index,
        'persisted': False,
        'approval_state_changed': False,
    }


@app.put('/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec', dependencies=[Depends(require_admin)])
def save_job_diagram_spec(job_id: str, diagram_index: int, payload: dict = Body(...)):
    parameters = payload.get('parameters')
    if not isinstance(parameters, dict):
        raise HTTPException(400, 'parameters must be a JSON object')
    note = str(payload.get('note') or '').strip()
    return save_diagram_spec(job_id, diagram_index, parameters, note)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec-history/{version_no}/restore', dependencies=[Depends(require_admin)])
def restore_diagram_spec_version(
    job_id: str,
    diagram_index: int,
    version_no: int,
    teacher_note: str = Form(''),
):
    ensure_diagram_baseline(job_id, diagram_index)
    _, _, _, current = _load_job_diagram(job_id, diagram_index)
    current_kind = str(current.get('normalized_kind') or current.get('kind') or '')
    with connect() as con:
        row = con.execute('''SELECT version_no,kind,title,parameters,diagram_hash
          FROM science_lesson_diagram_spec_versions
          WHERE job_id=%s AND diagram_index=%s AND version_no=%s AND kind=%s''',
          (job_id, diagram_index, version_no, current_kind)).fetchone()
    if not row:
        raise HTTPException(404, 'Diagram specification version not found for the current diagram kind')

    prepared = prepare_diagram_spec(
        current_kind,
        str(current.get('title') or row.get('title') or 'رسم توضيحي'),
        dict(row.get('parameters') or {}),
    )
    if not prepared.get('valid'):
        raise HTTPException(
            409,
            detail={
                'message': 'Stored diagram version no longer satisfies the current schema',
                'validation': prepared.get('validation'),
            },
        )

    result = _persist_diagram_spec(
        job_id,
        diagram_index,
        prepared,
        teacher_note.strip() or f'Restored diagram specification version {version_no}',
        action='diagram_spec_restored',
        restored_from_version=version_no,
        capture_pre_action='pre_diagram_spec_restore',
        capture_pre_note=f'Automatic snapshot before restoring diagram spec v{version_no}',
        capture_pre_metadata={'restore_target_version': version_no},
    )
    pre = result.get('pre_change_spec_version') or {}
    result.update({
        'restored': True,
        'restored_version': version_no,
        'pre_restore_diagram_version': pre.get('version_no'),
        'restored_source_hash': row.get('diagram_hash'),
    })
    return result
