from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app import operations_readiness as ops


class OperationsReadinessTests(unittest.TestCase):
    def _core(self, ready=True):
        return {
            "ready": ready,
            "whatsapp": {"a": False},
            "next_actions": [] if ready else [
                {"title": "fix core", "path": "/admin/readiness", "owner": "admin"}
            ],
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

    def _release(self, *, runtime_blockers=None, content_gates=None):
        runtime_blockers = list(runtime_blockers or [])
        content_gates = list(content_gates or [])
        return {
            "release_state": (
                "code_ready_pending_runtime_activation"
                if runtime_blockers
                else "runtime_ready_content_gate_open"
                if content_gates
                else "runtime_ready"
            ),
            "runtime_blockers": runtime_blockers,
            "content_gates": content_gates,
        }

    def _build(
        self,
        *,
        core_ready=True,
        runtime_blockers=None,
        content_gates=None,
        budget_blocked=False,
        database=True,
        admin=True,
        student_session=True,
        storage=True,
    ):
        with ExitStack() as stack:
            stack.enter_context(patch.object(ops, "system_readiness", return_value=self._core(core_ready)))
            stack.enter_context(patch.object(ops, "governance_snapshot", return_value=self._ai()))
            stack.enter_context(patch.object(
                ops,
                "budget_snapshot",
                return_value={
                    "configured": budget_blocked,
                    "level": "blocked" if budget_blocked else "not_configured",
                    "hard_block_active": budget_blocked,
                },
            ))
            stack.enter_context(patch.object(ops, "usage_snapshot", return_value={"summary": {}}))
            stack.enter_context(patch.object(ops, "intervention_summary", return_value={}))
            stack.enter_context(patch.object(ops, "_database_configured", return_value=database))
            stack.enter_context(patch.object(ops, "admin_configured", return_value=admin))
            stack.enter_context(patch.object(ops, "_student_session_configured", return_value=student_session))
            stack.enter_context(patch.object(ops, "storage_configured", return_value=storage))
            stack.enter_context(patch.object(
                ops,
                "_release_status",
                return_value=self._release(
                    runtime_blockers=runtime_blockers,
                    content_gates=content_gates,
                ),
            ))
            return ops.build_operations_readiness()

    def test_optional_integrations_do_not_block_launch(self):
        data = self._build()
        self.assertTrue(data["ready_for_technical_handoff"])
        self.assertTrue(data["ready_for_controlled_launch"])
        self.assertTrue(data["warnings"])
        self.assertFalse(data["blockers"])

    def test_content_failure_blocks_launch_but_not_technical_handoff(self):
        data = self._build(core_ready=False)
        self.assertTrue(data["ready_for_technical_handoff"])
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertFalse(data["content_release_ready"])
        self.assertIn("core_content", {x["id"] for x in data["blockers"]})

    def test_release_content_gate_is_separate_from_technical_readiness(self):
        data = self._build(content_gates=["23+23 exam bank gap: objective=0, essay=16"])
        self.assertTrue(data["ready_for_technical_handoff"])
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertEqual(len(data["technical_blockers"]), 0)
        self.assertEqual(len(data["content_gates"]), 1)
        self.assertIn("release_content_gates", {x["id"] for x in data["blockers"]})

    def test_runtime_blocker_blocks_technical_handoff(self):
        data = self._build(runtime_blockers=["Gemini File Search Store missing"])
        self.assertFalse(data["ready_for_technical_handoff"])
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertIn("runtime_activation", {x["id"] for x in data["technical_blockers"]})

    def test_storage_or_auth_gap_is_a_technical_blocker(self):
        data = self._build(storage=False)
        self.assertFalse(data["ready_for_technical_handoff"])
        self.assertIn("object_storage", {x["id"] for x in data["technical_blockers"]})
        data = self._build(admin=False)
        self.assertFalse(data["ready_for_technical_handoff"])
        self.assertIn("admin_access", {x["id"] for x in data["technical_blockers"]})

    def test_exhausted_ai_budget_blocks_technical_and_launch_readiness(self):
        data = self._build(budget_blocked=True)
        self.assertFalse(data["ready_for_technical_handoff"])
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertIn("ai_budget", {x["id"] for x in data["technical_blockers"]})

    def test_llms_never_become_launch_authority(self):
        data = self._build()
        self.assertTrue(data["launch_policy"]["ai_models_remain_advisory_for_scientific_content"])
        self.assertTrue(data["launch_policy"]["teacher_remains_final_for_interventions"])
        self.assertTrue(data["launch_policy"]["technical_handoff_excludes_content_completeness"])


if __name__ == "__main__":
    unittest.main()
