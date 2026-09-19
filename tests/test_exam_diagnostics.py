from pathlib import Path


def test_exam_diagnostics_routes_and_source_grounding():
    source = Path("app/exam_diagnostics.py").read_text(encoding="utf-8")
    assert "/api/student/attempts/{attempt_id}/diagnostic" in source
    assert "/api/admin/attempts/{attempt_id}/diagnostic" in source
    assert "/student/results/{attempt_id}" in source
    assert "source_filename" in source
    assert "source_page" in source
    assert '"content_source": "approved_pdf_only"' in source
    assert '"ai_auto_grading_override": False' in source


def test_question_timing_is_bounded_and_accumulated():
    source = Path("app/student_quiz.py").read_text(encoding="utf-8")
    assert "time_spent_seconds: int = Field(default=0, ge=0, le=600)" in source
    assert "time_spent_seconds=attempt_answers.time_spent_seconds+EXCLUDED.time_spent_seconds" in source
    assert "consumeQuestionSeconds" in source
    assert "startQuestionClock" in source


def test_teacher_question_analytics_include_timing_and_common_wrong_answer():
    source = Path("app/analytics.py").read_text(encoding="utf-8")
    assert "average_time_seconds" in source
    assert "common_wrong_answer" in source
    assert "common_wrong_count" in source
    assert "/admin/question-analytics" in source


def test_teacher_override_requires_reason_and_is_audited():
    engine = Path("app/exam_engine.py").read_text(encoding="utf-8")
    reports = Path("app/student_reports.py").read_text(encoding="utf-8")
    assert "attempt_score_overrides" in engine
    assert "reason: str = Field(min_length=3" in engine
    assert "/api/admin/attempts/{attempt_id}/score" in engine
    assert "score_overrides" in reports
    assert "التعديل بشري فقط" in reports


def test_personal_platform_has_no_exam_commercial_layer():
    files = [
        Path("app/exam_engine.py").read_text(encoding="utf-8").lower(),
        Path("app/exam_diagnostics.py").read_text(encoding="utf-8").lower(),
    ]
    text = "\n".join(files)
    for forbidden in ("subscription_plan", "exam_credit", "paywall", "billing_customer"):
        assert forbidden not in text
