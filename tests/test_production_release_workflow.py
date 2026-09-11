from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/production-release.yml")


class ControlledProductionReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_release_is_explicit_and_main_scoped(self):
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("branches: [main]", self.text)
        self.assertIn("- .release/production.json", self.text)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', self.text)

    def test_release_credential_is_secret_backed(self):
        self.assertIn("secrets.VERCEL_TOKEN", self.text)
        self.assertNotIn("VERCEL_TOKEN: token_", self.text)
        self.assertNotIn("VERCEL_TOKEN: vcp_", self.text)

    def test_cli_is_pinned(self):
        self.assertIn("VERCEL_CLI_VERSION: 59.15.1", self.text)
        self.assertIn('vercel@${VERCEL_CLI_VERSION}', self.text)

    def test_production_is_staged_before_domain_assignment(self):
        stage = self.text.index("--prod --skip-domain")
        staged_health = self.text.index("Verify staged health contract")
        promote = self.text.index("Promote verified deployment")
        production_smoke = self.text.index("Verify canonical production")
        self.assertLess(stage, staged_health)
        self.assertLess(staged_health, promote)
        self.assertLess(promote, production_smoke)

    def test_readiness_is_a_promotion_gate(self):
        self.assertIn("vercel curl /health/ready", self.text)
        self.assertIn("ready.get('status') != 'ready'", self.text)

    def test_concurrent_production_releases_are_serialized(self):
        self.assertIn("group: physics-edu-agent-production", self.text)
        self.assertIn("cancel-in-progress: false", self.text)


if __name__ == "__main__":
    unittest.main()
