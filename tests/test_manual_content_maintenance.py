from __future__ import annotations

from pathlib import Path
import unittest


SCRIPT = Path("tools/manual_content_maintenance.sh").read_text(encoding="utf-8")


class ManualContentMaintenanceTests(unittest.TestCase):
    def test_requires_clean_main_and_optional_expected_sha(self):
        self.assertIn('git rev-parse --abbrev-ref HEAD', SCRIPT)
        self.assertIn('Maintenance must run from main', SCRIPT)
        self.assertIn('git status --porcelain --untracked-files=all', SCRIPT)
        self.assertIn('--expected-sha', SCRIPT)

    def test_uses_isolated_non_promoted_deployment(self):
        self.assertIn('--skip-domain', SCRIPT)
        self.assertNotIn(' promote ', SCRIPT)
        self.assertIn('Canonical production was NOT promoted or modified', SCRIPT)

    def test_maintenance_auth_is_ephemeral_and_content_unlock_is_isolated(self):
        self.assertIn('CONTENT_MAINTENANCE_TOKEN', SCRIPT)
        self.assertIn('CONTENT_INGESTION_ENABLED=true', SCRIPT)
        deploy = SCRIPT.index('deploy --prebuilt --prod --skip-domain')
        enabled = SCRIPT.index('CONTENT_INGESTION_ENABLED=true')
        self.assertGreater(enabled, deploy)
        self.assertNotIn('vercel env add CONTENT_INGESTION_ENABLED', SCRIPT)

    def test_enforces_free_only_ai(self):
        self.assertIn('--env AI_FREE_ONLY=true', SCRIPT)

    def test_skips_edu001_when_coverage_is_already_complete(self):
        self.assertIn('EDU-001 already complete', SCRIPT)
        self.assertIn('run_source electrical', SCRIPT)
        self.assertIn('run_source modern', SCRIPT)

    def test_processes_visuals_individually_and_fails_closed(self):
        self.assertIn('/visual-pending', SCRIPT)
        self.assertIn('/visual/$qid', SCRIPT)
        self.assertIn('status") != "suggested"', SCRIPT)
        self.assertIn('without_suggestion', SCRIPT)
        self.assertIn('EDU-003 incomplete', SCRIPT)

    def test_never_auto_approves_visual_content(self):
        self.assertIn('source_grounded_only_no_visual_auto_approval', SCRIPT)
        self.assertIn('Human visual review is still required', SCRIPT)

    def test_cleanup_always_removes_isolated_deployment(self):
        self.assertIn('trap cleanup EXIT', SCRIPT)
        self.assertIn('remove "$DEPLOYMENT_URL" --yes', SCRIPT)


if __name__ == "__main__":
    unittest.main()
