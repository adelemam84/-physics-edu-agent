from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.student_security import (
    COOKIE_NAME,
    make_student_session_token,
    parse_student_session_token,
    resolve_student_code,
)


def request_with_cookie(token: str | None = None, method: str = "GET") -> Request:
    headers = []
    if token:
        headers.append((b"cookie", f"{COOKIE_NAME}={token}".encode()))
    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "headers": headers,
        "scheme": "https",
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    }
    return Request(scope)


class StudentSessionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "STUDENT_SESSION_SECRET": "unit-test-student-session-secret",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_token_round_trip(self):
        token = make_student_session_token(17, "STU-017")
        session = parse_student_session_token(token)
        self.assertIsNotNone(session)
        self.assertEqual(session.student_id, 17)
        self.assertEqual(session.external_code, "STU-017")

    def test_tampered_token_is_rejected(self):
        token = make_student_session_token(17, "STU-017")
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        self.assertIsNone(parse_student_session_token(tampered))

    def test_cookie_session_is_the_only_student_identity_source(self):
        token = make_student_session_token(17, "STU-017")
        request = request_with_cookie(token)
        self.assertEqual(resolve_student_code(request), "STU-017")

    def test_missing_session_is_rejected(self):
        request = request_with_cookie()
        with self.assertRaises(HTTPException) as ctx:
            resolve_student_code(request)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_token_expiry_is_enforced(self):
        token = make_student_session_token(17, "STU-017")
        with patch("app.student_security.time.time", return_value=time.time() + 13 * 60 * 60):
            self.assertIsNone(parse_student_session_token(token))


if __name__ == "__main__":
    unittest.main()
