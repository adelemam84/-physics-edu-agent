from __future__ import annotations

import unittest

from fastapi.routing import APIRoute

from app.security import require_admin
from index import app


class AdminApiProtectionContractTests(unittest.TestCase):
    def test_every_admin_api_except_auth_bootstrap_requires_admin_dependency(self):
        public_auth = {
            "/api/admin/session",
            "/api/admin/login",
            "/api/admin/logout",
        }
        missing = []
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            if not route.path.startswith("/api/admin/") or route.path in public_auth:
                continue
            dependency_calls = {dep.call for dep in route.dependant.dependencies}
            if require_admin not in dependency_calls:
                missing.append((route.path, sorted(route.methods or [])))
        self.assertFalse(
            missing,
            "Admin API routes missing require_admin: " + repr(missing),
        )


if __name__ == "__main__":
    unittest.main()
