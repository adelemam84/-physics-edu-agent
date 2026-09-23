from pathlib import Path

from app.feature_status import feature_status_snapshot


def test_feature_status_exposes_major_platform_capabilities_without_secrets():
    source = Path("app/feature_status.py").read_text(encoding="utf-8")
    for feature_id in (
        "admin_command_center",
        "student_sessions",
        "quiz_lifecycle",
        "adaptive_learning",
        "personal_exam_engine",
        "exam_diagnostics",
        "advanced_exam_analytics",
        "study_intelligence",
        "score_override_audit",
        "lesson_studio",
        "creative_integrations",
        "canva",
        "google_slides",
        "gemini_notebook_enterprise",
        "ai_operations",
        "whatsapp",
        "content_ingestion",
    ):
        assert feature_id in source
    assert "ADMIN_API_KEY" not in source
    assert "WHATSAPP_ACCESS_TOKEN" in source
    assert "os.getenv" in source


def test_feature_status_keeps_content_ingestion_explicitly_locked_when_disabled(monkeypatch):
    monkeypatch.setenv("CONTENT_INGESTION_ENABLED", "false")
    snapshot = feature_status_snapshot()
    content = next(x for x in snapshot["items"] if x["id"] == "content_ingestion")
    assert content["state"] == "locked"
    assert snapshot["content_ingestion_locked"] is True


def test_feature_status_routes_are_registered():
    source = Path("app/feature_status.py").read_text(encoding="utf-8")
    assert '/api/admin/feature-status' in source
    assert '/admin/feature-status' in source


def test_feature_status_tracks_free_only_external_integrations(monkeypatch):
    monkeypatch.setenv("PROJECT_FREE_ONLY", "true")
    monkeypatch.setenv("AI_FREE_ONLY", "")
    snapshot = feature_status_snapshot()
    by_id = {item["id"]: item for item in snapshot["items"]}
    assert by_id["gemini_notebook_enterprise"]["state"] == "deferred"
    assert by_id["canva"]["state"] in {"configured", "optional"}
    assert by_id["google_slides"]["state"] in {"configured", "optional"}


def test_feature_status_routes_exam_intelligence_to_real_admin_surfaces():
    snapshot = feature_status_snapshot()
    by_id = {item["id"]: item for item in snapshot["items"]}
    assert by_id["personal_exam_engine"]["path"] == "/admin/exam-engine"
    assert by_id["advanced_exam_analytics"]["path"] == "/admin/exam-analytics"
    assert by_id["exam_diagnostics"]["path"] == "/admin/progress"
    assert by_id["study_intelligence"]["path"] == "/admin/students"
    assert by_id["score_override_audit"]["path"] == "/admin/progress"
    for feature_id in (
        "personal_exam_engine",
        "exam_diagnostics",
        "advanced_exam_analytics",
        "study_intelligence",
        "score_override_audit",
    ):
        assert by_id[feature_id]["state"] == "active"
