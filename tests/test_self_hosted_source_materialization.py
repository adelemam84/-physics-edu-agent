from __future__ import annotations

import unittest
from pathlib import Path


HOSTED_CHECK_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/security-audit.yml",
    ".github/workflows/final-technical-readiness.yml",
    ".github/workflows/production-smoke.yml",
)


class HostedCheckRunnerTests(unittest.TestCase):
    def test_non_release_checks_use_isolated_hosted_runner(self):
        for path in HOSTED_CHECK_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("runs-on: ubuntu-latest", source)
            self.assertNotIn("runs-on: self-hosted", source)

    def test_standard_checkout_remains_pinned_on_hosted_runner(self):
        for path in HOSTED_CHECK_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", source)

    def test_production_release_stays_separate_from_hosted_check_policy(self):
        source = Path(".github/workflows/self-hosted-production-release.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: self-hosted", source)
        self.assertIn("Materialize exact release commit archive", source)


if __name__ == "__main__":
    unittest.main()
