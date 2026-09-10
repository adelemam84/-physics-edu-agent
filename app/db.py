from __future__ import annotations
import os
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
STORAGE_BACKEND = "neon_postgresql" if DATABASE_URL else "not_configured"

@contextmanager
def connect():
    """Open one transactional PostgreSQL connection and commit or roll back atomically."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    import psycopg
    from psycopg.rows import dict_row
    con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db():
    """Apply idempotent platform startup migrations, including Lesson Studio release-state schema."""
    defaults = [("system_name","منصة العلوم التعليمية"),("content_policy","pdf_only"),("allow_generated_questions","false"),("require_question_approval","true")]
    with connect() as con:
        for key,value in defaults:
            con.execute("INSERT INTO settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING",(key,value))
        # Do not seed subject-specific lessons. Academic structure is created explicitly
        # from the selected subject/grade/curriculum/term to avoid cross-subject pollution.
        # Non-destructive notification delivery tracking migration.
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS delivery_status text")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS delivered_at timestamptz")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS read_at timestamptz")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS provider_status_at timestamptz")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS provider_error_code text")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS provider_error_title text")
        con.execute("CREATE INDEX IF NOT EXISTS idx_parent_notifications_provider_message_id ON parent_notifications(provider_message_id)")
        # Scaling indexes for frequent quiz/report queries and DB-level duplicate-answer protection.
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_answers_attempt_question ON attempt_answers(attempt_id,question_id) WHERE attempt_id IS NOT NULL AND question_id IS NOT NULL")
        con.execute("CREATE INDEX IF NOT EXISTS idx_attempt_answers_attempt_correct ON attempt_answers(attempt_id,is_correct)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_attempt_answers_question ON attempt_answers(question_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_attempts_student_submitted ON attempts(student_id,submitted_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_attempts_student_quiz_submitted ON attempts(student_id,quiz_id,submitted_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_guardians_student_active_optin ON guardians(student_id,active,whatsapp_opt_in)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_quiz_questions_quiz_position ON quiz_questions(quiz_id,position)")
        con.execute("""CREATE TABLE IF NOT EXISTS question_review_notes(
          question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
          reason_code text NOT NULL,
          severity text NOT NULL DEFAULT 'review',
          details text,
          source_verified boolean NOT NULL DEFAULT false,
          status text NOT NULL DEFAULT 'open',
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS document_page_reviews(
          document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          page_number integer NOT NULL,
          page_role text NOT NULL DEFAULT 'unknown',
          review_status text NOT NULL DEFAULT 'pending',
          notes text,
          question_count integer,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(document_id,page_number)
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_document_page_reviews_queue ON document_page_reviews(document_id,review_status,page_role,page_number)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_question_review_notes_status ON question_review_notes(status,reason_code)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_questions_ready_academic ON questions(subject_id,grade_level_id,curriculum_version_id,term_id,approved) WHERE approved=TRUE")
        # Data-integrity constraints. Guarded by pg_constraint checks so startup remains idempotent.
        constraints = [
          ("quiz_questions_points_positive","ALTER TABLE quiz_questions ADD CONSTRAINT quiz_questions_points_positive CHECK (points>0)"),
          ("quiz_questions_position_nonnegative","ALTER TABLE quiz_questions ADD CONSTRAINT quiz_questions_position_nonnegative CHECK (position>=0)"),
          ("quizzes_duration_positive","ALTER TABLE quizzes ADD CONSTRAINT quizzes_duration_positive CHECK (duration_minutes IS NULL OR duration_minutes>0)"),
          ("attempts_score_range","ALTER TABLE attempts ADD CONSTRAINT attempts_score_range CHECK (score IS NULL OR (score>=0 AND score<=max_score))"),
          ("attempts_max_score_nonnegative","ALTER TABLE attempts ADD CONSTRAINT attempts_max_score_nonnegative CHECK (max_score>=0)"),
          ("attempt_answers_points_nonnegative","ALTER TABLE attempt_answers ADD CONSTRAINT attempt_answers_points_nonnegative CHECK (points_awarded>=0)"),
          ("parent_notifications_attempts_count_range","ALTER TABLE parent_notifications ADD CONSTRAINT parent_notifications_attempts_count_range CHECK (attempts_count>=0 AND attempts_count<=5)"),
          ("parent_notifications_delivery_status_check","ALTER TABLE parent_notifications ADD CONSTRAINT parent_notifications_delivery_status_check CHECK (delivery_status IS NULL OR delivery_status IN ('sent','delivered','read','failed'))"),
        ]
        for name, ddl in constraints:
            if not con.execute("SELECT 1 FROM pg_constraint WHERE conname=%s",(name,)).fetchone():
                con.execute(ddl)
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_parent_notifications_provider_message_id ON parent_notifications(provider_message_id) WHERE provider_message_id IS NOT NULL")

        # Reconcile legacy visual QA notes with source-backed assets created by the
        # newer Drive/source-page workflow. This is intentionally narrow: only a
        # `visual_asset_required` note can be auto-resolved, and only when the
        # attached asset points to the exact same source document and source page.
        con.execute("""UPDATE question_review_notes qr
          SET status='resolved', source_verified=TRUE,
              details=concat_ws(' | ',nullif(qr.details,''),'تم التحقق آليًا من الأصل البصري المرتبط بنفس المستند والصفحة.'),
              updated_at=now()
          FROM questions q JOIN question_assets a ON a.question_id=q.id
          WHERE qr.question_id=q.id
            AND qr.status='open'
            AND qr.reason_code='visual_asset_required'
            AND a.document_id=q.document_id
            AND a.page_number=coalesce(q.source_page,q.page)""")

        # Readiness is intentionally not approval. Startup migrations may repair
        # deterministic metadata, but they never flip a question to approved.
        # A reviewer must explicitly approve through the guarded admin write path.

    # Lesson Studio schema changes are startup migrations. Keeping these DDL
    # statements out of request handlers avoids repeated ACCESS EXCLUSIVE locks.
    from .services.lesson_release_state import ensure_release_state_schema
    ensure_release_state_schema()
