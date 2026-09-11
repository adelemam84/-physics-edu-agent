from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

from app import admin_auth, operations_readiness, student_session_api


class ReleaseSecurityContractTests(unittest.TestCase):
    def test_admin_login_is_rate_limited(self):
        source = inspect.getsource(admin_auth.admin_login)
        self.assertIn("enforce_request_policy", source)
        self.assertIn('name="admin_login"', source)

    def test_session_identity_responses_are_never_cacheable(self):
        for fn in (
            admin_auth.admin_session_status,
            admin_auth.admin_login,
            admin_auth.admin_logout,
            student_session_api.create_student_session,
            student_session_api.read_student_session,
            student_session_api.delete_student_session,
        ):
            self.assertIn('Cache-Control"] = "no-store"', inspect.getsource(fn), fn.__name__)

    def test_controlled_launch_requires_dedicated_student_session_secret(self):
        with patch.dict(
            os.environ,
            {
                "STUDENT_SESSION_SECRET": "",
                "ADMIN_SESSION_SECRET": "admin-only",
                "ADMIN_API_KEY": "admin-key",
                "DATABASE_URL": "postgresql://example",
            },
            clear=False,
        ):
            self.assertFalse(operations_readiness._student_session_configured())
        with patch.dict(
            os.environ,
            {"STUDENT_SESSION_SECRET": "dedicated-student-secret"},
            clear=False,
        ):
            self.assertTrue(operations_readiness._student_session_configured())


if __name__ == "__main__":
    unittest.main()
