from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import Header, HTTPException

from .lesson_integrity import review_source_hash


def lesson_content_precondition(
    x_lesson_content_hash: str | None = Header(default=None, alias='X-Lesson-Content-Hash'),
) -> str:
    """Require the exact lesson content hash that was visible when a teacher initiated a mutation."""
    expected = str(x_lesson_content_hash or '').strip()
    if not expected:
        raise HTTPException(428, {
            'message': 'Lesson mutation requires the content hash currently displayed to the teacher',
            'action': 'reload_workspace',
        })
    return expected


def content_hash_from_row(row) -> str:
    """Hash the canonical transcript and structured lesson represented by a database row."""
    return review_source_hash(
        str(row.get('raw_transcript') or ''),
        dict(row.get('structured_json') or {}),
    )


def assert_expected_content_hash(row, expected: str) -> str:
    """Reject a mutation when the locked lesson differs from the teacher-visible version."""
    current = content_hash_from_row(row)
    if not hmac.compare_digest(current, str(expected or '')):
        raise HTTPException(409, {
            'message': 'Lesson changed since this workspace was loaded; reload before saving',
            'expected_content_hash': str(expected or ''),
            'current_content_hash': current,
            'action': 'reload_workspace',
        })
    return current


def lock_job_for_mutation(con, job_id: str, expected: str) -> tuple[dict, str]:
    """Lock one lesson row and atomically validate its optimistic-concurrency precondition."""
    row = con.execute(
        'SELECT * FROM science_lesson_jobs WHERE id=%s FOR UPDATE',
        (job_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson studio job not found')
    item = dict(row)
    return item, assert_expected_content_hash(item, expected)


def source_review_hash(row) -> str:
    """Hash the teacher-visible OCR source state so stale text approval cannot overwrite a newer source."""
    payload = json.dumps(
        {
            'id': int(row['id']),
            'extracted_text': str(row.get('extracted_text') or ''),
            'requires_review': bool(row.get('requires_review')),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def assert_expected_source_hash(row, expected: str) -> str:
    """Reject stale OCR approval when the source row changed after the teacher loaded it."""
    current = source_review_hash(row)
    if not expected or not hmac.compare_digest(current, str(expected)):
        raise HTTPException(409, {
            'message': 'Lesson source changed since it was loaded; reload before approving OCR text',
            'expected_source_hash': str(expected or ''),
            'current_source_hash': current,
            'action': 'reload_workspace',
        })
    return current
