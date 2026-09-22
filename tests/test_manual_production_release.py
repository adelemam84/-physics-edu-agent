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
            SCRIPT.index("deploy --prod"),
        )

    def test_release_uses_remote_vercel_build_not_local_prebuilt_artifact(self):
        self.assertNotIn("vercel build --prod", SCRIPT)
        self.assertNotIn("deploy --prebuilt", SCRIPT)
        self.assertIn("deploy --prod --skip-domain --yes --no-wait", SCRIPT)

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

    def test_sensitive_admin_key_does_not_require_plaintext_retrieval(self):
        self.assertIn('ADMIN_API_KEY', SCRIPT)
        self.assertNotIn('/v10/projects/', SCRIPT)
        self.assertNotIn('"decrypt": "true"', SCRIPT)
        self.assertNotIn('ADMIN_LOGIN_BODY', SCRIPT)

    def test_admin_key_runtime_presence_is_checked_before_and_after_promotion(self):
        staged = SCRIPT.index('/api/admin/session --deployment "$STAGE_URL"')
        promote = SCRIPT.index('promote "$STAGE_URL" --yes')
        production = SCRIPT.index('$PRODUCTION_URL/api/admin/session"', promote)
        self.assertLess(staged, promote)
        self.assertLess(promote, production)
        self.assertIn('Staged ADMIN_API_KEY is not configured at runtime', SCRIPT)
        self.assertIn('Production ADMIN_API_KEY is not configured after promotion', SCRIPT)

    def test_async_vercel_deploy_waits_on_exact_url_without_duplicate_poll_deploys(self):
        self.assertIn(r"grep -Eo 'https://[^[:space:]]+\.vercel\.app'", SCRIPT)
        self.assertIn('inspect "$url" --wait --timeout=5m', SCRIPT)
        self.assertIn('did not reach READY within 5 minutes', SCRIPT)
        self.assertNotIn('for inspect_attempt in $(seq 1 24)', SCRIPT)

    def test_production_smoke_runs_after_promotion(self):
        promote = SCRIPT.index('promote "$STAGE_URL" --yes')
        health = SCRIPT.index('$PRODUCTION_URL/health"', promote)
        ready = SCRIPT.index('$PRODUCTION_URL/health/ready"', promote)
        self.assertLess(promote, health)
        self.assertLess(health, ready)


if __name__ == "__main__":
    unittest.main()
