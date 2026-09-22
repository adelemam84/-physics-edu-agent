from __future__ import annotations

from pathlib import Path
import unittest

SCRIPT = Path("tools/manual_production_release.sh").read_text(encoding="utf-8")


class ManualProductionReleaseTests(unittest.TestCase):
    def test_archive_source_can_supply_verified_sha_without_git_fetch_state(self):
        self.assertIn('SOURCE_SHA="${RELEASE_SOURCE_SHA:-}"', SCRIPT)
        self.assertIn('SOURCE_REF="${RELEASE_SOURCE_REF:-}"', SCRIPT)
        self.assertIn('Archive release source must declare RELEASE_SOURCE_REF=main', SCRIPT)
        self.assertIn('HEAD_SHA="$SOURCE_SHA"', SCRIPT)
        self.assertIn('Archive source workspace verified without mutable Git network state', SCRIPT)

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
        staged = SCRIPT.index('"${STAGE_URL}/api/admin/session"')
        promote = SCRIPT.index('promote "$STAGE_URL" --yes')
        production = SCRIPT.index('$PRODUCTION_URL/api/admin/session"', promote)
        self.assertLess(staged, promote)
        self.assertLess(promote, production)
        self.assertIn('Staged ADMIN_API_KEY is not configured at runtime', SCRIPT)
        self.assertIn('Production ADMIN_API_KEY is not configured after promotion', SCRIPT)

    def test_vercel_curl_uses_full_deployment_urls_and_native_curl_flags(self):
        self.assertIn('curl "${BOOTSTRAP_URL}/api/internal/release-bootstrap" -X POST', SCRIPT)
        self.assertIn('curl "${STAGE_URL}/health" --fail-with-body', SCRIPT)
        self.assertIn('curl "${STAGE_URL}/health/ready" --fail-with-body', SCRIPT)
        self.assertIn('curl "${STAGE_URL}/api/admin/session" --fail-with-body', SCRIPT)
        self.assertNotIn('--deployment "$BOOTSTRAP_URL"', SCRIPT)
        self.assertNotIn('--deployment "$STAGE_URL"', SCRIPT)
    def test_release_temp_files_are_portable_between_git_bash_and_windows_python(self):
        self.assertIn('TMP_DIR=".git/release-tmp"', SCRIPT)
        self.assertIn('mkdir -p "$TMP_DIR"', SCRIPT)
        self.assertIn('rm -rf -- "$TMP_DIR"', SCRIPT)
        self.assertNotIn("/tmp/physics-", SCRIPT)
        self.assertIn('Path(".git/release-tmp/bootstrap.json")', SCRIPT)
        self.assertIn('Path(".git/release-tmp/stage-health.json")', SCRIPT)
        self.assertIn('Path(".git/release-tmp/prod-health.json")', SCRIPT)

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
