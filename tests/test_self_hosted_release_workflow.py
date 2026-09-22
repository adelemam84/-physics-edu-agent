from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
SECURITY = (ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github/workflows/self-hosted-production-release.yml").read_text(encoding="utf-8")


class SelfHostedReleaseWorkflowTests(unittest.TestCase):
    def test_primary_ci_owns_pr_and_push_dependency_audit(self):
        self.assertIn('"pip-audit==2.10.1"', CI)
        self.assertIn("python -m pip_audit -r requirements.txt", CI)
        self.assertIn("pull_request:", CI)
        self.assertIn("branches: [main]", CI)

    def test_standalone_security_audit_is_scheduled_or_manual_only(self):
        self.assertIn("schedule:", SECURITY)
        self.assertIn("workflow_dispatch:", SECURITY)
        self.assertNotIn("pull_request:", SECURITY)
        self.assertNotIn("branches: [main]", SECURITY)

    def test_release_marker_only_pushes_do_not_relaunch_primary_ci(self):
        self.assertIn("paths-ignore:", CI)
        self.assertIn('".release/**"', CI)

    def test_new_release_supersedes_stale_in_progress_release(self):
        self.assertIn("group: physics-edu-agent-self-hosted-production", RELEASE)
        self.assertIn("cancel-in-progress: true", RELEASE)

    def test_release_keeps_self_hosted_runner_and_explicit_dependencies(self):
        self.assertIn("runs-on: self-hosted", RELEASE)
        self.assertIn("Install runtime dependencies", RELEASE)
        self.assertIn("python -m pip install --disable-pip-version-check -r requirements.txt", RELEASE)

    def test_release_runs_post_promotion_technical_readiness_and_uploads_evidence(self):
        self.assertIn("Run post-release technical readiness gate", RELEASE)
        self.assertIn("python tools/technical_readiness_probe.py", RELEASE)
        self.assertIn("TECH_READY_EXPECT_CONTENT_INGESTION_LOCKED", RELEASE)
        self.assertIn("TECH_READY_EXPECT_VERSION", RELEASE)
        self.assertIn("Upload post-release readiness evidence", RELEASE)
        self.assertIn("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", RELEASE)
        self.assertIn("technical-readiness-results.json", RELEASE)

    def test_release_no_longer_requires_local_vercel_python_build_tooling(self):
        self.assertNotIn("Install uv for local Vercel Python build", RELEASE)
        self.assertNotIn("pip install --disable-pip-version-check --no-cache-dir uv", RELEASE)


if __name__ == "__main__":
    unittest.main()
