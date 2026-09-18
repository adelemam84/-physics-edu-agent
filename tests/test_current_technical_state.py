from __future__ import annotations

import json
from pathlib import Path
import unittest

from app.version import APPLICATION_VERSION


CURRENT_STATE_PATH = Path(".release/current-technical-state.json")


class CurrentTechnicalStateContractTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads(CURRENT_STATE_PATH.read_text(encoding="utf-8"))

    def test_state_tracks_current_application_version(self):
        self.assertEqual(self.state["application_version"], APPLICATION_VERSION)
        self.assertTrue(self.state["technical_complete"])
        self.assertFalse(self.state["content_complete"])

    def test_content_phase_remains_locked_and_deferred(self):
        self.assertEqual(self.state["content_ingestion"], "locked")
        self.assertEqual(self.state["content_phase"], "deferred")
        guardrails = self.state["guardrails"]
        self.assertFalse(guardrails["curriculum_source_uploads_allowed"])
        self.assertFalse(guardrails["question_file_uploads_allowed"])
        self.assertFalse(guardrails["automatic_scientific_approval_allowed"])

    def test_runtime_attestation_is_fail_closed(self):
        attestation = self.state["runtime_attestation"]
        self.assertTrue(attestation["exact_version_required"])
        self.assertTrue(attestation["content_ingestion_lock_required"])
        self.assertEqual(attestation["health_version"], APPLICATION_VERSION)
        self.assertEqual(attestation["readiness_version"], APPLICATION_VERSION)
        self.assertEqual(attestation["readiness_content_ingestion"], "locked")
        self.assertEqual(attestation["runtime_errors_last_6h"], 0)

    def test_current_state_points_to_immutable_historical_baseline(self):
        self.assertEqual(
            self.state["historical_baseline"],
            ".release/pre-content-baseline.json",
        )

    def test_evidence_and_production_identity_are_machine_verifiable(self):
        production = self.state["production"]
        self.assertEqual(production["canonical_url"], "https://physics-edu-agent.vercel.app")
        self.assertTrue(production["deployment_id"].startswith("dpl_"))
        for key in ("released_code_sha", "release_marker_sha", "post_release_hardening_sha"):
            value = production[key]
            self.assertEqual(len(value), 40)
            self.assertTrue(all(ch in "0123456789abcdef" for ch in value))

        for value in self.state["evidence"].values():
            self.assertIsInstance(value, int)
            self.assertGreater(value, 0)

    def test_only_content_gates_remain_open(self):
        remaining = self.state["remaining_work"]
        self.assertEqual(remaining["technical_issues_open"], 0)
        self.assertEqual(set(remaining["content_gates"]), {"EDU-001", "EDU-003"})


if __name__ == "__main__":
    unittest.main()
