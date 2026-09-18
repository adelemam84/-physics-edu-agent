from __future__ import annotations

from ..db import connect


def ensure_lesson_pack_schema() -> None:
    """Create Lesson Pack tables during controlled startup/release migration."""
    with connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS lesson_pack_jobs(
              id uuid PRIMARY KEY,
              title text NOT NULL,
              subject text NOT NULL,
              grade_label text,
              pack_mode text NOT NULL,
              status text NOT NULL DEFAULT 'uploaded',
              source_file_count integer NOT NULL DEFAULT 0,
              source_page_count integer NOT NULL DEFAULT 0,
              raw_transcript text,
              pack_json jsonb,
              scientific_review_json jsonb,
              teacher_approved boolean NOT NULL DEFAULT false,
              approval_notes text,
              pdf_student_object_key text,
              pdf_teacher_object_key text,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS lesson_pack_pages(
              id bigserial PRIMARY KEY,
              job_id uuid NOT NULL REFERENCES lesson_pack_jobs(id) ON DELETE CASCADE,
              position integer NOT NULL,
              file_index integer NOT NULL,
              original_filename text NOT NULL,
              original_page integer NOT NULL,
              object_key text NOT NULL,
              extracted_text text,
              alternate_ocr_text text,
              confidence numeric,
              ocr_confidence_band text,
              ocr_conflicts jsonb,
              requires_review boolean NOT NULL DEFAULT true,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              UNIQUE(job_id,position)
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lesson_pack_jobs_created ON lesson_pack_jobs(created_at DESC)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lesson_pack_pages_job ON lesson_pack_pages(job_id,position)"
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS lesson_pack_page_enhancements(
              page_id bigint PRIMARY KEY REFERENCES lesson_pack_pages(id) ON DELETE CASCADE,
              job_id uuid NOT NULL REFERENCES lesson_pack_jobs(id) ON DELETE CASCADE,
              original_object_key text NOT NULL,
              visual_object_key text,
              ocr_object_key text,
              diff_object_key text,
              profile text NOT NULL DEFAULT 'balanced',
              params_json jsonb NOT NULL DEFAULT '{}'::jsonb,
              metrics_before_json jsonb NOT NULL DEFAULT '{}'::jsonb,
              metrics_after_json jsonb NOT NULL DEFAULT '{}'::jsonb,
              fidelity_json jsonb NOT NULL DEFAULT '{}'::jsonb,
              ocr_comparison_json jsonb,
              teacher_approved boolean NOT NULL DEFAULT false,
              approval_notes text,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lesson_pack_page_enhancements_job ON lesson_pack_page_enhancements(job_id,page_id)"
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS lesson_presentation_drafts(
              job_id uuid PRIMARY KEY REFERENCES lesson_pack_jobs(id) ON DELETE CASCADE,
              base_hash text NOT NULL,
              edit_digest text NOT NULL,
              blueprint_json jsonb NOT NULL,
              current_slide integer NOT NULL DEFAULT 0,
              updated_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS lesson_presentation_revisions(
              id bigserial PRIMARY KEY,
              job_id uuid NOT NULL REFERENCES lesson_pack_jobs(id) ON DELETE CASCADE,
              base_hash text NOT NULL,
              edit_digest text NOT NULL,
              blueprint_json jsonb NOT NULL,
              current_slide integer NOT NULL DEFAULT 0,
              action text NOT NULL DEFAULT 'checkpoint',
              label text,
              created_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lesson_presentation_revisions_job ON lesson_presentation_revisions(job_id,created_at DESC,id DESC)"
        )
