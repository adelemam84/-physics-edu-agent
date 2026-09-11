from __future__ import annotations

import unittest
from unittest.mock import patch

from app import operations_readiness as ops


class OperationsReadinessTests(unittest.TestCase):
    def _core(self, ready=True):
        return {
            "ready": ready,
            "whatsapp": {"a": False},
            "next_actions": [] if ready else [{"title": "fix core", "path": "/admin/readiness", "owner": "admin"}],
        }

    def _ai(self):
        return {
            "providers": {
                "gemini": {"configured": True},
                "openai": {"configured": False},
                "mathpix": {"configured": False},
            },
            "summary": {
                "auto_approval_tasks": 0,
                "auto_publish_tasks": 0,
                "question_bank_write_tasks": 0,
            },
            "principles": {"grading_final_decision_is_deterministic": True},
        }

    def test_optional_integrations_do_not_block_launch(self):
        with patch.object(ops, "system_readiness", return_value=self._core(True)), \
             patch.object(ops, "governance_snapshot", return_value=self._ai()), \
             patch.object(ops, "budget_snapshot", return_value={"configured": False, "level": "not_configured", "hard_block_active": False}), \
             patch.object(ops, "usage_snapshot", return_value={"summary": {}}), \
             patch.object(ops, "intervention_summary", return_value={}), \
             patch.object(ops, "_student_session_configured", return_value=True):
            data = ops.build_operations_readiness()
        self.assertTrue(data["ready_for_controlled_launch"])
        self.assertTrue(data["warnings"])
        self.assertFalse(data["blockers"])

    def test_core_content_failure_blocks_controlled_launch(self):
        with patch.object(ops, "system_readiness", return_value=self._core(False)), \
             patch.object(ops, "governance_snapshot", return_value=self._ai()), \
             patch.object(ops, "budget_snapshot", return_value={"configured": False, "level": "not_configured", "hard_block_active": False}), \
             patch.object(ops, "usage_snapshot", return_value={"summary": {}}), \
             patch.object(ops, "intervention_summary", return_value={}), \
             patch.object(ops, "_student_session_configured", return_value=True):
            data = ops.build_operations_readiness()
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertIn("core_content", {x["id"] for x in data["blockers"]})

    def test_exhausted_ai_budget_is_a_launch_blocker(self):
        with patch.object(ops, "system_readiness", return_value=self._core(True)), \
             patch.object(ops, "governance_snapshot", return_value=self._ai()), \
             patch.object(ops, "budget_snapshot", return_value={"configured": True, "level": "blocked", "hard_block_active": True}), \
             patch.object(ops, "usage_snapshot", return_value={"summary": {}}), \
             patch.object(ops, "intervention_summary", return_value={}), \
             patch.object(ops, "_student_session_configured", return_value=True):
            data = ops.build_operations_readiness()
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertIn("ai_budget", {x["id"] for x in data["blockers"]})

    def test_llms_never_become_launch_authority(self):
        with patch.object(ops, "system_readiness", return_value=self._core(True)), \
             patch.object(ops, "governance_snapshot", return_value=self._ai()), \
             patch.object(ops, "budget_snapshot", return_value={"configured": False, "level": "not_configured", "hard_block_active": False}), \
             patch.object(ops, "usage_snapshot", return_value={"summary": {}}), \
             patch.object(ops, "intervention_summary", return_value={}), \
             patch.object(ops, "_student_session_configured", return_value=True):
            data = ops.build_operations_readiness()
        self.assertTrue(data["launch_policy"]["ai_models_remain_advisory_for_scientific_content"])
        self.assertTrue(data["launch_policy"]["teacher_remains_final_for_interventions"])


if __name__ == "__main__":
    unittest.main()
