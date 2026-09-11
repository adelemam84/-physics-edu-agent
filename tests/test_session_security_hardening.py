from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request

from app import admin_auth, operations_readiness, student_session_api
from app.security import (
    COOKIE_NAME as ADMIN_COOKIE,
    admin_session_secret_configured,
    admin_session_secret_source,
    make_admin_session_token,
    require_admin,
)
from app.services.runtime_identity import runtime_identity
from app.student_security import (
    COOKIE_NAME as STUDENT_COOKIE,
    make_student_session_token,
    set_student_session_cookie,
)


def request(
    *,
    method: str,
    host: str = "example.com",
    origin: str | None = None,
    cookie_name: str | None = None,
    cookie_value: str | None = None,
) -> Request:
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    if cookie_name and cookie_value:
        headers.append(
            (b"cookie", f"{cookie_name}={cookie_value}".encode())
        )
    return Request({
        "type": "http",
        "method": method,
        "path": "/",
        "headers": headers,
        "scheme": "https",
        "server": (host, 443),
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    })


class SessionSecurityHardeningTests(unittest.TestCase):
    def test_admin_secret_posture_distinguishes_dedicated_and_fallback(self):
        with patch.dict(
            os.environ,
            {
                "ADMIN_API_KEY": "admin-key",
                "ADMIN_SESSION_SECRET": "",
            },
            clear=False,
        ):
            self.assertFalse(admin_session_secret_configured())
            self.assertEqual(
                admin_session_secret_source(),
                "admin_api_key_fallback",
            )

        with patch.dict(
            os.environ,
            {
                "ADMIN_API_KEY": "admin-key",
                "ADMIN_SESSION_SECRET": "dedicated-session-secret",
            },
            clear=False,
        ):
            self.assertTrue(admin_session_secret_configured())
            self.assertEqual(admin_session_secret_source(), "dedicated")

    def test_legacy_admin_session_fallback_remains_compatible(self):
        with patch.dict(
            os.environ,
            {
                "ADMIN_API_KEY": "admin-key",
                "ADMIN_SESSION_SECRET": "",
            },
            clear=False,
        ):
            token = make_admin_session_token()
            req = request(
                method="POST",
                origin="https://example.com",
                cookie_name=ADMIN_COOKIE,
                cookie_value=token,
            )
            self.assertTrue(require_admin(req, x_admin_key=None))

    def test_admin_cookie_mutation_rejects_cross_origin(self):
        with patch.dict(
            os.environ,
            {
                "ADMIN_API_KEY": "admin-key",
                "ADMIN_SESSION_SECRET": "dedicated",
            },
            clear=False,
        ):
            token = make_admin_session_token()
            req = request(
                method="POST",
                origin="https://evil.example",
                cookie_name=ADMIN_COOKIE,
                cookie_value=token,
            )
            with self.assertRaises(HTTPException) as ctx:
                require_admin(req, x_admin_key=None)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_api_key_remains_valid_for_programmatic_cross_origin_mutation(self):
        with patch.dict(
            os.environ,
            {"ADMIN_API_KEY": "admin-key"},
            clear=False,
        ):
            req = request(
                method="POST",
                origin="https://automation.example",
            )
            self.assertTrue(require_admin(req, x_admin_key="admin-key"))

    def test_admin_logout_route_requires_admin_dependency(self):
        source = inspect.getsource(admin_auth)
        self.assertIn(
            '@app.post("/api/admin/logout", dependencies=[Depends(require_admin)])',
            source,
        )

    def test_admin_logout_deletes_cookie_with_strict_secure_attributes(self):
        response = Response()
        admin_auth.admin_logout(response)
        header = response.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", header)
        self.assertIn("secure", header)
        self.assertIn("samesite=strict", header)
        self.assertIn("max-age=0", header)

    def test_student_cookie_is_strict_same_site(self):
        response = Response()
        with patch.dict(
            os.environ,
            {"STUDENT_SESSION_SECRET": "student-secret"},
            clear=False,
        ):
            set_student_session_cookie(response, student_id=17)
        header = response.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", header)
        self.assertIn("samesite=strict", header)

    def test_student_logout_rejects_cross_origin_when_session_exists(self):
        with patch.dict(
            os.environ,
            {"STUDENT_SESSION_SECRET": "student-secret"},
            clear=False,
        ):
            token = make_student_session_token(17)
            req = request(
                method="DELETE",
                origin="https://evil.example",
                cookie_name=STUDENT_COOKIE,
                cookie_value=token,
            )
            with self.assertRaises(HTTPException) as ctx:
                student_session_api.delete_student_session(
                    Response(),
                    req,
                )
            self.assertEqual(ctx.exception.status_code, 403)

    def test_student_logout_allows_same_origin(self):
        with patch.dict(
            os.environ,
            {"STUDENT_SESSION_SECRET": "student-secret"},
            clear=False,
        ):
            token = make_student_session_token(17)
            req = request(
                method="DELETE",
                origin="https://example.com",
                cookie_name=STUDENT_COOKIE,
                cookie_value=token,
            )
            response = Response()
            data = student_session_api.delete_student_session(
                response,
                req,
            )
        self.assertFalse(data["authenticated"])
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())

    def test_runtime_identity_reports_admin_session_presence_only(self):
        identity = runtime_identity({
            "ADMIN_API_KEY": "admin-key",
            "ADMIN_SESSION_SECRET": "do-not-expose",
        })
        self.assertTrue(identity["config_state"]["admin_access"])
        self.assertTrue(identity["config_state"]["admin_session"])
        self.assertNotIn("do-not-expose", repr(identity))

    def test_admin_session_secret_is_optional_hardening_not_technical_blocker(self):
        source = inspect.getsource(operations_readiness.build_operations_readiness)
        technical_prefix = source.split("    optional = [", 1)[0]
        optional_suffix = source.split("    optional = [", 1)[1]
        self.assertNotIn('"id": "admin_session_secret"', technical_prefix)
        self.assertIn('"id": "admin_session_secret"', optional_suffix)


if __name__ == "__main__":
    unittest.main()
