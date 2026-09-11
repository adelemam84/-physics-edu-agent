from __future__ import annotations
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
STORAGE_BACKEND = "neon_postgresql" if DATABASE_URL else "not_configured"

STARTUP_MIGRATION_LOCK_KEY = 2026091101
_DIRECT_DATABASE_CONTEXT: ContextVar[bool] = ContextVar(
    "physics_edu_direct_database",
    default=False,
)


def _replace_hostname(url: str, hostname: str) -> str:
    """Replace only the URL hostname while preserving credentials, port, path and query."""
    parts = urlsplit(str(url or "").strip())
    if not parts.hostname:
        return str(url or "").strip()
    if "@" in parts.netloc:
        userinfo, hostport = parts.netloc.rsplit("@", 1)
        prefix = userinfo + "@"
    else:
        hostport = parts.netloc
        prefix = ""
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(
        (parts.scheme, f"{prefix}{hostname}{port}", parts.path, parts.query, parts.fragment)
    )


def _neon_hostname(url: str) -> str:
    try:
        return str(urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def _is_neon_url(url: str) -> bool:
    return _neon_hostname(url).endswith(".neon.tech")


def _is_pooled_url(url: str) -> bool:
    return "-pooler." in _neon_hostname(url)


def _to_neon_pooled_url(url: str) -> str:
    """Return the equivalent Neon PgBouncer URL when the input is a Neon direct URL."""
    hostname = _neon_hostname(url)
    if not hostname or not hostname.endswith(".neon.tech") or "-pooler." in hostname:
        return str(url or "").strip()
    labels = hostname.split(".")
    labels[0] = labels[0] + "-pooler"
    return _replace_hostname(url, ".".join(labels))


def _to_neon_direct_url(url: str) -> str:
    """Return the equivalent direct Neon URL when the input is a pooled Neon URL."""
    hostname = _neon_hostname(url)
    if not hostname or "-pooler." not in hostname:
        return str(url or "").strip()
    return _replace_hostname(url, hostname.replace("-pooler.", ".", 1))


def resolve_database_urls(env: Mapping[str, str] | None = None) -> dict:
    """Resolve secret-bearing runtime/direct URLs without exposing them in diagnostics."""
    source = env if env is not None else os.environ
    configured = str(source.get("DATABASE_URL") or "").strip()
    direct_override = str(source.get("DATABASE_DIRECT_URL") or "").strip()
    policy = str(source.get("DATABASE_RUNTIME_POOLING") or "auto").strip().lower()
    if policy not in {"auto", "pooled", "direct"}:
        policy = "auto"

    direct_source = direct_override or configured
    direct_url = (
        _to_neon_direct_url(direct_source)
        if _is_neon_url(direct_source)
        else direct_source
    )

    runtime_url = configured
    on_vercel = (
        str(source.get("VERCEL") or "") == "1"
        or bool(str(source.get("VERCEL_ENV") or "").strip())
    )
    if policy == "pooled" and _is_neon_url(runtime_url):
        runtime_url = _to_neon_pooled_url(runtime_url)
    elif policy == "direct" and _is_neon_url(runtime_url):
        runtime_url = _to_neon_direct_url(runtime_url)
    elif policy == "auto" and on_vercel and _is_neon_url(runtime_url):
        runtime_url = _to_neon_pooled_url(runtime_url)

    return {
        "configured_url": configured,
        "runtime_url": runtime_url,
        "direct_url": direct_url,
        "pooling_policy": policy,
        "direct_override": bool(direct_override),
        "on_vercel": on_vercel,
    }


_DATABASE_URLS = resolve_database_urls()
RUNTIME_DATABASE_URL = _DATABASE_URLS["runtime_url"]
DIRECT_DATABASE_URL = _DATABASE_URLS["direct_url"]
DATABASE_RUNTIME_POOLING = _DATABASE_URLS["pooling_policy"]


def database_connection_profile(env: Mapping[str, str] | None = None) -> dict:
    """Return a secret-free description of runtime pooling and migration safety."""
    urls = resolve_database_urls(env) if env is not None else dict(_DATABASE_URLS)
    runtime_url = str(urls.get("runtime_url") or "")
    direct_url = str(urls.get("direct_url") or "")
    is_neon = _is_neon_url(runtime_url or direct_url)
    runtime_mode = "pooled" if _is_pooled_url(runtime_url) else "direct"
    direct_mode = "pooled" if _is_pooled_url(direct_url) else "direct"
    migration_safe = bool(direct_url) and direct_mode == "direct"
    return {
        "configured": bool(urls.get("configured_url")),
        "is_neon": is_neon,
        "on_vercel": bool(urls.get("on_vercel")),
        "pooling_policy": urls.get("pooling_policy"),
        "runtime_mode": runtime_mode if runtime_url else "not_configured",
        "migration_mode": direct_mode if direct_url else "not_configured",
        "migration_safe": migration_safe,
        "direct_override": bool(urls.get("direct_override")),
        "automatic_pooler_derivation": bool(
            is_neon
            and runtime_url
            and runtime_url != str(urls.get("configured_url") or "")
            and _is_pooled_url(runtime_url)
        ),
        "secret_values_returned": False,
    }


@contextmanager
def direct_database_context():
    """Force nested connect() calls to use the direct migration-safe URL."""
    token = _DIRECT_DATABASE_CONTEXT.set(True)
    try:
        yield
    finally:
        _DIRECT_DATABASE_CONTEXT.reset(token)


def _selected_database_url() -> str:
    return DIRECT_DATABASE_URL if _DIRECT_DATABASE_CONTEXT.get() else RUNTIME_DATABASE_URL


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)
    return value if value > 0 else float(default)


