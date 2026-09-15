from __future__ import annotations

from pathlib import Path
import unittest


TOOL = Path("tools/technical_readiness_probe.py").read_text(encoding="utf-8")
WORKFLOW = Path(".github/workflows/final-technical-readiness.yml").read_text(encoding="utf-8")


class TechnicalReadinessProbeContractTests(unittest.TestCase):
    def test_gate_covers_health_security_and_anonymous_identity_surfaces(self):
        for path in (
            "/health",
            "/health/ready",
            "/api/research-engine/status",
            "/api/next-release/status",
            "/api/admin/ai-operations/summary",
            "/api/student/session",
        ):
            self.assertIn(path, TOOL)

    def test_gate_preserves_deferred_content_policy(self):
        self.assertIn('"content_ingestion": "deferred"', TOOL)
        self.assertIn('state.startswith("runtime_ready")', TOOL)
        self.assertNotIn("content_release_ready", TOOL)

    def test_gate_checks_baseline_security_headers(self):
        for name in (
            "strict-transport-security",
            "content-security-policy",
            "x-content-type-options",
            "x-frame-options",
            "permissions-policy",
        ):
            self.assertIn(name, TOOL)

    def test_gate_checks_no_store_session_and_readiness_contracts(self):
        self.assertGreaterEqual(TOOL.count('"no-store"'), 2)
        self.assertIn("anonymous admin API expected 401", TOOL)
        self.assertIn("anonymous student session must be unauthenticated", TOOL)

    def test_workflow_is_read_only_and_evidence_backed(self):
        self.assertIn("permissions:\n  contents: read", WORKFLOW)
        self.assertIn("python tools/technical_readiness_probe.py", WORKFLOW)
        self.assertIn("technical-readiness-results.json", WORKFLOW)
        self.assertIn("retention-days: 30", WORKFLOW)
        self.assertNotIn("secrets.", WORKFLOW)

    def test_actions_are_immutably_pinned(self):
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", WORKFLOW)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", WORKFLOW)
        self.assertIn("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
