from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.exam_engine import resolve_exam_code_legacy
from app.student_security import set_student_session_cookie
from app.student_session_api import StudentSessionLogin, create_student_session


def request(
    *,
    method: str = "POST",
    path: str = "/api/student/session",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    base_headers = [(b"host", b"physics-edu-agent.vercel.app")]
    base_headers.extend(headers or [])
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": base_headers,
            "scheme": "https",
            "server": ("physics-edu-agent.vercel.app", 443),
            "client": ("127.0.0.1", 12345),
            "query_string": b"",
        }
    )


class StudentSessionAbuseHardeningTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "STUDENT_SESSION_SECRET": "student-session-hardening-test-secret",
                "VERCEL_ENV": "production",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_production_student_cookie_is_http_only_secure_and_strict(self):
        response = Response()
        set_student_session_cookie(response, student_id=17)
        cookie = response.headers.get("set-cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)

    def test_cross_site_browser_login_is_blocked_before_rate_limit_or_database(self):
        req = request(
            headers=[
                (b"sec-fetch-site", b"cross-site"),
                (b"origin", b"https://evil.example"),
            ]
        )
        with patch("app.student_session_api.enforce_request_policy") as rate, patch(
            "app.student_session_api.connect"
        ) as connect:
            with self.assertRaises(HTTPException) as ctx:
                create_student_session(
                    StudentSessionLogin(student_code="STUDENT-1"),
                    Response(),
                    req,
                )
        self.assertEqual(ctx.exception.status_code, 403)
        rate.assert_not_called()
        connect.assert_not_called()

    def test_no_origin_api_client_remains_supported_and_rate_limited(self):
        req = request()
        con = MagicMock()
        con.execute.return_value.fetchone.return_value = {"id": 17, "name": "طالب"}
        cm = MagicMock()
        cm.__enter__.return_value = con
        cm.__exit__.return_value = False
        response = Response()
        with patch(
            "app.student_session_api.enforce_request_policy"
        ) as rate, patch("app.student_session_api.connect", return_value=cm):
            result = create_student_session(
                StudentSessionLogin(student_code="STUDENT-1"),
                response,
                req,
            )
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["student"]["id"], 17)
        rate.assert_called_once()
        self.assertIn("SameSite=strict", response.headers.get("set-cookie", ""))

    def test_deprecated_exam_code_get_is_gone_semantically(self):
        req = request(method="GET", path="/api/student/exams/resolve/ABC234")
        with patch("app.exam_engine._resolve_exam_code") as resolver:
            with self.assertRaises(HTTPException) as ctx:
                resolve_exam_code_legacy("ABC234", req)
        self.assertEqual(ctx.exception.status_code, 410)
        resolver.assert_not_called()
        self.assertIn("POST /api/student/exams/resolve", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
