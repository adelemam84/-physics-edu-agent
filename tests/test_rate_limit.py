from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.services import rate_limit


class _FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _FakeResult(self.row)


class _Context:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, exc_type, exc, tb):
        return False


def _request(forwarded: str | None = None) -> Request:
    headers = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers,
        "scheme": "https",
        "server": ("test", 443),
        "client": ("10.0.0.1", 1000),
        "query_string": b"",
    })


class RateLimitTests(unittest.TestCase):
    def test_policy_is_environment_configurable(self):
        with patch.dict(
            os.environ,
            {
                "RATE_LIMIT_STUDENT_LOGIN_MAX": "9",
                "RATE_LIMIT_STUDENT_LOGIN_WINDOW_SECONDS": "120",
            },
            clear=False,
        ):
            self.assertEqual(
                rate_limit.policy(
                    "student_login",
                    default_limit=12,
                    default_window_seconds=600,
                ),
                (9, 120),
            )

    def test_request_subject_prefers_forwarded_client_ip(self):
        self.assertEqual(
            rate_limit.request_subject(_request("203.0.113.4, 10.0.0.1")),
            "ip:203.0.113.4",
        )

    def test_hash_never_exposes_subject(self):
        digest = rate_limit.subject_hash("scope", "STUDENT-SECRET-CODE")
        self.assertNotIn("STUDENT-SECRET-CODE", digest)
        self.assertEqual(len(digest), 64)

    def test_limit_exceeded_returns_429_and_retry_after(self):
        con = _FakeConnection({"hits": 6, "retry_after": 44})
        with patch("app.services.rate_limit.connect", return_value=_Context(con)):
            with self.assertRaises(HTTPException) as ctx:
                rate_limit.enforce_rate_limit(
                    scope="test",
                    subject="abc",
                    limit=5,
                    window_seconds=60,
                )
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "44")


if __name__ == "__main__":
    unittest.main()
