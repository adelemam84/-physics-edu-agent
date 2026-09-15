from __future__ import annotations

import ast
from pathlib import Path
import unittest


SCRIPT = Path("tools/production_smoke.py")
WORKFLOW = Path(".github/workflows/production-smoke.yml")


class ContinuousProductionSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.script)

    def test_monitor_is_scheduled_manual_and_self_validating_on_main(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("branches: [main]", self.workflow)
        self.assertIn('cron: "17 */6 * * *"', self.workflow)

    def test_monitor_has_read_only_repo_permissions(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)

    def test_probe_only_uses_get_requests(self):
        self.assertIn('method="GET"', self.script)
        self.assertNotIn('method="POST"', self.script)
        self.assertNotIn('method="PUT"', self.script)
        self.assertNotIn('method="DELETE"', self.script)

    def test_probe_covers_public_runtime_contracts(self):
        for path in (
            "/health",
            "/health/ready",
            "/api/research-engine/status",
            "/api/next-release/status",
        ):
            self.assertIn(path, self.script)

    def test_probe_has_bounded_retries_and_timeout(self):
        self.assertIn("SMOKE_TIMEOUT_SECONDS", self.script)
        self.assertIn("SMOKE_ATTEMPTS", self.script)
        self.assertIn("timeout=TIMEOUT_SECONDS", self.script)

    def test_evidence_is_always_uploaded(self):
        self.assertIn("if: always()", self.workflow)
        self.assertIn("production-smoke-results.json", self.workflow)


if __name__ == "__main__":
    unittest.main()
