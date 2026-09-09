from __future__ import annotations

import hashlib
import hmac
import json
import re

from fastapi import Header, HTTPException

from .lesson_integrity import review_source_hash


_SHA256_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def _normalize_expected_hash(expected: str | None, *, action: str, missing_status: int = 409) -> str:
    """Validate and normalize one client-supplied SHA-256 revision before constant-time comparison."""
    value = str(expected or '').strip()
    if not value:
        raise HTTPException(missing_status, {
            'message': 'A current 64-character SHA-256 revision is required',
            'action': action,
        })
    if not _SHA256_RE.fullmatch(value):
        raise HTTPException(409, {
            'message': 'The supplied revision hash is malformed; reload the current editor state',
            'action': action,
        })
    return value.lower()


def lesson_content_precondition(
    x_lesson_content_hash: str | None = Header(default=None, alias='X-Lesson-Content-Hash'),
) -> str:
    """Require a valid SHA-256 lesson hash that was visible when a teacher initiated a mutation."""
    return _normalize_expected_hash(
        x_lesson_content_hash,
        action='reload_workspace',
        missing_status=428,
    )


def content_hash_from_row(row) -> str:
    """Hash the canonical transcript and structured lesson represented by a database row."""
    return review_source_hash(
        str(row.get('raw_transcript') or ''),
        dict(row.get('structured_json') or {}),
    )


def assert_expected_content_hash(row, expected: str) -> str:
    """Reject a mutation when the locked lesson differs from the teacher-visible version."""
    current = content_hash_from_row(row)
    normalized = _normalize_expected_hash(expected, action='reload_workspace', missing_status=428)
    if not hmac.compare_digest(current, normalized):
        raise HTTPException(409, {
            'message': 'Lesson changed since this workspace was loaded; reload before saving',
            'expected_content_hash': normalized,
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
    """Hash the teacher-visible OCR review state so a stale source action cannot overwrite a newer one."""
    payload = json.dumps(
        {
            'id': int(row['id']),
            'extracted_text': str(row.get('extracted_text') or ''),
            'alternate_ocr_text': str(row.get('alternate_ocr_text') or ''),
            'confidence': row.get('confidence'),
            'ocr_confidence_band': str(row.get('ocr_confidence_band') or ''),
            'ocr_conflicts': row.get('ocr_conflicts') or [],
            'requires_review': bool(row.get('requires_review')),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def assert_expected_source_hash(row, expected: str) -> str:
    """Reject a stale or malformed OCR revision before comparing it with the current source state."""
    current = source_review_hash(row)
    normalized = _normalize_expected_hash(expected, action='reload_workspace')
    if not hmac.compare_digest(current, normalized):
        raise HTTPException(409, {
            'message': 'Lesson source changed since it was loaded; reload before changing OCR review state',
            'expected_source_hash': normalized,
            'current_source_hash': current,
            'action': 'reload_workspace',
        })
    return current


def source_editor_hash(row) -> str:
    """Hash OCR review state plus the current adjusted-image derivative used by source-editor mutations."""
    payload = json.dumps(
        {
            'source_review_hash': source_review_hash(row),
            'adjusted_object_key': str(row.get('adjusted_object_key') or ''),
            'adjustment_meta': row.get('adjustment_meta') or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def assert_expected_source_editor_hash(row, expected: str) -> str:
    """Reject a stale or malformed image/OCR editor revision before a source mutation is committed."""
    current = source_editor_hash(row)
    normalized = _normalize_expected_hash(expected, action='reload_source_editor')
    if not hmac.compare_digest(current, normalized):
        raise HTTPException(409, {
            'message': 'Lesson source editor state changed since it was loaded; reload before saving',
            'expected_source_editor_hash': normalized,
            'current_source_editor_hash': current,
            'action': 'reload_source_editor',
        })
    return current
