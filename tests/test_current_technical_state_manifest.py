from __future__ import annotations

import json
from pathlib import Path
import unittest


STATE_PATH = Path(".release/current-technical-state.json")


class CurrentTechnicalStateManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    def test_current_state_keeps_content_phase_locked(self):
        self.assertTrue(self.state["technical_complete"])
        self.assertFalse(self.state["content_complete"])
        self.assertEqual(self.state["content_ingestion"], "locked")
        self.assertEqual(self.state["content_phase"], "deferred")
        self.assertFalse(self.state["guardrails"]["curriculum_source_uploads_allowed"])
        self.assertFalse(self.state["guardrails"]["question_file_uploads_allowed"])

    def test_current_state_has_no_open_technical_issues(self):
        remaining = self.state["remaining_work"]
        self.assertEqual(remaining["technical_issues_open"], 0)
        self.assertEqual(set(remaining["content_gates"]), {"EDU-001", "EDU-003"})

    def test_post_release_gates_are_recorded_successfully(self):
        gates = self.state["post_release_gates"]
        self.assertEqual(
            gates,
            {
                "final_technical_readiness": "success",
                "performance_readiness": "success",
                "smoke_monitor": "success",
            },
        )
        evidence = self.state["evidence"]
        for key in (
            "controlled_production_release_run",
            "release_ci_run",
            "final_technical_readiness_run",
            "production_performance_readiness_run",
            "production_smoke_run",
        ):
            self.assertIsInstance(evidence[key], int)
            self.assertGreater(evidence[key], 0)

    def test_performance_attestation_remains_within_recorded_limits(self):
        perf = self.state["performance_attestation"]
        self.assertTrue(perf["passed"])
        self.assertEqual(perf["failures"], 0)
        self.assertEqual(perf["successes"], perf["request_count"])
        self.assertLessEqual(perf["p95_ms"], perf["p95_limit_ms"])
        self.assertLessEqual(perf["max_ms"], perf["max_limit_ms"])
        self.assertGreaterEqual(perf["warmup_rounds"], 1)
        self.assertGreaterEqual(perf["warmup_concurrency"], 1)

    def test_runtime_attestation_stays_locked_and_error_free(self):
        runtime = self.state["runtime_attestation"]
        self.assertTrue(runtime["exact_version_required"])
        self.assertTrue(runtime["content_ingestion_lock_required"])
        self.assertEqual(runtime["readiness_content_ingestion"], "locked")
        self.assertEqual(runtime["runtime_errors_last_1h"], 0)


if __name__ == "__main__":
    unittest.main()
