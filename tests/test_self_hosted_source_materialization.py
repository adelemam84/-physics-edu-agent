from __future__ import annotations

import unittest
from pathlib import Path


SELF_HOSTED_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/security-audit.yml",
    ".github/workflows/final-technical-readiness.yml",
    ".github/workflows/production-smoke.yml",
)


class SelfHostedSourceMaterializationTests(unittest.TestCase):
    def test_critical_self_hosted_workflows_do_not_use_actions_checkout(self):
        for path in SELF_HOSTED_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("runs-on: self-hosted", source)
            self.assertNotIn("actions/checkout@", source)

    def test_archive_fetch_is_bounded_authenticated_and_exact_sha(self):
        for path in SELF_HOSTED_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("/zipball/$env:SOURCE_SHA", source)
            self.assertIn("Authorization: Bearer $env:SOURCE_TOKEN", source)
            self.assertIn("--retry 3", source)
            self.assertIn("--connect-timeout 15 --max-time 120", source)
            self.assertIn("SOURCE_SHA: ${{ github.sha }}", source)
            self.assertIn("Workflow archive is missing requirements.txt", source)
            self.assertIn("Workflow archive is missing index.py", source)


if __name__ == "__main__":
    unittest.main()
