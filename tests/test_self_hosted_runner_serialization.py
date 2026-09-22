from __future__ import annotations

from pathlib import Path
import unittest


SELF_HOSTED_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/execute-edu001-edu003.yml",
    ".github/workflows/security-audit.yml",
    ".github/workflows/final-technical-readiness.yml",
    ".github/workflows/production-smoke.yml",
    ".github/workflows/self-hosted-production-release.yml",
)

SHARED_GROUP = "group: physics-edu-agent-self-hosted"


class SelfHostedRunnerSerializationTests(unittest.TestCase):
    def test_self_hosted_workflows_share_one_non_cancelling_group(self):
        for path in SELF_HOSTED_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertIn("runs-on: self-hosted", source, path)
            self.assertIn(SHARED_GROUP, source, path)
            self.assertIn("cancel-in-progress: false", source, path)

    def test_self_hosted_workflows_do_not_cancel_running_workers(self):
        for path in SELF_HOSTED_WORKFLOWS:
            source = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("cancel-in-progress: true", source, path)


if __name__ == "__main__":
    unittest.main()
