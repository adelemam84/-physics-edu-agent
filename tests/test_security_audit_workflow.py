from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/security-audit.yml")


class SecurityAuditWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_audit_runs_for_pull_requests_and_main(self):
        self.assertIn("pull_request:", self.text)
        self.assertIn("branches: [main]", self.text)

    def test_pip_audit_is_pinned_and_checks_runtime_requirements(self):
        self.assertIn('"pip-audit==2.10.1"', self.text)
        self.assertIn("python -m pip_audit -r requirements.txt", self.text)

    def test_workflow_has_read_only_repository_permissions(self):
        self.assertIn("permissions:\n  contents: read", self.text)


if __name__ == "__main__":
    unittest.main()
