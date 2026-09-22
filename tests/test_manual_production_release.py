from __future__ import annotations

from pathlib import Path
import unittest

SCRIPT = Path("tools/manual_production_release.sh").read_text(encoding="utf-8")


class ManualProductionReleaseTests(unittest.TestCase):
    def test_requires_main_and_clean_workspace(self):
        self.assertIn('git rev-parse --abbrev-ref HEAD', SCRIPT)
        self.assertIn('Release must run from main', SCRIPT)
        self.assertIn('git status --porcelain --untracked-files=all', SCRIPT)

    def test_runs_compile_and_full_regression_suite_before_deploy(self):
        self.assertLess(SCRIPT.index("python -m compileall"), SCRIPT.index("vercel@"))
        self.assertLess(
            SCRIPT.index("python -m unittest discover -s tests -v"),
            SCRIPT.index("deploy --prebuilt"),
        )

    def test_bootstrap_is_isolated_and_ephemeral(self):
        self.assertIn("--skip-domain", SCRIPT)
        self.assertIn("RELEASE_BOOTSTRAP_TOKEN", SCRIPT)
        self.assertIn("/api/internal/release-bootstrap", SCRIPT)
        self.assertIn("trap cleanup EXIT", SCRIPT)

    def test_stage_does_not_promote_without_explicit_flag(self):
        self.assertIn("--promote", SCRIPT)
        self.assertIn('if [ "$PROMOTE" -ne 1 ]', SCRIPT)
        self.assertIn("Canonical production was NOT changed", SCRIPT)

    def test_content_ingestion_is_never_enabled_and_must_stay_locked(self):
        self.assertNotIn("CONTENT_INGESTION_ENABLED=true", SCRIPT)
        self.assertGreaterEqual(
            SCRIPT.count('content_ingestion") != "locked"'),
            2,
        )

    def test_admin_key_is_verified_without_putting_secret_on_command_line(self):
        self.assertIn('ADMIN_LOGIN_BODY="$(mktemp)"', SCRIPT)
        self.assertIn('chmod 600 "$ADMIN_LOGIN_BODY"', SCRIPT)
        self.assertGreaterEqual(SCRIPT.count("/api/admin/login"), 2)
        self.assertGreaterEqual(SCRIPT.count('--data-binary "@$ADMIN_LOGIN_BODY"'), 2)
        self.assertIn("Staged ADMIN_API_KEY verification failed", SCRIPT)
        self.assertIn("Production ADMIN_API_KEY verification failed after promotion", SCRIPT)
        self.assertIn('rm -f -- "$ADMIN_LOGIN_BODY"', SCRIPT)
        self.assertNotIn('echo "$ADMIN_API_KEY"', SCRIPT)
        self.assertNotIn('--data "$ADMIN_API_KEY"', SCRIPT)

    def test_admin_key_gate_runs_before_and_after_promotion(self):
        staged = SCRIPT.index('/api/admin/login --deployment "$STAGE_URL"')
        promote = SCRIPT.index('promote "$STAGE_URL" --yes')
        production = SCRIPT.index('$PRODUCTION_URL/api/admin/login"', promote)
        self.assertLess(staged, promote)
        self.assertLess(promote, production)

    def test_production_smoke_runs_after_promotion(self):
        promote = SCRIPT.index('promote "$STAGE_URL" --yes')
        health = SCRIPT.index('$PRODUCTION_URL/health"', promote)
        ready = SCRIPT.index('$PRODUCTION_URL/health/ready"', promote)
        self.assertLess(promote, health)
        self.assertLess(health, ready)


if __name__ == "__main__":
    unittest.main()
