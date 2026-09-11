from __future__ import annotations

import inspect
import unittest

from app import teacher_intervention_queue as queue


class TeacherInterventionQueueTests(unittest.TestCase):
    def test_no_attempts_require_baseline_not_high_risk_label(self):
        result = queue._risk_profile(
            days_inactive=None,
            recent_average=None,
            weak_lessons=0,
            repeated_error_questions=0,
            completed_attempts=0,
        )
        self.assertEqual(result["priority"], "baseline")
        self.assertEqual(result["next_action"], "baseline_assessment")

    def test_combined_low_performance_and_weakness_is_high_priority(self):
        result = queue._risk_profile(
            days_inactive=8,
            recent_average=45.0,
            weak_lessons=2,
            repeated_error_questions=2,
            completed_attempts=5,
        )
        self.assertEqual(result["priority"], "high")
        self.assertGreaterEqual(result["score"], 55)
        self.assertEqual(result["next_action"], "reengage_student")

    def test_recent_weak_student_gets_adaptive_practice_action(self):
        result = queue._risk_profile(
            days_inactive=1,
            recent_average=62.0,
            weak_lessons=2,
            repeated_error_questions=1,
            completed_attempts=4,
        )
        self.assertEqual(result["next_action"], "adaptive_practice")
        self.assertIn(result["priority"], {"medium", "high"})

    def test_healthy_recent_student_is_low_priority(self):
        result = queue._risk_profile(
            days_inactive=1,
            recent_average=88.0,
            weak_lessons=0,
            repeated_error_questions=0,
            completed_attempts=6,
        )
        self.assertEqual(result["priority"], "low")
        self.assertEqual(result["next_action"], "monitor")

    def test_risk_classification_never_uses_llm_or_auto_messages(self):
        source = inspect.getsource(queue)
        lowered = source.lower()
        self.assertNotIn("openai", lowered)
        self.assertNotIn("gemini", lowered)
        self.assertIn('"llm_risk_classification": False', source)
        self.assertIn('"no_automatic_messaging": True', source)

    def test_admin_ui_explains_deterministic_policy(self):
        self.assertIn("لا يستخدم نموذج ذكاء لتصنيف الطالب", queue.PAGE)
        self.assertIn("/api/admin/intervention-queue", queue.PAGE)
        self.assertIn("خريطة المعرفة", queue.PAGE)


if __name__ == "__main__":
    unittest.main()
