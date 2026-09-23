from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

# Register the feature routes that Feature Status is expected to report.
from app import exam_advanced_analytics  # noqa: F401
from app import exam_diagnostics  # noqa: F401
from app import exam_engine  # noqa: F401
from app import study_intelligence  # noqa: F401
from app.feature_status import feature_status_snapshot


class FeatureStatusTests(unittest.TestCase):
    def test_feature_status_exposes_major_platform_capabilities_without_secrets(self):
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
            self.assertIn(feature_id, source)
        self.assertNotIn("ADMIN_API_KEY", source)
        self.assertIn("WHATSAPP_ACCESS_TOKEN", source)
        self.assertIn("os.getenv", source)

    def test_feature_status_keeps_content_ingestion_explicitly_locked_when_disabled(self):
        with patch.dict(os.environ, {"CONTENT_INGESTION_ENABLED": "false"}, clear=False):
            snapshot = feature_status_snapshot()
        content = next(x for x in snapshot["items"] if x["id"] == "content_ingestion")
        self.assertEqual(content["state"], "locked")
        self.assertTrue(snapshot["content_ingestion_locked"])

    def test_feature_status_routes_are_registered(self):
        source = Path("app/feature_status.py").read_text(encoding="utf-8")
        self.assertIn('/api/admin/feature-status', source)
        self.assertIn('/admin/feature-status', source)

    def test_feature_status_tracks_free_only_external_integrations(self):
        with patch.dict(
            os.environ,
            {"PROJECT_FREE_ONLY": "true", "AI_FREE_ONLY": ""},
            clear=False,
        ):
            snapshot = feature_status_snapshot()
        by_id = {item["id"]: item for item in snapshot["items"]}
        self.assertEqual(by_id["gemini_notebook_enterprise"]["state"], "deferred")
        self.assertIn(by_id["canva"]["state"], {"configured", "optional"})
        self.assertIn(by_id["google_slides"]["state"], {"configured", "optional"})

    def test_feature_status_routes_exam_intelligence_to_real_admin_surfaces(self):
        snapshot = feature_status_snapshot()
        by_id = {item["id"]: item for item in snapshot["items"]}
        self.assertEqual(by_id["personal_exam_engine"]["path"], "/admin/exam-engine")
        self.assertEqual(by_id["advanced_exam_analytics"]["path"], "/admin/exam-analytics")
        self.assertEqual(by_id["exam_diagnostics"]["path"], "/admin/progress")
        self.assertEqual(by_id["study_intelligence"]["path"], "/admin/students")
        self.assertEqual(by_id["score_override_audit"]["path"], "/admin/progress")
        for feature_id in (
            "personal_exam_engine",
            "exam_diagnostics",
            "advanced_exam_analytics",
            "study_intelligence",
            "score_override_audit",
        ):
            self.assertEqual(by_id[feature_id]["state"], "active")


if __name__ == "__main__":
    unittest.main()
