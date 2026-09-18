from pathlib import Path
import unittest

VISUAL = Path("app/visual_review_assistant.py").read_text(encoding="utf-8")
GOV = Path("app/services/ai_governance.py").read_text(encoding="utf-8")
MAINT = Path("app/content_maintenance_api.py").read_text(encoding="utf-8")


class Edu003OpenAIFallbackContractTests(unittest.TestCase):
    def test_visual_fallback_uses_same_source_image_and_is_non_persistent(self):
        self.assertIn('"type": "input_image"', VISUAL)
        self.assertIn('"data:image/jpeg;base64,"', VISUAL)
        self.assertIn('"store": False', VISUAL)
        self.assertIn("source_image_only_no_auto_approval", VISUAL)

    def test_fallback_is_bounded_and_only_after_provider_failure(self):
        self.assertIn("def _should_openai_fallback", VISUAL)
        self.assertIn("{408, 429, 500, 502, 503, 504}", VISUAL)
        self.assertIn("provider_timeout=45", VISUAL)
        self.assertIn("provider_retry=False", VISUAL)
        self.assertIn("timeout=60", VISUAL)
        self.assertIn("retry=False", VISUAL)

    def test_openai_fallback_is_telemetry_and_budget_governed(self):
        self.assertIn('task="visual_review_fallback"', VISUAL)
        self.assertIn('provider="openai"', VISUAL)
        self.assertIn("enforce_ai_budget(", VISUAL)
        self.assertIn("record_ai_usage(", VISUAL)

    def test_governance_declares_visual_fallback_without_auto_authority(self):
        self.assertIn("openai_visual_fallback", GOV)
        self.assertIn("exact_source_image_gemini_with_openai_fallback", GOV)
        self.assertIn("visual_review_fallback_preserves_exact_source_image", GOV)

    def test_maintenance_status_exposes_secret_free_provider_readiness(self):
        self.assertIn('"ai_providers": provider_status()', MAINT)
        self.assertIn('"openai_visual_fallback": model_settings()["openai_visual_fallback"]', MAINT)


if __name__ == "__main__":
    unittest.main()
