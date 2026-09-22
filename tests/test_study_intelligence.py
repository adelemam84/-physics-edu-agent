from pathlib import Path


def test_weakness_progression_compares_recent_and_previous_attempt_windows():
    source = Path("app/study_intelligence.py").read_text(encoding="utf-8")
    assert "latest_5_completed_attempts_vs_previous_5" in source
    assert "row_number() OVER(ORDER BY a.completed_at DESC,a.id DESC) rn" in source
    assert "ra.rn<=5" in source
    assert "ra.rn BETWEEN 6 AND 10" in source
    assert "persistent_weakness" in source
    assert "worsening" in source
    assert "recovered" in source
    assert '"no_ai_auto_classification": True' in source


def test_personal_study_queue_is_deterministic_and_source_grounded():
    source = Path("app/study_intelligence.py").read_text(encoding="utf-8")
    assert "priority_score" in source
    assert "approved_explanatory_pdf_only" in source
    assert "approved_source_questions_only" in source
    assert "deterministic_priority_score" in source
    assert "lesson_source_mappings" in source
    assert "lsm.mapping_status=\'approved\'" in source
    assert "d.kind IN ('lesson','explanation','textbook','notes')" in source
    assert '"/api/student/adaptive-practice/create?count=10"' in source


def test_study_queue_and_progression_have_student_and_admin_endpoints():
    source = Path("app/study_intelligence.py").read_text(encoding="utf-8")
    assert "/api/student/weakness-progression" in source
    assert "/api/admin/students/{student_id}/weakness-progression" in source
    assert "/api/student/study-queue" in source
    assert "/api/admin/students/{student_id}/study-queue" in source
    assert "/student/study-queue" in source


def test_learning_suite_integrates_new_study_intelligence():
    source = Path("app/advanced_learning.py").read_text(encoding="utf-8")
    assert "build_personal_study_queue" in source
    assert "build_weakness_progression" in source
    assert '"dynamic_study_queue": dynamic_study_queue' in source
    assert '"weakness_progression": weakness_progression' in source
    assert "9 أدوات تعليمية متقدمة" in source


def test_personal_study_queue_remains_noncommercial():
    source = Path("app/study_intelligence.py").read_text(encoding="utf-8").lower()
    assert '"commercial_features": false' in source
    for forbidden in ("subscription_plan", "billing_customer", "exam_credit", "paywall"):
        assert forbidden not in source
