from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/production-rollback.yml").read_text(encoding="utf-8")


class ControlledProductionRollbackWorkflowTests(unittest.TestCase):
    def test_rollback_derives_expected_version_from_target_health(self):
        self.assertIn("ROLLBACK_EXPECT_VERSION", WORKFLOW)
        self.assertIn('health.get("version")', WORKFLOW)
        self.assertIn('with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as fh:', WORKFLOW)
        self.assertIn('fh.write(f"ROLLBACK_EXPECT_VERSION={version}\\n")', WORKFLOW)

    def test_rollback_runs_full_read_only_post_verification(self):
        for token in (
            "Run post-rollback production smoke",
            "python tools/production_smoke.py",
            "Run post-rollback technical readiness",
            "python tools/technical_readiness_probe.py",
            "Run post-rollback performance readiness",
            "python tools/performance_probe.py",
        ):
            self.assertIn(token, WORKFLOW)

    def test_rollback_probes_use_recovered_version_and_content_lock(self):
        self.assertIn("SMOKE_EXPECT_VERSION: ${{ env.ROLLBACK_EXPECT_VERSION }}", WORKFLOW)
        self.assertIn("TECH_READY_EXPECT_VERSION: ${{ env.ROLLBACK_EXPECT_VERSION }}", WORKFLOW)
        self.assertIn('TECH_READY_EXPECT_CONTENT_INGESTION_LOCKED: "true"', WORKFLOW)

    def test_rollback_uploads_post_verification_evidence(self):
        self.assertIn("production-rollback-verification-${{ github.run_id }}", WORKFLOW)
        for path in (
            "production-smoke-results.json",
            "technical-readiness-results.json",
            "performance-results.json",
        ):
            self.assertIn(path, WORKFLOW)
        self.assertIn("if: always()", WORKFLOW)

    def test_rollback_post_verification_does_not_add_write_probes(self):
        self.assertNotIn("CONTENT_INGESTION_ENABLED=true", WORKFLOW)
        self.assertNotIn("python tools/execute_edu001_edu003.py", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
