from __future__ import annotations

import inspect
import unittest

from app import student_command_center as command


class StudentCommandCenterTests(unittest.TestCase):
    def test_evidence_confidence_stays_low_when_data_is_sparse(self):
        result = command._evidence_confidence(
            {"recent_attempts": 1},
            {"lessons": [{"responses": 1}]},
            {"responses_7d": 2},
        )
        self.assertEqual(result["level"], "low")
        self.assertLess(result["score"], 50)

    def test_evidence_confidence_can_reach_high_with_broad_evidence(self):
        result = command._evidence_confidence(
            {"recent_attempts": 5},
            {"lessons": [{"responses": 3} for _ in range(5)]},
            {"responses_7d": 30},
        )
        self.assertEqual(result["level"], "high")
        self.assertGreaterEqual(result["score"], 70)

    def test_adaptive_recommendation_wins_today_mission(self):
        mission = command._today_mission(
            {"recommendations": [{"action": "adaptive_practice", "title": "عالج الضعف", "reason": "مفهوم ضعيف"}]},
            [{"question_id": 1}],
            {"level": "building"},
        )
        self.assertEqual(mission["kind"], "adaptive_practice")
        self.assertEqual(mission["primary_action"]["type"], "adaptive_practice")
        self.assertEqual(mission["primary_action"]["count"], 10)

    def test_next_lesson_is_selected_only_when_recommendation_is_ready(self):
        mission = command._today_mission(
            {"recommendations": [{"action": "study_next", "lesson_id": 44, "title": "الدرس التالي"}]},
            [],
            {"level": "nearly_ready"},
        )
        self.assertEqual(mission["kind"], "study_lesson")
        self.assertEqual(mission["primary_action"]["path"], "/student/lesson/44")

    def test_command_center_has_no_llm_decision_path(self):
        source = inspect.getsource(command)
        lowered = source.lower()
        self.assertNotIn("openai", lowered)
        self.assertNotIn("gemini", lowered)
        self.assertNotIn("anthropic", lowered)
        self.assertIn('"llm_decision_making": False', source)

    def test_student_ui_is_session_only(self):
        self.assertIn("/api/student/session", command.PAGE)
        self.assertIn("/api/student/command-center", command.PAGE)
        self.assertNotIn("student_code=", command.PAGE)
        self.assertNotIn("sessionStorage", command.PAGE)


if __name__ == "__main__":
    unittest.main()
