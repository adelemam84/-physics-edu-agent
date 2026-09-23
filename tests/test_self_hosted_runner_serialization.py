from __future__ import annotations

from pathlib import Path
import unittest


HOSTED_ROUTINE_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/security-audit.yml",
    ".github/workflows/final-technical-readiness.yml",
    ".github/workflows/production-smoke.yml",
)

SELF_HOSTED_FALLBACK_WORKFLOWS = (
    ".github/workflows/execute-edu001-edu003.yml",
    ".github/workflows/self-hosted-production-release.yml",
)

SHARED_GROUP = "group: physics-edu-agent-self-hosted"


class RunnerModeContractTests(unittest.TestCase):
    def test_routine_workflows_use_github_hosted_runners(self):
        for path in HOSTED_ROUTINE_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("runs-on: ubuntu-latest", source, path)
            self.assertNotIn("runs-on: self-hosted", source, path)
            self.assertNotIn(SHARED_GROUP, source, path)

    def test_deferred_content_workflow_remains_locked_on_self_hosted_path(self):
        source = Path(".github/workflows/execute-edu001-edu003.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: self-hosted", source)
        self.assertIn("if: ${{ false }}", source)
        self.assertIn(SHARED_GROUP, source)

    def test_self_hosted_release_remains_serialized_as_manual_fallback(self):
        source = Path(".github/workflows/self-hosted-production-release.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: self-hosted", source)
        self.assertIn(SHARED_GROUP, source)
        self.assertIn("cancel-in-progress: false", source)

    def test_primary_controlled_release_is_already_hosted(self):
        source = Path(".github/workflows/production-release.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-latest", source)
        self.assertIn("group: physics-edu-agent-production", source)


if __name__ == "__main__":
    unittest.main()
