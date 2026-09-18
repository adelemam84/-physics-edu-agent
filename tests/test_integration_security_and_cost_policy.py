from __future__ import annotations

import inspect
import unittest
from fastapi import HTTPException

from app import external_creative_integrations as integrations
from app import lesson_studio_integrations_ui as integrations_ui


class IntegrationSecurityAndCostTests(unittest.TestCase):
    def test_integrations_admin_page_is_protected(self):
        source = inspect.getsource(integrations_ui)
        self.assertIn(
            "dependencies=[Depends(require_admin)]",
            source,
        )

    def test_enterprise_notebook_is_disabled_by_free_only_policy(self):
        original = integrations.AI_FREE_ONLY
        integrations.AI_FREE_ONLY = True
        try:
            status = integrations.integration_status()["gemini_notebook_enterprise"]
        finally:
            integrations.AI_FREE_ONLY = original
        self.assertFalse(status["configured"])
        self.assertTrue(status["blocked_by_free_only_policy"])
        self.assertEqual(status["mode"], "disabled_by_free_only_policy")

    def test_enterprise_notebook_execution_is_blocked_in_free_only_mode(self):
        original = integrations.AI_FREE_ONLY
        integrations.AI_FREE_ONLY = True
        try:
            with self.assertRaises(HTTPException) as ctx:
                integrations.create_gemini_notebook("test-job")
        finally:
            integrations.AI_FREE_ONLY = original
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
