from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
SECURITY = (ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github/workflows/self-hosted-production-release.yml").read_text(encoding="utf-8")


class SelfHostedReleaseWorkflowTests(unittest.TestCase):
    def test_release_marker_only_pushes_do_not_relaunch_ci_or_security(self):
        for workflow in (CI, SECURITY):
            self.assertIn("paths-ignore:", workflow)
            self.assertIn('".release/**"', workflow)

    def test_release_keeps_self_hosted_runner_and_explicit_dependencies(self):
        self.assertIn("runs-on: self-hosted", RELEASE)
        self.assertIn("Install runtime dependencies", RELEASE)
        self.assertIn("python -m pip install --disable-pip-version-check -r requirements.txt", RELEASE)

    def test_release_no_longer_requires_local_vercel_python_build_tooling(self):
        self.assertNotIn("Install uv for local Vercel Python build", RELEASE)
        self.assertNotIn("pip install --disable-pip-version-check --no-cache-dir uv", RELEASE)


if __name__ == "__main__":
    unittest.main()