def _nonnegative_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)
    return value if value >= 0 else int(default)


def database_resilience_profile(env: Mapping[str, str] | None = None) -> dict:
    """Return secret-free connection retry and transaction timeout policy."""
    source = env if env is not None else os.environ

    def positive_int(name: str, default: int) -> int:
        try:
            value = int(source.get(name, str(default)))
        except (TypeError, ValueError):
            return int(default)
        return value if value > 0 else int(default)

    def nonnegative_int(name: str, default: int) -> int:
        try:
            value = int(source.get(name, str(default)))
        except (TypeError, ValueError):
            return int(default)
        return value if value >= 0 else int(default)

    return {
        "connect_timeout_seconds": positive_int(
            "DATABASE_CONNECT_TIMEOUT_SECONDS", 10
        ),
        "connect_retries": nonnegative_int("DATABASE_CONNECT_RETRIES", 2),
        "retry_base_delay_ms": positive_int(
            "DATABASE_RETRY_BASE_DELAY_MS", 150
        ),
        "retry_max_delay_ms": positive_int(
            "DATABASE_RETRY_MAX_DELAY_MS", 1200
        ),
        "runtime_statement_timeout_ms": positive_int(
            "DATABASE_STATEMENT_TIMEOUT_MS", 45000
        ),
        "runtime_lock_timeout_ms": positive_int(
            "DATABASE_LOCK_TIMEOUT_MS", 5000
        ),
        "migration_statement_timeout_ms": positive_int(
            "DATABASE_MIGRATION_STATEMENT_TIMEOUT_MS", 180000
        ),
        "migration_lock_timeout_ms": positive_int(
            "DATABASE_MIGRATION_LOCK_TIMEOUT_MS", 30000
        ),
        "transaction_retries": 0,
        "secret_values_returned": False,
    }


def _open_connection(
    database_url: str,
    *,
    autocommit: bool = False,
    application_name: str = "physics-edu-agent",
):
    """Retry connection establishment only; never replay a started transaction."""
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    import psycopg
    from psycopg.rows import dict_row

    policy = database_resilience_profile()
    retries = int(policy["connect_retries"])
    delay_ms = int(policy["retry_base_delay_ms"])
    max_delay_ms = int(policy["retry_max_delay_ms"])

    for attempt in range(retries + 1):
        try:
            return psycopg.connect(
                database_url,
                row_factory=dict_row,
                connect_timeout=int(policy["connect_timeout_seconds"]),
                autocommit=autocommit,
                application_name=application_name,
            )
        except psycopg.OperationalError:
            if attempt >= retries:
                raise
            wait_ms = min(max_delay_ms, delay_ms * (2 ** attempt))
            time.sleep(wait_ms / 1000.0)


def _apply_transaction_timeouts(con, *, migration: bool) -> None:
    """Apply transaction-local limits compatible with PgBouncer transaction mode."""
    policy = database_resilience_profile()
    if migration:
        statement_ms = int(policy["migration_statement_timeout_ms"])
        lock_ms = int(policy["migration_lock_timeout_ms"])
    else:
        statement_ms = int(policy["runtime_statement_timeout_ms"])
        lock_ms = int(policy["runtime_lock_timeout_ms"])
    con.execute(
        """SELECT
             set_config('statement_timeout', %s, true),
             set_config('lock_timeout', %s, true)""",
        (f"{statement_ms}ms", f"{lock_ms}ms"),
    )


