from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import Depends, Form, HTTPException

from .db import connect
from .main import app
from .security import require_admin


def _history_schema() -> None:
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_versions(
          id uuid PRIMARY KEY,
          job_id uuid NOT NULL REFERENCES science_lesson_jobs(id) ON DELETE CASCADE,
          version_no integer NOT NULL,
          action text NOT NULL,
          note text,
          content_hash text NOT NULL,
          raw_transcript text,
          structured_json jsonb,
          job_status text,
          teacher_approved boolean NOT NULL DEFAULT false,
          metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(job_id,version_no)
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_science_lesson_versions_job ON science_lesson_versions(job_id,version_no DESC)')


def _content_hash(raw_transcript: str, structured: dict) -> str:
    payload = json.dumps(
        {'raw_transcript': raw_transcript or '', 'structured_json': structured or {}},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def snapshot_job(job_id: str, action: str, note: str = '', metadata: dict | None = None) -> dict:
    """Store an immutable pre-change snapshot. Duplicate current hashes are still allowed for distinct audit actions."""
    _history_schema()
    with connect() as con:
        row = con.execute('''SELECT id,raw_transcript,structured_json,status,teacher_approved,
          teacher_approved_at,second_review,second_review_provider,second_review_at,
          reference_review,reference_review_hash,reference_review_at,pdf_object_key
          FROM science_lesson_jobs WHERE id=%s''', (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson studio job not found')
        next_no = int(con.execute(
            'SELECT COALESCE(max(version_no),0)+1 n FROM science_lesson_versions WHERE job_id=%s',
            (job_id,)
        ).fetchone()['n'])
        structured = dict(row.get('structured_json') or {})
        transcript = str(row.get('raw_transcript') or '')
        digest = _content_hash(transcript, structured)
        version_id = str(uuid.uuid4())
        meta = {
            'teacher_approved_at': str(row.get('teacher_approved_at') or ''),
            'second_review_present': bool(row.get('second_review')),
            'second_review_provider': row.get('second_review_provider'),
            'second_review_at': str(row.get('second_review_at') or ''),
            'reference_review_present': bool(row.get('reference_review')),
            'reference_review_hash': row.get('reference_review_hash'),
            'reference_review_at': str(row.get('reference_review_at') or ''),
            'pdf_object_key': row.get('pdf_object_key'),
            **(metadata or {}),
        }
        con.execute('''INSERT INTO science_lesson_versions(
          id,job_id,version_no,action,note,content_hash,raw_transcript,structured_json,
          job_status,teacher_approved,metadata)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)''',
          (version_id, job_id, next_no, action[:120], note[:1000], digest, transcript,
           json.dumps(structured, ensure_ascii=False), row.get('status'),
           bool(row.get('teacher_approved')), json.dumps(meta, ensure_ascii=False)))
    return {'id': version_id, 'job_id': job_id, 'version_no': next_no, 'content_hash': digest, 'action': action}


def ensure_initial_snapshot(job_id: str) -> None:
    _history_schema()
    with connect() as con:
        exists = con.execute('SELECT 1 FROM science_lesson_versions WHERE job_id=%s LIMIT 1', (job_id,)).fetchone()
    if not exists:
        snapshot_job(job_id, 'initial_snapshot', 'Automatic baseline before version tracking')


@app.get('/api/admin/lesson-studio/jobs/{job_id}/versions', dependencies=[Depends(require_admin)])
def list_lesson_versions(job_id: str):
    ensure_initial_snapshot(job_id)
    with connect() as con:
        rows = list(con.execute('''SELECT id,version_no,action,note,content_hash,job_status,
          teacher_approved,metadata,created_at
          FROM science_lesson_versions WHERE job_id=%s ORDER BY version_no DESC''', (job_id,)).fetchall())
        current = con.execute('SELECT raw_transcript,structured_json,status,teacher_approved,updated_at FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
    if not current:
        raise HTTPException(404, 'Lesson studio job not found')
    current_hash = _content_hash(str(current.get('raw_transcript') or ''), dict(current.get('structured_json') or {}))
    return {
        'job_id': job_id,
        'current': {
            'content_hash': current_hash,
            'status': current.get('status'),
            'teacher_approved': bool(current.get('teacher_approved')),
            'updated_at': current.get('updated_at'),
        },
        'versions': [dict(x) for x in rows],
        'policy': {
            'immutable_snapshots': True,
            'restore_invalidates_approval': True,
            'restore_invalidates_external_reviews': True,
            'original_sources_untouched': True,
        },
    }


@app.get('/api/admin/lesson-studio/jobs/{job_id}/versions/{version_no}', dependencies=[Depends(require_admin)])
def get_lesson_version(job_id: str, version_no: int):
    _history_schema()
    with connect() as con:
        row = con.execute('''SELECT id,version_no,action,note,content_hash,raw_transcript,
          structured_json,job_status,teacher_approved,metadata,created_at
          FROM science_lesson_versions WHERE job_id=%s AND version_no=%s''', (job_id, version_no)).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson version not found')
    return {'job_id': job_id, 'version': dict(row)}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/versions/{version_no}/restore', dependencies=[Depends(require_admin)])
def restore_lesson_version(job_id: str, version_no: int, teacher_note: str = Form('')):
    _history_schema()
    with connect() as con:
        version = con.execute('''SELECT raw_transcript,structured_json,content_hash FROM science_lesson_versions
          WHERE job_id=%s AND version_no=%s''', (job_id, version_no)).fetchone()
        current = con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
    if not current:
        raise HTTPException(404, 'Lesson studio job not found')
    if not version:
        raise HTTPException(404, 'Lesson version not found')

    pre_restore = snapshot_job(
        job_id, 'pre_restore_snapshot',
        f'Automatic snapshot before restoring version {version_no}',
        {'restore_target_version': version_no},
    )

    with connect() as con:
        con.execute('''UPDATE science_lesson_jobs SET
          raw_transcript=%s,
          structured_json=%s::jsonb,
          teacher_approved=FALSE,teacher_approved_at=NULL,
          second_review=NULL,second_review_provider=NULL,second_review_at=NULL,
          reference_review=NULL,reference_review_hash=NULL,reference_review_at=NULL,
          quality_snapshot=NULL,pdf_object_key=NULL,
          status='content_review_required',updated_at=now()
          WHERE id=%s''',
          (version.get('raw_transcript') or '', json.dumps(version.get('structured_json') or {}, ensure_ascii=False), job_id))
    restored_hash = _content_hash(str(version.get('raw_transcript') or ''), dict(version.get('structured_json') or {}))
    return {
        'restored': True,
        'job_id': job_id,
        'restored_version': version_no,
        'restored_content_hash': restored_hash,
        'pre_restore_version': pre_restore['version_no'],
        'teacher_note': teacher_note.strip(),
        'approval_invalidated': True,
        'second_review_invalidated': True,
        'reference_review_invalidated': True,
        'previous_pdf_invalidated': True,
        'sources_untouched': True,
    }
