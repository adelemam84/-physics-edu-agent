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

    def test_local_python_build_prerequisites_are_explicit(self):
        self.assertIn("Install uv for local Vercel build", self.text)
        self.assertIn("python -m pip install --disable-pip-version-check --upgrade uv", self.text)

    def test_node_matches_current_vercel_runtime_generation(self):
        self.assertIn('node-version: "24"', self.text)

    def test_release_does_not_mutate_runtime_secrets(self):
        self.assertNotIn("vercel env add STUDENT_SESSION_SECRET", self.text)
        self.assertNotIn("openssl rand -hex 32", self.text)

    def test_required_production_env_names_are_preflighted_without_values(self):
        self.assertIn("Validate production runtime configuration", self.text)
        for name in (
            "DATABASE_URL",
            "ADMIN_API_KEY",
            "STUDENT_SESSION_SECRET",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_ENDPOINT_URL_S3",
            "AWS_REGION",
        ):
            self.assertIn(f'"{name}"', self.text)
        self.assertIn("Missing required production environment keys", self.text)

    def test_controlled_release_provenance_is_injected_at_runtime(self):
        self.assertIn("--env RELEASE_GIT_REF=main", self.text)
        self.assertIn('--env RELEASE_GIT_SHA="$GITHUB_SHA"', self.text)

    def test_runtime_bootstrap_runs_inside_ephemeral_staged_deployment(self):
        self.assertNotIn("vercel env run -e production", self.text)
        self.assertIn("Bootstrap staged production runtime", self.text)
        self.assertIn("--env RELEASE_BOOTSTRAP_TOKEN=", self.text)
        self.assertIn("X-Release-Bootstrap-Token:", self.text)
        self.assertIn("/api/internal/release-bootstrap", self.text)
        build = self.text.index("Build production artifact")
        bootstrap = self.text.index("Bootstrap staged production runtime")
        stage = self.text.index("Stage production deployment without bootstrap credential")
        self.assertLess(build, bootstrap)
        self.assertLess(bootstrap, stage)

    def test_bootstrap_credential_is_not_present_on_promoted_deployment(self):
        final_stage = self.text.index("Stage production deployment without bootstrap credential")
        staged_health = self.text.index("Verify staged health contract")
        final_block = self.text[final_stage:staged_health]
        self.assertNotIn("RELEASE_BOOTSTRAP_TOKEN", final_block)
        self.assertIn("Remove bootstrap-only deployment", self.text)
        self.assertIn('vercel remove "$BOOTSTRAP_DEPLOYMENT_URL"', self.text)

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

    def test_vercel_curl_uses_environment_auth_not_curl_passthrough_token(self):
        self.assertIn('vercel curl /health --deployment "$DEPLOYMENT_URL"', self.text)
        self.assertIn('vercel curl /health/ready --deployment "$DEPLOYMENT_URL"', self.text)
        self.assertNotIn('vercel curl /health --deployment "$DEPLOYMENT_URL" --token=', self.text)
        self.assertNotIn('vercel curl /health/ready --deployment "$DEPLOYMENT_URL" --token=', self.text)

    def test_concurrent_production_releases_are_serialized(self):
        self.assertIn("group: physics-edu-agent-production", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_release_marker_is_bound_to_its_parent_code_commit(self):
        self.assertIn("fetch-depth: 2", self.text)
        self.assertIn("requested_code_sha", self.text)
        self.assertIn('PARENT_SHA="$(git rev-parse HEAD^)"', self.text)
        self.assertIn(
            'REQUESTED_CODE_SHA" != "$PARENT_SHA',
            self.text,
        )

    def test_generated_vercel_workspace_must_not_dirty_release_source(self):
        self.assertIn(
            "Verify clean release workspace after Vercel pull",
            self.text,
        )
        self.assertIn(
            "Verify clean release workspace after build",
            self.text,
        )
        self.assertGreaterEqual(
            self.text.count('git status --porcelain --untracked-files=all'),
            2,
        )

    def test_vercel_transient_python_manifests_are_locally_excluded_only_when_untracked(self):
        self.assertIn(
            "Isolate Vercel-generated dependency metadata",
            self.text,
        )
        self.assertIn("for generated in pyproject.toml uv.lock", self.text)
        self.assertIn(
            'git ls-files --error-unmatch "$generated"',
            self.text,
        )
        self.assertIn(
            'printf \'/%s\\n\' "$generated" >> .git/info/exclude',
            self.text,
        )
        self.assertNotIn('rm -f -- "$generated"', self.text)
        self.assertIn(
            "unexpected non-ignored repository files",
            self.text,
        )

    def test_generated_release_files_are_gitignored(self):
        gitignore = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn(".vercel/", gitignore)
        self.assertIn("__pycache__/", gitignore)
        self.assertIn("*.py[cod]", gitignore)
        self.assertIn("!.env.example", gitignore)
        self.assertNotIn("pyproject.toml", gitignore)
        self.assertNotIn("uv.lock", gitignore)


if __name__ == "__main__":
    unittest.main()
