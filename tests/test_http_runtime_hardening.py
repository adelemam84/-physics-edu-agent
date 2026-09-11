from __future__ import annotations

import asyncio
import os
import re
import unittest
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import Response

from app.main import (
    _sensitive_cache_path,
    add_security_headers,
)


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers or [],
        "scheme": "https",
        "server": ("example.test", 443),
        "client": ("127.0.0.1", 12345),
    })


async def _response(path: str, *, headers=None) -> Response:
    async def call_next(request: Request):
        return Response("ok", media_type="text/plain")
    return await add_security_headers(_request(path, headers=headers), call_next)


class HttpRuntimeHardeningTests(unittest.TestCase):
    def test_sensitive_path_contract_covers_admin_and_student_surfaces(self):
        for path in (
            "/admin",
            "/admin/dashboard",
            "/api/admin/session",
            "/student",
            "/student/quiz/10",
            "/api/student/session",
            "/api/practice/questions",
            "/api/attempts/submit",
            "/api/integrations/canva/oauth/callback",
        ):
            self.assertTrue(_sensitive_cache_path(path), path)
        self.assertFalse(_sensitive_cache_path("/health"))
        self.assertFalse(_sensitive_cache_path("/openapi.json"))

    def test_sensitive_responses_are_no_store(self):
        response = asyncio.run(_response("/api/student/session"))
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_public_health_does_not_get_global_no_store(self):
        response = asyncio.run(_response("/health"))
        self.assertNotIn("cache-control", response.headers)
        self.assertNotIn("pragma", response.headers)

    def test_request_id_is_server_generated_and_not_reflected(self):
        response = asyncio.run(_response(
            "/health",
            headers=[(b"x-request-id", b"attacker-controlled")],
        ))
        request_id = response.headers["x-request-id"]
        self.assertNotEqual(request_id, "attacker-controlled")
        self.assertRegex(request_id, re.compile(r"^[0-9a-f]{32}$"))

    def test_security_headers_are_present(self):
        response = asyncio.run(_response("/health"))
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "same-origin")
        self.assertEqual(response.headers["x-permitted-cross-domain-policies"], "none")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_hsts_is_production_only(self):
        with patch.dict(os.environ, {"VERCEL_ENV": "preview"}, clear=False):
            response = asyncio.run(_response("/health"))
            self.assertNotIn("strict-transport-security", response.headers)
        with patch.dict(os.environ, {"VERCEL_ENV": "production"}, clear=False):
            response = asyncio.run(_response("/health"))
            self.assertEqual(
                response.headers["strict-transport-security"],
                "max-age=31536000; includeSubDomains",
            )


if __name__ == "__main__":
    unittest.main()
