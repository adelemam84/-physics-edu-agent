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
        "lesson_studio",
        "creative_integrations",
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
