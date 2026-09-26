from __future__ import annotations

import unittest
from contextlib import ExitStack, nullcontext
from unittest.mock import patch

from app import release_hardening as release
from app import source_review


class ReleaseHardeningReadinessTests(unittest.TestCase):
    def _research(self, *, gemini=False, auto_write=False):
        return {
            "configured": gemini,
            "orchestrator": {"status": "active"},
            "guardrails": {
                "question_bank_auto_write": auto_write,
            },
        }

    def _blueprint(self, *, feasible=True):
        return {
            "blueprint": {
                "objective_questions": 23,
                "essay_questions": 23,
            },
            "active_shape_feasible": feasible,
            "gaps": {
                "objective": 0 if feasible else 3,
                "essay": 0 if feasible else 2,
            },
        }

    def _coverage(self, *, ready=True):
        return {
            "summary": {
                "coverage_ready": ready,
                "open_zero_question_pages": 0 if ready else 4,
                "count_mismatch_pages": 0 if ready else 1,
            }
        }

    def _integrity(self, *, ready=True):
        return {
            "ready": ready,
            "invalid_approved_questions": 0 if ready else 1,
            "question_lesson_mismatches": 0,
            "quiz_question_mismatches": 0,
            "critical_open_qa": 0,
        }

    def _status(
        self,
        *,
        gemini=False,
        file_search=False,
        auto_write=False,
        coverage=True,
        integrity=True,
        feasible=True,
    ):
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(release, "connect", return_value=nullcontext(object()))
            )
            stack.enter_context(
                patch.object(
                    release,
                    "research_engine_status",
                    return_value=self._research(
                        gemini=gemini,
                        auto_write=auto_write,
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    release,
                    "configured_store_name",
                    return_value="stores/test" if file_search else "",
                )
            )
            stack.enter_context(
                patch.object(
                    release,
                    "blueprint_readiness",
                    return_value=self._blueprint(feasible=feasible),
                )
            )
            stack.enter_context(
                patch.object(
                    release,
                    "active_content_integrity_snapshot",
                    return_value=self._integrity(ready=integrity),
                )
            )
            stack.enter_context(
                patch.object(
                    source_review,
                    "_source_page_coverage_snapshot",
                    return_value=self._coverage(ready=coverage),
                )
            )
            stack.enter_context(
                patch.object(
                    release,
                    "_sync_summary",
                    return_value={
                        "total": 0,
                        "active": 0,
                        "processing": 0,
                        "failed": 0,
                    },
                )
            )
            return release.next_release_status()

    def test_missing_optional_ai_does_not_block_runtime(self):
        data = self._status(gemini=False, file_search=False)
        self.assertEqual(data["runtime_blockers"], [])
        self.assertEqual(data["content_gates"], [])
        self.assertEqual(data["release_state"], "runtime_ready")
        self.assertFalse(data["optional_capabilities"]["gemini_source_engine"])
        self.assertFalse(data["optional_capabilities"]["gemini_file_search"])
        self.assertEqual(len(data["optional_warnings"]), 2)
        self.assertTrue(
            data["policy"]["optional_ai_capabilities_do_not_block_runtime"]
        )

    def test_content_gate_remains_separate_from_runtime(self):
        data = self._status(coverage=False)
        self.assertEqual(data["runtime_blockers"], [])
        self.assertTrue(data["content_gates"])
        self.assertEqual(
            data["release_state"],
            "runtime_ready_content_gate_open",
        )

    def test_ai_auto_write_guard_failure_is_runtime_blocker(self):
        data = self._status(auto_write=True)
        self.assertTrue(data["runtime_blockers"])
        self.assertEqual(
            data["release_state"],
            "code_ready_pending_runtime_activation",
        )
        self.assertIn(
            "AI question-bank auto-write guard is not enforced",
            data["runtime_blockers"],
        )

    def test_configured_ai_is_reported_without_changing_release_authority(self):
        data = self._status(gemini=True, file_search=True)
        self.assertTrue(data["optional_capabilities"]["gemini_source_engine"])
        self.assertTrue(data["optional_capabilities"]["gemini_file_search"])
        self.assertEqual(data["optional_warnings"], [])
        self.assertEqual(data["runtime_blockers"], [])
        self.assertEqual(data["release_state"], "runtime_ready")

    def test_deployment_policy_accepts_equivalent_manual_controlled_release(self):
        data = self._status()
        policy = data["deployment_policy"]
        self.assertIn("deterministic regression gates", policy)
        self.assertIn("production smoke checks", policy)
        self.assertIn("manual controlled release path", policy)


if __name__ == "__main__":
    unittest.main()
