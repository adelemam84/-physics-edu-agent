from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/production-rollback.yml")
RUNBOOK = Path("docs/production-recovery-runbook.md")


class ProductionRecoveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_rollback_requires_explicit_confirmation_and_target(self):
        self.assertIn("target_deployment:", self.workflow)
        self.assertIn("confirm:", self.workflow)
        self.assertIn('"$CONFIRM" != "ROLLBACK"', self.workflow)

    def test_target_is_health_checked_before_traffic_change(self):
        target_check = self.workflow.index("Verify target deployment is healthy before rollback")
        rollback = self.workflow.index("Roll back production traffic")
        self.assertLess(target_check, rollback)
        self.assertIn("vercel curl /health", self.workflow)
        self.assertIn("vercel curl /health/ready", self.workflow)

    def test_rollback_and_release_share_serialization_group(self):
        release = Path(".github/workflows/production-release.yml").read_text(encoding="utf-8")
        self.assertIn("group: physics-edu-agent-production", self.workflow)
        self.assertIn("group: physics-edu-agent-production", release)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_database_is_never_automatically_rewound(self):
        self.assertNotIn("neon", self.workflow.lower())
        self.assertNotIn("restore_snapshot", self.workflow)
        self.assertIn("Database: unchanged", self.workflow)

    def test_post_rollback_canonical_smoke_is_required(self):
        rollback = self.workflow.index("Roll back production traffic")
        smoke = self.workflow.index("Verify canonical production after rollback")
        self.assertLess(rollback, smoke)
        self.assertIn("$PRODUCTION_URL/health/ready", self.workflow)

    def test_runbook_records_current_recovery_constraints(self):
        self.assertIn("6 hours", self.runbook)
        self.assertIn("backup-technical-hardening-2026-09-16", self.runbook)
        self.assertIn("Automatic snapshot schedules are not enabled", self.runbook)
        self.assertIn("Do not delete or reset production automatically", self.runbook)


if __name__ == "__main__":
    unittest.main()
