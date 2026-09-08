from __future__ import annotations

import json

from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from .lesson_studio_quality import quality_snapshot, _quality_schema
from .science_lesson_studio import _job
from .services.lesson_diagram_integrity import diagram_manifest
from .services.lesson_integrity import review_source_hash


GATE_ORDER = (
    'ocr_review',
    'notation_review',
    'diagram_review',
    'scientific_reference_review',
    'independent_second_review',
    'teacher_approval',
    'final_pdf_export',
)


def _state_schema() -> None:
    _quality_schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS pdf_source_hash text')
        con.execute('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS pdf_diagram_manifest_hash text')
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_gate_state(
          job_id uuid NOT NULL REFERENCES science_lesson_jobs(id) ON DELETE CASCADE,
          content_hash text NOT NULL,
          gate text NOT NULL,
          state text NOT NULL,
          details jsonb NOT NULL DEFAULT '{}'::jsonb,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(job_id,content_hash,gate)
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_science_lesson_gate_state_job ON science_lesson_gate_state(job_id,updated_at DESC)')


def _check_map(snapshot: dict) -> dict[str, dict]:
    return {str(x.get('id')): x for x in snapshot.get('checks') or []}


def approval_state_from_snapshot(
    snapshot: dict,
    *,
    pdf_object_key: str | None,
    pdf_source_hash: str | None,
    current_hash: str,
    pdf_diagram_manifest_hash: str | None = None,
    current_diagram_manifest_hash: str | None = None,
) -> dict:
    checks = _check_map(snapshot)
    gates: list[dict] = []

    def add(gate: str, state: str, detail) -> None:
        gates.append({'gate': gate, 'state': state, 'details': detail})

    ocr = checks.get('ocr_review_clear') or {}
    add('ocr_review', 'complete' if ocr.get('ok') else 'blocked', {'pending': ocr.get('value')})

    notation = checks.get('notation_review_clear') or {}
    add('notation_review', 'complete' if notation.get('ok') else 'blocked', {'pending': notation.get('value')})

    diagram = checks.get('diagram_review_clear') or {}
    binding = checks.get('diagram_version_binding') or {'ok': True, 'value': 0}
    diagram_ok = bool(diagram.get('ok')) and bool(binding.get('ok'))
    add('diagram_review', 'complete' if diagram_ok else 'blocked', {
        'pending': diagram.get('value'),
        'stale_version_bindings': binding.get('value'),
    })

    reference = checks.get('scientific_reference_alignment') or {}
    ref_value = reference.get('value')
    if isinstance(ref_value, dict) and not ref_value.get('required', False):
        if ref_value.get('present') and ref_value.get('fresh_for_current_content') and ref_value.get('verdict') == 'aligned':
            add('scientific_reference_review', 'complete', ref_value)
        else:
            add('scientific_reference_review', 'not_required', ref_value)
    else:
        add('scientific_reference_review', 'complete' if reference.get('ok') else 'blocked', ref_value)

    second = checks.get('independent_second_review') or {}
    second_value = second.get('value')
    if second_value == 'optional_not_configured':
        add('independent_second_review', 'not_required', {'configured': False})
    else:
        add('independent_second_review', 'complete' if second.get('ok') else 'blocked', second_value)

    teacher_recorded = bool(snapshot.get('teacher_approved'))
    teacher_fresh = bool(snapshot.get('teacher_approval_fresh', teacher_recorded))
    if teacher_recorded and teacher_fresh:
        add('teacher_approval', 'complete', {
            'approved': True,
            'fresh_for_current_content_and_diagrams': True,
        })
    elif snapshot.get('preapproval_ready'):
        add('teacher_approval', 'pending', {
            'approved': teacher_recorded,
            'fresh_for_current_content_and_diagrams': teacher_fresh,
            'can_approve_now': True,
        })
    else:
        add('teacher_approval', 'blocked', {
            'approved': teacher_recorded,
            'fresh_for_current_content_and_diagrams': teacher_fresh,
            'can_approve_now': False,
        })

    content_fresh = bool(pdf_object_key and pdf_source_hash and pdf_source_hash == current_hash)
    diagram_fresh = True
    if current_diagram_manifest_hash is not None:
        diagram_fresh = bool(
            pdf_diagram_manifest_hash
            and pdf_diagram_manifest_hash == current_diagram_manifest_hash
        )
    pdf_fresh = content_fresh and diagram_fresh
    pdf_detail = {
        'object_key': pdf_object_key,
        'fresh_for_current_content': content_fresh,
        'fresh_for_current_diagram_manifest': diagram_fresh,
        'stored_diagram_manifest_hash': pdf_diagram_manifest_hash,
        'current_diagram_manifest_hash': current_diagram_manifest_hash,
    }
    if pdf_fresh:
        add('final_pdf_export', 'complete', pdf_detail)
    elif snapshot.get('final_ready'):
        add('final_pdf_export', 'pending', pdf_detail)
    else:
        add('final_pdf_export', 'blocked', pdf_detail)

    complete = sum(1 for x in gates if x['state'] == 'complete')
    actionable = [x['gate'] for x in gates if x['state'] == 'pending']
    blocked = [x['gate'] for x in gates if x['state'] == 'blocked']
    return {
        'content_hash': current_hash,
        'diagram_manifest_hash': current_diagram_manifest_hash,
        'gates': gates,
        'summary': {
            'complete': complete,
            'not_required': sum(1 for x in gates if x['state'] == 'not_required'),
            'pending': len(actionable),
            'blocked': len(blocked),
            'all_required_complete': all(x['state'] in {'complete','not_required'} for x in gates),
        },
        'next_actions': actionable,
        'blocked_gates': blocked,
        'policy': {
            'state_bound_to_content_hash': True,
            'state_bound_to_diagram_manifest_hash': True,
            'stale_teacher_approval_never_counts_as_complete': True,
            'stale_pdf_never_counts_as_complete': True,
            'source_files_untouched': True,
        },
    }


def sync_approval_state(job_id: str) -> dict:
    _state_schema()
    snapshot = quality_snapshot(job_id)
    row, _ = _job(job_id)
    row = dict(row)
    structured = dict(row.get('structured_json') or {})
    current_hash = review_source_hash(str(row.get('raw_transcript') or ''), structured)
    current_diagram_hash = diagram_manifest(structured)['hash']
    with connect() as con:
        pdf = con.execute('''SELECT pdf_object_key,pdf_source_hash,pdf_diagram_manifest_hash
          FROM science_lesson_jobs WHERE id=%s''', (job_id,)).fetchone()
    if not pdf:
        raise HTTPException(404, 'Lesson studio job not found')
    state = approval_state_from_snapshot(
        snapshot,
        pdf_object_key=pdf.get('pdf_object_key'),
        pdf_source_hash=pdf.get('pdf_source_hash'),
        current_hash=current_hash,
        pdf_diagram_manifest_hash=pdf.get('pdf_diagram_manifest_hash'),
        current_diagram_manifest_hash=current_diagram_hash,
    )
    with connect() as con:
        for gate in state['gates']:
            con.execute('''INSERT INTO science_lesson_gate_state(job_id,content_hash,gate,state,details,updated_at)
              VALUES(%s,%s,%s,%s,%s::jsonb,now())
              ON CONFLICT(job_id,content_hash,gate) DO UPDATE SET
                state=EXCLUDED.state,details=EXCLUDED.details,updated_at=now()''',
              (job_id,current_hash,gate['gate'],gate['state'],json.dumps(gate.get('details') or {}, ensure_ascii=False)))
    return {'job_id': job_id, **state}


@app.get('/api/admin/lesson-studio/jobs/{job_id}/approval-state', dependencies=[Depends(require_admin)])
def lesson_approval_state(job_id: str):
    return sync_approval_state(job_id)
