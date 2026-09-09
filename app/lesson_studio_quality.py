from __future__ import annotations

import json
import logging
import os
import uuid

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _schema
from .services.lesson_diagram_integrity import diagram_manifest
from .services.lesson_integrity import review_source_hash
from .services.lesson_pdf_renderer import render_lesson_pdf
from .services.storage import delete_object, put_bytes, storage_configured

OPENAI_REVIEW_CONFIGURED = bool(os.getenv('OPENAI_API_KEY', '').strip())
REFERENCE_REVIEW_REQUIRED = os.getenv('LESSON_STUDIO_REQUIRE_REFERENCE_REVIEW', 'false').strip().lower() in {'1','true','yes','on'}
logger = logging.getLogger(__name__)


def _quality_schema() -> None:
    """Ensure the base Lesson Studio schema is available; release columns migrate at startup."""
    _schema()


def _second_review_check(row: dict, structured: dict) -> dict:
    """Evaluate the optional independent second review against current content."""
    if not OPENAI_REVIEW_CONFIGURED:
        return {'id': 'independent_second_review', 'ok': True, 'value': 'optional_not_configured'}
    review = row.get('second_review') or {}
    transcript = row.get('raw_transcript') or ''
    current_hash = review_source_hash(transcript, structured)
    stored_hash = row.get('second_review_source_hash') or ''
    findings = review.get('findings') if isinstance(review, dict) else []
    if not isinstance(findings, list):
        findings = []
    blocking = [x for x in findings if x.get('severity') in {'critical', 'review'}]
    verdict = review.get('verdict') if isinstance(review, dict) else None
    fresh = bool(stored_hash) and stored_hash == current_hash
    ok = bool(review) and fresh and verdict == 'clear' and not blocking
    return {
        'id': 'independent_second_review',
        'ok': ok,
        'value': {
            'configured': True,
            'present': bool(review),
            'fresh_for_current_content': fresh,
            'verdict': verdict,
            'blocking_findings': len(blocking),
            'provider': row.get('second_review_provider'),
        },
    }


def _reference_review_check(row: dict, structured: dict) -> dict:
    """Evaluate source-reference alignment without treating references as authoring input."""
    review = row.get('reference_review') or {}
    transcript = row.get('raw_transcript') or ''
    current_hash = review_source_hash(transcript, structured)
    stored_hash = row.get('reference_review_hash') or ''
    fresh = bool(review and stored_hash and stored_hash == current_hash)
    findings = review.get('findings') if isinstance(review, dict) else []
    if not isinstance(findings, list):
        findings = []
    blocking = [x for x in findings if x.get('severity') in {'critical', 'review'}]
    verdict = review.get('verdict') if isinstance(review, dict) else None
    clear = fresh and verdict == 'aligned' and not blocking
    if not REFERENCE_REVIEW_REQUIRED:
        return {
            'id': 'scientific_reference_alignment',
            'ok': True,
            'value': {
                'required': False,
                'present': bool(review),
                'fresh_for_current_content': fresh,
                'verdict': verdict,
                'blocking_findings': len(blocking),
            },
        }
    return {
        'id': 'scientific_reference_alignment',
        'ok': clear,
        'value': {
            'required': True,
            'present': bool(review),
            'fresh_for_current_content': fresh,
            'verdict': verdict,
            'blocking_findings': len(blocking),
        },
    }


def _canonical_source_transcript(sources: list[dict]) -> str | None:
    """Reconstruct the transcript from locked source rows when full source fields are available."""
    if not sources or any('position' not in s or 'filename' not in s or 'extracted_text' not in s for s in sources):
        return None
    return '\n\n'.join(
        f"[مصدر {s['position']}: {s['filename']}]\n{s.get('extracted_text') or ''}" for s in sources
    )


