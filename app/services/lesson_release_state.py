from __future__ import annotations

from ..db import connect


_RELEASE_COLUMNS = (
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved boolean NOT NULL DEFAULT false',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved_at timestamptz',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approval_source_hash text',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approval_diagram_hash text',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS quality_snapshot jsonb',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review jsonb',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review_provider text',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review_at timestamptz',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS second_review_source_hash text',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS reference_review jsonb',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS reference_review_hash text',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS reference_review_at timestamptz',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS pdf_source_hash text',
    'ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS pdf_diagram_manifest_hash text',
)


def ensure_release_state_columns(con) -> None:
    """Apply the release-state column migration using an existing transaction."""
    for statement in _RELEASE_COLUMNS:
        con.execute(statement)


def ensure_release_state_schema() -> None:
    """Create the Lesson Studio base schema, then migrate release-state columns once at startup."""
    from ..science_lesson_studio import _schema

    _schema()
    with connect() as con:
        ensure_release_state_columns(con)


def invalidate_release_state(con, job_id: str, *, status: str) -> None:
    """Invalidate all release artifacts atomically inside the caller's content transaction."""
    con.execute(
        '''UPDATE science_lesson_jobs SET
          teacher_approved=FALSE,teacher_approved_at=NULL,
          teacher_approval_source_hash=NULL,teacher_approval_diagram_hash=NULL,
          quality_snapshot=NULL,
          second_review=NULL,second_review_provider=NULL,second_review_at=NULL,
          second_review_source_hash=NULL,
          reference_review=NULL,reference_review_hash=NULL,reference_review_at=NULL,
          pdf_object_key=NULL,pdf_source_hash=NULL,pdf_diagram_manifest_hash=NULL,
          status=%s,updated_at=now()
          WHERE id=%s''',
        (status, job_id),
    )