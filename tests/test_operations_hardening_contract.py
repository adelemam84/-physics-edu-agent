from __future__ import annotations

import inspect
import unittest

from app import (
    adaptive_practice,
    lesson_studio_second_reviewer,
    research_engine,
    science_lesson_studio,
    student_review_exports,
    student_session_api,
    visual_review_assistant,
)


class OperationsHardeningContractTests(unittest.TestCase):
    def test_expensive_ai_paths_emit_telemetry(self):
        self.assertIn("record_ai_usage", inspect.getsource(research_engine._execute_orchestrated))
        self.assertIn("record_ai_usage", inspect.getsource(science_lesson_studio._gemini_text))
        self.assertIn("record_ai_usage", inspect.getsource(science_lesson_studio._mathpix_ocr))
        self.assertIn("record_ai_usage", inspect.getsource(lesson_studio_second_reviewer._openai_review))

    def test_expensive_mutations_are_rate_limited(self):
        self.assertIn("enforce_request_policy", inspect.getsource(student_session_api.create_student_session))
        self.assertIn("enforce_subject_policy", inspect.getsource(adaptive_practice.create_student_adaptive_quiz))
        self.assertIn("enforce_subject_policy", inspect.getsource(student_review_exports.student_mistakes_review_pdf))
        self.assertIn("enforce_request_policy", inspect.getsource(research_engine.api_research_engine_query))
        self.assertIn("enforce_request_policy", inspect.getsource(science_lesson_studio.process_lesson_job))
        self.assertIn("enforce_request_policy", inspect.getsource(lesson_studio_second_reviewer.run_second_review))
        self.assertIn("enforce_request_policy", inspect.getsource(visual_review_assistant.visual_review_batch_suggest))


if __name__ == "__main__":
    unittest.main()