def _build_quality_snapshot(job_id: str, row: dict, sources: list[dict]) -> dict:
    """Evaluate every release gate from one coherent job/source state without I/O."""
    row = dict(row)
    sources = [dict(x) for x in sources]
    structured = dict(row.get('structured_json') or {})
    source_pending = sum(1 for s in sources if s.get('requires_review'))
    source_transcript = _canonical_source_transcript(sources)
    source_transcript_bound = source_transcript is None or source_transcript == str(row.get('raw_transcript') or '')
    uncertain = list(structured.get('uncertain_items') or [])
    diagrams = list(structured.get('diagram_specs') or [])
    manifest = diagram_manifest(structured)
    manifest_by_index = {x['index']: x for x in manifest['items']}
    diagram_pending = 0
    diagram_binding_pending = 0
    visual_provenance_pending = 0
    for index, d in enumerate(diagrams):
        engine = d.get('diagram_engine') or {}
        provenance = d.get('visual_provenance') or {}
        if not engine.get('svg') or engine.get('review_required'):
            diagram_pending += 1
        binding = manifest_by_index.get(index) or {}
        if binding.get('version_bound') and not binding.get('approval_fresh'):
            diagram_binding_pending += 1
        if engine.get('svg') and not provenance.get('origin'):
            visual_provenance_pending += 1
    notation_pending = int((structured.get('notation_quality') or {}).get('review_required') or 0)
    sections = list(structured.get('sections') or [])
    sections_without_source_refs = sum(1 for s in sections if not (s.get('source_refs') or []))
    current_content_hash = review_source_hash(str(row.get('raw_transcript') or ''), structured)
    teacher_approval_recorded = bool(row.get('teacher_approved'))
    teacher_approval_fresh = bool(
        teacher_approval_recorded
        and row.get('teacher_approval_source_hash') == current_content_hash
        and row.get('teacher_approval_diagram_hash') == manifest['hash']
    )
    checks = [
        {'id': 'source_preserved', 'ok': int(row.get('source_count') or 0) == len(sources) and len(sources) > 0, 'value': len(sources)},
        {'id': 'source_transcript_binding', 'ok': source_transcript_bound, 'value': source_transcript_bound},
        {'id': 'ocr_review_clear', 'ok': source_pending == 0, 'value': source_pending},
        {'id': 'structured_content_ready', 'ok': bool(structured), 'value': bool(structured)},
        {'id': 'uncertainty_clear', 'ok': len(uncertain) == 0, 'value': len(uncertain)},
        {'id': 'notation_review_clear', 'ok': notation_pending == 0, 'value': notation_pending},
        {'id': 'diagram_review_clear', 'ok': diagram_pending == 0, 'value': diagram_pending},
        {'id': 'diagram_version_binding', 'ok': diagram_binding_pending == 0, 'value': diagram_binding_pending},
        {'id': 'visual_provenance_clear', 'ok': visual_provenance_pending == 0, 'value': visual_provenance_pending},
        {'id': 'section_provenance', 'ok': sections_without_source_refs == 0 if sections else True, 'value': sections_without_source_refs},
        _reference_review_check(row, structured),
        _second_review_check(row, structured),
    ]
    preapproval_ready = all(x['ok'] for x in checks)
    return {
        'job_id': job_id,
        'checks': checks,
        'preapproval_ready': preapproval_ready,
        'teacher_approved': teacher_approval_recorded,
        'teacher_approval_fresh': teacher_approval_fresh,
        'teacher_approval_binding': {
            'current_content_hash': current_content_hash,
            'approved_content_hash': row.get('teacher_approval_source_hash'),
            'current_diagram_manifest_hash': manifest['hash'],
            'approved_diagram_manifest_hash': row.get('teacher_approval_diagram_hash'),
        },
        'diagram_manifest': manifest,
        'final_ready': preapproval_ready and teacher_approval_fresh,
        'policy': {
            'no_silent_scientific_correction': True,
            'teacher_is_final_gate': True,
            'teacher_approval_bound_to_content_and_diagram_manifest': True,
            'precise_diagrams_require_deterministic_or_reviewed_output': True,
            'versioned_diagrams_require_current_spec_hash_approval': True,
            'visual_assets_require_provenance': True,
            'ambiguous_scientific_notation_requires_review': True,
            'fresh_independent_review_required_when_provider_configured': True,
            'scientific_reference_is_validation_context_not_authoring_source': True,
            'scientific_reference_review_required': REFERENCE_REVIEW_REQUIRED,
            'approval_and_export_recheck_locked_state': True,
            'quality_cache_written_from_locked_state': True,
            'raw_transcript_must_match_locked_source_rows': True,
        },
    }


