from __future__ import annotations

import unittest

from app.ai_operations import PAGE
from app.services.ai_governance import governance_snapshot


class AIOperationsContractTests(unittest.TestCase):
    def test_page_exposes_model_task_matrix_and_safety_language(self):
        self.assertIn("AI Operations", PAGE)
        self.assertIn("توزيع المهام", PAGE)
        self.assertIn("لا اعتماد آلي", PAGE)
        self.assertIn("/api/admin/ai-operations/summary", PAGE)

    def test_snapshot_contains_expected_high_value_tasks(self):
        tasks = {x["task"] for x in governance_snapshot()["tasks"]}
        expected = {
            "source_analysis",
            "visual_review",
            "handwriting_ocr_primary",
            "independent_scientific_review",
            "grading",
            "adaptive_practice_selection",
            "scientific_diagram_rendering",
        }
        self.assertTrue(expected.issubset(tasks), expected - tasks)


if __name__ == "__main__":
    unittest.main()
