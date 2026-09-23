from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/rollback-preflight.yml").read_text(encoding="utf-8")
RUNBOOK = Path("OPERATIONS_RUNBOOK.md").read_text(encoding="utf-8")


class RollbackPreflightWorkflowTests(unittest.TestCase):
    def test_preflight_is_manual_and_read_only(self):
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertIn("target_deployment:", WORKFLOW)
        self.assertIn("permissions:\n  contents: read", WORKFLOW)
        self.assertNotIn("vercel rollback ", WORKFLOW)
        self.assertNotIn("vercel promote ", WORKFLOW)
        self.assertNotIn("CONTENT_INGESTION_ENABLED=true", WORKFLOW)

    def test_preflight_validates_target_health_readiness_version_and_lock(self):
        for token in (
            "Verify rollback candidate",
            "vercel curl /health",
            "vercel curl /health/ready",
            'health.get("status") != "ok"',
            'ready.get("status") != "ready"',
            'health.get("version")',
            'ready.get("content_ingestion") != "locked"',
        ):
            self.assertIn(token, WORKFLOW)

    def test_preflight_collects_additional_read_only_status_evidence(self):
        self.assertIn("vercel curl /api/research-engine/status", WORKFLOW)
        self.assertIn("vercel curl /api/next-release/status", WORKFLOW)
        self.assertIn("rollback-preflight-results.json", WORKFLOW)
        self.assertIn("production-rollback-preflight-${{ github.run_id }}", WORKFLOW)

    def test_runbook_documents_preflight_before_real_rollback(self):
        self.assertIn("Rollback preflight", RUNBOOK)
        self.assertIn("does not change production traffic", RUNBOOK)
        self.assertIn("Controlled Production Rollback", RUNBOOK)


if __name__ == "__main__":
    unittest.main()