def _acquire_startup_advisory_lock(
    con,
    *,
    wait_seconds: float,
    poll_seconds: float,
) -> int:
    """Acquire the shared startup lock with a bounded wait; return attempts."""
    deadline = time.monotonic() + max(0.1, float(wait_seconds))
    attempts = 0
    while True:
        attempts += 1
        row = con.execute(
            "SELECT pg_try_advisory_lock(%s) acquired",
            (STARTUP_MIGRATION_LOCK_KEY,),
        ).fetchone()
        if row and bool(row["acquired"]):
            return attempts
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Timed out waiting for startup migration lock"
            )
        time.sleep(max(0.01, float(poll_seconds)))


@contextmanager
def startup_migration_lock():
    """Serialize startup DDL and force all nested DB work onto the direct connection."""
    if not DIRECT_DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    wait_seconds = _positive_float_env(
        "STARTUP_MIGRATION_LOCK_WAIT_SECONDS", 20.0
    )
    poll_seconds = _positive_float_env(
        "STARTUP_MIGRATION_LOCK_POLL_SECONDS", 0.25
    )
    con = _open_connection(
        DIRECT_DATABASE_URL,
        autocommit=True,
        application_name="physics-edu-startup-lock",
    )
    acquired = False
    try:
        _acquire_startup_advisory_lock(
            con,
            wait_seconds=wait_seconds,
            poll_seconds=poll_seconds,
        )
        acquired = True
        with direct_database_context():
            yield
    finally:
        if acquired:
            try:
                con.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (STARTUP_MIGRATION_LOCK_KEY,),
                )
            except Exception:
                pass
        con.close()


@contextmanager
def connect():
    """Open one transaction using pooled runtime DB or direct migration DB by context."""
    database_url = _selected_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    migration = _DIRECT_DATABASE_CONTEXT.get()
    con = _open_connection(
        database_url,
        application_name=(
            "physics-edu-migration"
            if migration
            else "physics-edu-runtime"
        ),
    )
    try:
        _apply_transaction_timeouts(con, migration=migration)
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
        con.execute("ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS owner_student_id bigint REFERENCES students(id) ON DELETE CASCADE")
        con.execute("CREATE INDEX IF NOT EXISTS idx_quizzes_owner_student ON quizzes(owner_student_id,created_at DESC)")
        # Legacy adaptive quizzes were globally published before student ownership
        # existed. Archive any still-public legacy rows so they cannot leak across
        # student portals; students can generate a new isolated remedial quiz.
        con.execute("""WITH affected AS (
          UPDATE quizzes q
          SET published=FALSE,lifecycle_status='archived',
              archived_at=coalesce(archived_at,now()),ready_at=NULL
          WHERE q.owner_student_id IS NULL AND q.published=TRUE
            AND EXISTS(
              SELECT 1 FROM quiz_audit_log al
              WHERE al.quiz_id=q.id AND al.action='adaptive_publish'
            )
          RETURNING q.id,q.quality_score
        )
        INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score,details)
        SELECT id,'legacy_adaptive_isolation','published','archived',quality_score,
               '{"reason":"missing_owner_student_id"}'::jsonb
        FROM affected""")
        con.execute("""CREATE TABLE IF NOT EXISTS request_rate_limits(
          scope text NOT NULL,
          subject_hash text NOT NULL,
          window_start timestamptz NOT NULL DEFAULT now(),
          hits integer NOT NULL DEFAULT 0,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(scope,subject_hash)
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_request_rate_limits_updated ON request_rate_limits(updated_at)")
        con.execute("""CREATE TABLE IF NOT EXISTS ai_usage_events(
          id bigserial PRIMARY KEY,
          provider text NOT NULL,
          task text NOT NULL,
          model text,
          status text NOT NULL,
          latency_ms integer,
          input_tokens bigint NOT NULL DEFAULT 0,
          output_tokens bigint NOT NULL DEFAULT 0,
          total_tokens bigint NOT NULL DEFAULT 0,
          estimated_cost_usd numeric(18,8),
          usage_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
          error_code text,
          created_at timestamptz NOT NULL DEFAULT now()
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_events_created ON ai_usage_events(created_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_events_task_provider ON ai_usage_events(task,provider,created_at DESC)")
        con.execute("DELETE FROM request_rate_limits WHERE updated_at < now() - interval '7 days'")
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
