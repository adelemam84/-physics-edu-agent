from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.exam_engine import exam_delivery_state, normalize_access_code


def test_exam_access_code_normalization():
    assert normalize_access_code(" ab-c 234 ") == "ABC234"


def test_delivery_state_tracks_schedule_window():
    now = datetime.now(timezone.utc)
    base = {
        "published": True,
        "lifecycle_status": "published",
        "db_now": now,
        "available_from": None,
        "available_until": None,
    }
    assert exam_delivery_state(base) == "open"
    assert exam_delivery_state({**base, "available_from": now + timedelta(minutes=5)}) == "scheduled"
    assert exam_delivery_state({**base, "available_until": now - timedelta(seconds=1)}) == "closed"
    assert exam_delivery_state({**base, "published": False}) == "unpublished"


def test_personal_exam_engine_schema_is_idempotent_and_noncommercial():
    source = Path("app/db.py").read_text(encoding="utf-8")
    assert "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS access_code text" in source
    assert "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS available_from timestamptz" in source
    assert "ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS available_until timestamptz" in source
    assert "CREATE TABLE IF NOT EXISTS exam_integrity_events" in source
    assert "CREATE TABLE IF NOT EXISTS attempt_question_order" in source
    assert "CREATE TABLE IF NOT EXISTS attempt_score_overrides" in source
    assert "shuffle_questions boolean NOT NULL DEFAULT false" in source
    assert "uq_quizzes_access_code_upper" in source
    lowered = source.lower()
    assert "exam_billing" not in lowered
    assert "exam_credits" not in lowered


def test_student_exam_runtime_enforces_schedule_and_keeps_autosave_resume():
    source = Path("app/student_quiz.py").read_text(encoding="utf-8")
    assert "ensure_exam_open(q)" in source
    assert "ensure_exam_open(quiz)" in source
    assert "/api/student/attempts/'+id+'/answer" in source
    assert "تم استكمال محاولتك السابقة" in source
    assert "reportIntegrity" in source
    assert "auto_submit" in source
    assert "ensure_attempt_question_order" in source
    assert "question_order" in source


def test_integrity_endpoint_is_rate_limited():
    source = Path("app/security_hardening.py").read_text(encoding="utf-8")
    assert "student_integrity_event" in source
    assert r"^/api/student/attempts/\d+/integrity-event$" in source


def test_teacher_score_override_is_audited_and_human_only():
    source = Path("app/exam_engine.py").read_text(encoding="utf-8")
    assert "/api/admin/attempts/{attempt_id}/score" in source
    assert "attempt_score_overrides" in source
    assert "reason: str = Field(min_length=3" in source
    assert "لا يمكن تعديل درجة محاولة لم يتم تسليمها" in source
    assert "الدرجة الجديدة لا يمكن أن تتجاوز الدرجة النهائية" in source
    assert "actor,'admin'" not in source  # no client-controlled actor field


def test_exam_code_resolution_uses_post_body_and_is_rate_limited():
    engine = Path("app/exam_engine.py").read_text(encoding="utf-8")
    hardening = Path("app/security_hardening.py").read_text(encoding="utf-8")
    assert '@app.post("/api/student/exams/resolve")' in engine
    assert "body:JSON.stringify({access_code:v})" in engine
    assert "resolve/'+encodeURIComponent(v)" not in engine
    assert '@app.get("/api/student/exams/resolve/{access_code}", deprecated=True)' in engine
    assert "student_exam_code_resolve" in hardening
    assert r"^/api/student/exams/resolve$" in hardening


def test_custom_exam_access_code_collision_is_handled_as_conflict():
    source = Path("app/exam_engine.py").read_text(encoding="utf-8")
    assert "AND id<>%s" in source
    assert "كود الاختبار مستخدم بالفعل" in source