def _locked_job_state(con, job_id: str) -> tuple[dict, list[dict]]:
    """Lock the lesson and its OCR-source review rows before a final gate mutation."""
    row = con.execute(
        'SELECT * FROM science_lesson_jobs WHERE id=%s FOR UPDATE',
        (job_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson studio job not found')
    sources = list(con.execute('''SELECT id,position,filename,extracted_text,requires_review
      FROM science_lesson_sources WHERE job_id=%s ORDER BY position FOR UPDATE''',
      (job_id,)).fetchall())
    return dict(row), [dict(x) for x in sources]


def _snapshot_contract(snapshot: dict) -> tuple[str, str]:
    """Return the immutable content and diagram identities verified by a snapshot."""
    binding = snapshot.get('teacher_approval_binding') or {}
    return (
        str(binding.get('current_content_hash') or ''),
        str((snapshot.get('diagram_manifest') or {}).get('hash') or ''),
    )


def _require_snapshot_state(snapshot: dict, *, final: bool) -> None:
    """Raise a stable quality-gate response for approval or final export."""
    ready_key = 'final_ready' if final else 'preapproval_ready'
    if snapshot.get(ready_key):
        return
    failed = [x for x in snapshot.get('checks') or [] if not x.get('ok')]
    if final and not snapshot.get('teacher_approval_fresh'):
        failed.append({
            'id': 'teacher_approval_fresh',
            'ok': False,
            'value': snapshot.get('teacher_approval_binding'),
        })
    message = 'Final PDF export blocked by quality gate' if final else 'Lesson failed quality gate'
    raise HTTPException(409, {'message': message, 'failed': failed})


def _final_pdf_object_key(job_id: str, content_hash: str, diagram_hash: str) -> str:
    """Return a unique immutable object key bound to the verified lesson contract."""
    export_id = uuid.uuid4().hex
    return (
        f'lesson-studio/{job_id}/final-approved-'
        f'{content_hash[:16]}-{diagram_hash[:16]}-{export_id}.pdf'
    )


def _delete_unpromoted_pdf(job_id: str, key: str) -> None:
    """Delete a failed export only while a locked row proves the object is not currently promoted."""
    try:
        with connect() as con:
            row = con.execute(
                'SELECT pdf_object_key FROM science_lesson_jobs WHERE id=%s FOR UPDATE',
                (job_id,),
            ).fetchone()
            if row and row.get('pdf_object_key') == key:
                return
            delete_object(key)
    except Exception:
        # An orphan is safer than deleting an object whose live reference could
        # not be verified because the database or storage cleanup failed.
        logger.exception('Failed to safely delete unpromoted lesson PDF object %s', key)


def quality_snapshot(job_id: str) -> dict:
    """Recompute and cache quality state while holding the same locked database state."""
    _quality_schema()
    with connect() as con:
        row, sources = _locked_job_state(con, job_id)
        snapshot = _build_quality_snapshot(job_id, row, sources)
        con.execute('UPDATE science_lesson_jobs SET quality_snapshot=%s::jsonb WHERE id=%s',
                    (json.dumps(snapshot, ensure_ascii=False), job_id))
    return snapshot


@app.get('/api/admin/lesson-studio/jobs/{job_id}/quality', dependencies=[Depends(require_admin)])
def lesson_quality(job_id: str):
    """Expose the current locked quality snapshot to an authenticated administrator."""
    return quality_snapshot(job_id)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/approve-content', dependencies=[Depends(require_admin)])
def approve_lesson_content(job_id: str):
    """Approve only the exact content and diagram contract that passes all locked gates."""
    _quality_schema()
    with connect() as con:
        row, sources = _locked_job_state(con, job_id)
        snapshot = _build_quality_snapshot(job_id, row, sources)
        _require_snapshot_state(snapshot, final=False)
        content_hash, diagram_hash = _snapshot_contract(snapshot)
        approved_snapshot = dict(snapshot)
        approved_binding = dict(snapshot.get('teacher_approval_binding') or {})
        approved_binding['approved_content_hash'] = content_hash
        approved_binding['approved_diagram_manifest_hash'] = diagram_hash
        approved_snapshot.update({
            'teacher_approved': True,
            'teacher_approval_fresh': True,
            'teacher_approval_binding': approved_binding,
            'final_ready': True,
        })
        con.execute('''UPDATE science_lesson_jobs SET
          teacher_approved=TRUE,teacher_approved_at=now(),
          teacher_approval_source_hash=%s,teacher_approval_diagram_hash=%s,
          quality_snapshot=%s::jsonb,
          status='approved_for_export',updated_at=now() WHERE id=%s''',
          (content_hash, diagram_hash, json.dumps(approved_snapshot, ensure_ascii=False), job_id))
    return {
        'approved': True,
        'job_id': job_id,
        'final_ready': True,
        'content_hash': content_hash,
        'diagram_manifest_hash': diagram_hash,
        'atomic_gate': True,
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/revoke-content-approval', dependencies=[Depends(require_admin)])
def revoke_lesson_content_approval(job_id: str):
    """Revoke teacher approval and invalidate every PDF binding derived from it."""
    _quality_schema()
    with connect() as con:
        if not con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone():
            raise HTTPException(404, 'Lesson studio job not found')
        con.execute('''UPDATE science_lesson_jobs SET
          teacher_approved=FALSE,teacher_approved_at=NULL,
          teacher_approval_source_hash=NULL,teacher_approval_diagram_hash=NULL,
          quality_snapshot=NULL,
          pdf_object_key=NULL,pdf_source_hash=NULL,pdf_diagram_manifest_hash=NULL,
          status='content_review_required',updated_at=now() WHERE id=%s''', (job_id,))
    return {'revoked': True, 'job_id': job_id, 'previous_pdf_invalidated': True}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/final-pdf', dependencies=[Depends(require_admin)])
def export_final_lesson_pdf(job_id: str):
    """Render and promote a PDF only if its approved contract survives a post-render recheck."""
    _quality_schema()

    # Capture one fully locked and verified state for rendering. Nothing is
    # rendered from a snapshot whose source reviews or job content can change
    # underneath the gate calculation.
    with connect() as con:
        row, sources = _locked_job_state(con, job_id)
        snapshot = _build_quality_snapshot(job_id, row, sources)
        _require_snapshot_state(snapshot, final=True)
        verified_content_hash, verified_diagram_hash = _snapshot_contract(snapshot)
        structured = dict(row.get('structured_json') or {})
        con.execute('UPDATE science_lesson_jobs SET quality_snapshot=%s::jsonb WHERE id=%s',
                    (json.dumps(snapshot, ensure_ascii=False), job_id))

    data = render_lesson_pdf(structured)
    key = _final_pdf_object_key(job_id, verified_content_hash, verified_diagram_hash)
    persist_to_storage = storage_configured()
    uploaded = False
    if persist_to_storage:
        put_bytes(key, data, 'application/pdf')
        uploaded = True

    # Re-lock and re-evaluate after rendering/upload. Only the exact state
    # verified above can become the current final PDF.
    try:
        with connect() as con:
            current_row, current_sources = _locked_job_state(con, job_id)
            current_snapshot = _build_quality_snapshot(job_id, current_row, current_sources)
            _require_snapshot_state(current_snapshot, final=True)
            current_content_hash, current_diagram_hash = _snapshot_contract(current_snapshot)
            if (
                current_content_hash != verified_content_hash
                or current_diagram_hash != verified_diagram_hash
            ):
                raise HTTPException(409, {
                    'message': 'Lesson changed during PDF export; generated file was not promoted',
                    'verified_content_hash': verified_content_hash,
                    'current_content_hash': current_content_hash,
                    'verified_diagram_manifest_hash': verified_diagram_hash,
                    'current_diagram_manifest_hash': current_diagram_hash,
                })
            if persist_to_storage:
                con.execute('''UPDATE science_lesson_jobs SET
                  pdf_object_key=%s,pdf_source_hash=%s,pdf_diagram_manifest_hash=%s,
                  quality_snapshot=%s::jsonb,
                  status='final_pdf_ready',updated_at=now() WHERE id=%s''',
                  (
                      key,
                      verified_content_hash,
                      verified_diagram_hash,
                      json.dumps(current_snapshot, ensure_ascii=False),
                      job_id,
                  ))
    except Exception:
        if uploaded:
            _delete_unpromoted_pdf(job_id, key)
        raise

    return Response(
        data,
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename="science-lesson-{job_id}.pdf"',
            'X-Lesson-Content-Hash': verified_content_hash,
            'X-Lesson-Diagram-Manifest-Hash': verified_diagram_hash,
        },
    )