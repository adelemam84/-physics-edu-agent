from __future__ import annotations

import ast
from pathlib import Path
import unittest


SCRIPT = Path("tools/production_smoke.py")
WORKFLOW = Path(".github/workflows/production-smoke.yml")


class ContinuousProductionSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.script)

    def test_monitor_is_scheduled_manual_and_self_validating_on_main(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("branches: [main]", self.workflow)
        self.assertIn('cron: "17 */6 * * *"', self.workflow)

    def test_monitor_has_read_only_repo_permissions(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)

    def test_probe_only_uses_get_requests(self):
        self.assertIn('method="GET"', self.script)
        self.assertNotIn('method="POST"', self.script)
        self.assertNotIn('method="PUT"', self.script)
        self.assertNotIn('method="DELETE"', self.script)

    def test_probe_covers_public_runtime_contracts(self):
        for path in (
            "/health",
            "/health/ready",
            "/api/research-engine/status",
            "/api/next-release/status",
            "/api/student/session",
            "/api/admin/feature-status",
            "/api/student/exams/resolve/SMOKE-LEGACY-CODE",
            "/student",
            "/admin/dashboard",
            "/student/quiz/1",
            "/student/results/1",
            "/student/study-queue",
            "/student/command-center",
        ):
            self.assertIn(path, self.script)

    def test_probe_attests_anonymous_student_session_and_read_only_ui_shells(self):
        for token in (
            'data.get("authenticated") is False',
            "id=studentLoginForm",
            "flushPendingSaves",
            "submitInFlight",
            "weakBtn.disabled=true",
            "statusLabels=",
            '"/api/admin/feature-status"',
            "status == 401",
            '"/api/student/exams/resolve/SMOKE-LEGACY-CODE"',
            "status == 410",
            "دخول الإدارة",
            "student_shell_contracts",
        ):
            self.assertIn(token, self.script)

    def test_probe_supports_json_and_html_contracts_without_mutations(self):
        self.assertIn('"json"', self.script)
        self.assertIn('"text"', self.script)
        self.assertIn('"status"', self.script)
        self.assertIn('mode == "status"', self.script)
        self.assertIn("except HTTPError as exc:", self.script)
        self.assertNotIn('method="POST"', self.script)
        self.assertNotIn('method="PUT"', self.script)
        self.assertNotIn('method="PATCH"', self.script)
        self.assertNotIn('method="DELETE"', self.script)

    def test_probe_has_bounded_retries_and_timeout(self):
        self.assertIn("SMOKE_TIMEOUT_SECONDS", self.script)
        self.assertIn("SMOKE_ATTEMPTS", self.script)
        self.assertIn("timeout=TIMEOUT_SECONDS", self.script)

    def test_probe_attests_runtime_version_and_content_lock(self):
        self.assertIn("SMOKE_EXPECT_VERSION", self.script)
        self.assertIn('data.get("content_ingestion") == "locked"', self.script)
        self.assertIn("Resolve expected production version", self.workflow)
        self.assertIn("from app.version import APPLICATION_VERSION", self.workflow)

    def test_evidence_is_always_uploaded(self):
        self.assertIn("if: always()", self.workflow)
        self.assertIn("production-smoke-results.json", self.workflow)


    def test_probe_attests_negative_security_contracts_without_writes(self):
        for token in (
            '"/api/admin/feature-status"',
            "lambda status: status == 401",
            '"/api/student/exams/resolve/SMOKE-LEGACY-CODE"',
            "lambda status: status == 410",
            '"/admin/dashboard"',
            '"دخول الإدارة"',
            '"HttpOnly"',
        ):
            self.assertIn(token, self.script)
        self.assertNotIn('method="POST"', self.script)
        self.assertNotIn('method="PATCH"', self.script)
        self.assertNotIn('method="DELETE"', self.script)


if __name__ == "__main__":
    unittest.main()
