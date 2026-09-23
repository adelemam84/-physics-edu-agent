from pathlib import Path


def test_advanced_exam_analytics_are_exam_scoped_and_deterministic():
    source = Path("app/exam_advanced_analytics.py").read_text(encoding="utf-8")
    assert "/api/admin/exams/{quiz_id}/advanced-analytics" in source
    assert "WHERE a0.quiz_id=%s AND a0.completed_at IS NOT NULL" in source
    assert '"analysis": "deterministic"' in source
    assert "flags_are_review_signals_not_auto_rejections" in source
    assert "very_low_success" in source
    assert "very_high_success" in source
    assert "time_outlier" in source


def test_attempt_weakness_training_is_source_grounded_and_excludes_original_questions():
    source = Path("app/adaptive_practice.py").read_text(encoding="utf-8")
    assert "build_attempt_weakness_practice" in source
    assert "/api/student/attempts/{attempt_id}/weakness-practice/create" in source
    assert "q.id<>ALL(%s)" in source
    assert "qa.document_id=q.document_id" in source
    assert "qa.page_number=coalesce(q.source_page,q.page)" in source
    assert "approved_exact_source_asset_only" in source
    assert "weakness_publish" in source


def test_student_diagnostic_links_to_weakness_training():
    source = Path("app/exam_diagnostics.py").read_text(encoding="utf-8")
    assert "إنشاء تدريب نقاط الضعف" in source
    assert "/weakness-practice/create?count=10" in source


def test_admin_dashboard_links_advanced_exam_analytics():
    source = Path("app/admin_dashboard.py").read_text(encoding="utf-8")
    assert "/admin/exam-analytics" in source
