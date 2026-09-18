from __future__ import annotations

import json
from typing import Any

from ..db import connect

_MAX_NOTES = 500


def clean_notes(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text[:_MAX_NOTES] or None


def active_approval(job_id: str, base_hash: str, edit_digest: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            """SELECT id,job_id,base_hash,edit_digest,approval_notes,approved_by,
                      approved_at,revoked_at
               FROM lesson_presentation_approvals
               WHERE job_id=%s AND base_hash=%s AND edit_digest=%s AND revoked_at IS NULL
               ORDER BY approved_at DESC,id DESC
               LIMIT 1""",
            (job_id, base_hash, edit_digest),
        ).fetchone()
    return dict(row) if row else None


def record_approval(
    job_id: str,
    *,
    base_hash: str,
    edit_digest: str,
    blueprint: dict,
    notes: Any = None,
    approved_by: str = "admin_session",
) -> dict:
    existing = active_approval(job_id, base_hash, edit_digest)
    if existing:
        return {**existing, "created": False}
    with connect() as con:
        row = con.execute(
            """INSERT INTO lesson_presentation_approvals(
                 job_id,base_hash,edit_digest,blueprint_json,approval_notes,approved_by
               ) VALUES (%s,%s,%s,%s::jsonb,%s,%s)
               RETURNING id,job_id,base_hash,edit_digest,approval_notes,approved_by,
                         approved_at,revoked_at""",
            (
                job_id,
                base_hash,
                edit_digest,
                json.dumps(blueprint, ensure_ascii=False),
                clean_notes(notes),
                str(approved_by or "admin_session")[:120],
            ),
        ).fetchone()
    return {**dict(row), "created": True}


def list_approvals(job_id: str, limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with connect() as con:
        rows = list(
            con.execute(
                """SELECT id,job_id,base_hash,edit_digest,approval_notes,approved_by,
                          approved_at,revoked_at,revoke_reason
                   FROM lesson_presentation_approvals
                   WHERE job_id=%s
                   ORDER BY approved_at DESC,id DESC
                   LIMIT %s""",
                (job_id, limit),
            ).fetchall()
        )
    return [dict(row) for row in rows]


def revoke_approval(job_id: str, approval_id: int, reason: Any = None) -> dict | None:
    with connect() as con:
        row = con.execute(
            """UPDATE lesson_presentation_approvals
               SET revoked_at=COALESCE(revoked_at,now()),
                   revoke_reason=CASE WHEN revoked_at IS NULL THEN %s ELSE revoke_reason END
               WHERE id=%s AND job_id=%s
               RETURNING id,job_id,base_hash,edit_digest,approval_notes,approved_by,
                         approved_at,revoked_at,revoke_reason""",
            (clean_notes(reason), approval_id, job_id),
        ).fetchone()
    return dict(row) if row else None
