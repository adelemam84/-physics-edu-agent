from pathlib import Path
import unittest

STUDIO = Path("app/science_lesson_studio.py").read_text(encoding="utf-8")
VISUAL = Path("app/visual_review_assistant.py").read_text(encoding="utf-8")

class Edu003ProviderTimeoutTests(unittest.TestCase):
    def test_gemini_helper_accepts_task_specific_timeout_and_retry(self):
        self.assertIn("provider_timeout: float = 90", STUDIO)
        self.assertIn("provider_retry: bool = True", STUDIO)
        self.assertIn("timeout=provider_timeout", STUDIO)
        self.assertIn("retry=provider_retry", STUDIO)

    def test_visual_review_uses_fail_fast_provider_policy(self):
        self.assertTrue("task='visual_review'" in VISUAL or 'task="visual_review"' in VISUAL)
        self.assertIn("provider_timeout=45", VISUAL)
        self.assertIn("provider_retry=False", VISUAL)

if __name__ == "__main__":
    unittest.main()
