from __future__ import annotations

from pathlib import Path
import unittest


class OperationalReadinessContractTests(unittest.TestCase):
    def test_dependency_security_audit_is_recurring_and_manual(self):
        text = Path('.github/workflows/security-audit.yml').read_text(encoding='utf-8')
        self.assertIn('schedule:', text)
        self.assertIn('cron: "29 3 * * 1"', text)
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('pip-audit==2.10.1', text)
        self.assertIn('group: physics-edu-agent-self-hosted', text)
        self.assertIn('cancel-in-progress: false', text)

    def test_runbook_separates_app_rollback_from_database_recovery(self):
        text = Path('OPERATIONS_RUNBOOK.md').read_text(encoding='utf-8')
        self.assertIn('Application rollback changes Vercel production traffic only', text)
        self.assertIn('Database recovery is deliberately separate', text)
        self.assertIn('Never restore directly over the production branch', text)
        self.assertIn('snapshot limit was reached', text)
        self.assertIn('backup scheduling is not enabled', text)

    def test_runbook_preserves_content_ingestion_boundary(self):
        text = Path('OPERATIONS_RUNBOOK.md').read_text(encoding='utf-8')
        self.assertIn('content ingestion remains a separate controlled phase', text)


if __name__ == '__main__':
    unittest.main()
