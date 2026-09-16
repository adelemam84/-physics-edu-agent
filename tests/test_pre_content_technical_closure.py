from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.version import APPLICATION_VERSION


BASELINE_PATH = Path(".release/pre-content-baseline.json")
RELEASE_PATH = Path(".release/production.json")


class PreContentTechnicalClosureContractTests(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        self.release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))

    def test_baseline_is_technical_only_and_content_stays_deferred(self):
        self.assertTrue(self.baseline["technical_complete"])
        self.assertFalse(self.baseline["content_complete"])
        self.assertEqual(self.baseline["content_ingestion"], "locked")
        self.assertEqual(self.baseline["content_phase"], "deferred")
        self.assertFalse(
            self.baseline["guardrails"]["curriculum_source_uploads_allowed"]
        )
        self.assertFalse(
            self.baseline["guardrails"]["question_file_uploads_allowed"]
        )

    def test_baseline_matches_current_runtime_and_release_request(self):
        self.assertEqual(self.baseline["application_version"], APPLICATION_VERSION)
        self.assertEqual(self.release["content_ingestion"], "locked")
        self.assertEqual(self.release["scope"], "technical_runtime_only")
        self.assertEqual(
            self.baseline["production"]["requested_code_sha"],
            self.release["requested_code_sha"],
        )

    def test_recovery_checkpoint_is_current_no_compute_handoff_branch(self):
        recovery = self.baseline["database_recovery"]
        self.assertEqual(recovery["provider"], "neon")
        self.assertEqual(recovery["state"], "ready")
        self.assertTrue(recovery["no_compute"])
        self.assertEqual(
            recovery["recovery_branch_name"],
            "pre-content-handoff-2026-09-17",
        )
        self.assertTrue(recovery["recovery_branch_id"].startswith("br-"))

    def test_closure_records_machine_verifiable_evidence(self):
        evidence = self.baseline["evidence"]
        for key in (
            "controlled_production_release_run",
            "ci_run",
            "security_audit_run",
            "final_technical_readiness_run",
            "final_technical_readiness_job",
        ):
            self.assertIsInstance(evidence[key], int)
            self.assertGreater(evidence[key], 0)
        self.assertGreaterEqual(evidence["final_technical_readiness_attempt"], 2)

    def test_only_content_gates_remain_open(self):
        remaining = self.baseline["remaining_work"]
        self.assertEqual(remaining["technical_issues_open"], 0)
        self.assertEqual(set(remaining["content_gates"]), {"EDU-001", "EDU-003"})

    def test_manifest_contains_no_secret_like_keys(self):
        forbidden = ("password", "secret", "token", "api_key", "access_key")

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    lowered = str(key).lower()
                    self.assertFalse(
                        any(part in lowered for part in forbidden),
                        f"secret-like key in baseline: {key}",
                    )
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self.baseline)


if __name__ == "__main__":
    unittest.main()
