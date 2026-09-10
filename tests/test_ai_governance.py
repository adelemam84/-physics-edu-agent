from __future__ import annotations

import unittest

from app.services.ai_governance import governance_snapshot, task_policies


class AIGovernanceTests(unittest.TestCase):
    """Protect the model-routing and scientific-authority contract."""

    def test_no_model_can_approve_publish_or_write_question_bank(self):
        for task in task_policies():
            self.assertFalse(task.can_auto_approve, task.task)
            self.assertFalse(task.can_publish, task.task)
            self.assertFalse(task.can_write_question_bank, task.task)

    def test_generative_scientific_tasks_are_source_grounded_and_advisory(self):
        generative = {"gemini", "openai", "mathpix"}
        for task in task_policies():
            if task.provider in generative:
                self.assertTrue(task.source_grounded, task.task)
                self.assertTrue(task.advisory_only, task.task)
                self.assertTrue(task.human_gate, task.task)

    def test_final_grading_and_adaptive_selection_are_deterministic(self):
        by_id = {x.task: x for x in task_policies()}
        self.assertEqual(by_id["grading"].provider, "deterministic")
        self.assertIsNone(by_id["grading"].model)
        self.assertEqual(by_id["adaptive_practice_selection"].provider, "deterministic")
        self.assertIsNone(by_id["adaptive_practice_selection"].model)

    def test_independent_reviewer_is_separate_from_source_engine(self):
        by_id = {x.task: x for x in task_policies()}
        self.assertEqual(by_id["source_analysis"].provider, "gemini")
        self.assertEqual(by_id["independent_scientific_review"].provider, "openai")
        self.assertNotEqual(
            by_id["source_analysis"].provider,
            by_id["independent_scientific_review"].provider,
        )

    def test_snapshot_is_secret_free_and_fail_safe(self):
        snap = governance_snapshot()
        text = repr(snap).lower()
        self.assertNotIn("api_key", text)
        self.assertNotIn("app_key", text)
        self.assertEqual(snap["summary"]["auto_approval_tasks"], 0)
        self.assertEqual(snap["summary"]["auto_publish_tasks"], 0)
        self.assertEqual(snap["summary"]["question_bank_write_tasks"], 0)
        self.assertTrue(snap["principles"]["pdf_is_scientific_source_of_truth"])


if __name__ == "__main__":
    unittest.main()
