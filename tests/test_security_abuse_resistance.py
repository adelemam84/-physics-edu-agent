from __future__ import annotations

import hashlib
import inspect
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app import admin_auth, security_hardening, student_lesson, student_quiz, whatsapp_webhook
from app.services import rate_limit


def _request(*, forwarded: str | None = None, client: str = "10.0.0.1") -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers,
        "scheme": "https",
        "server": ("test", 443),
        "client": (client, 1234),
        "query_string": b"",
    })


def _streaming_request(body: bytes, *, content_length: int | None = None) -> Request:
    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http",
        "method": "POST",
        "path": "/webhooks/whatsapp",
        "headers": headers,
        "scheme": "https",
        "server": ("test", 443),
        "client": ("10.0.0.1", 1234),
        "query_string": b"",
    }, receive)


class SecurityAbuseResistanceTests(unittest.TestCase):
    def test_rate_limit_subject_hash_is_keyed_and_secret_dependent(self):
        with patch.dict(
            os.environ,
            {
                "RATE_LIMIT_HASH_SECRET": "alpha-secret",
                "STUDENT_SESSION_SECRET": "",
                "ADMIN_SESSION_SECRET": "",
                "ADMIN_API_KEY": "",
            },
            clear=False,
        ):
            first = rate_limit.subject_hash("student_login", "STUDENT-123")
        with patch.dict(os.environ, {"RATE_LIMIT_HASH_SECRET": "beta-secret"}, clear=False):
            second = rate_limit.subject_hash("student_login", "STUDENT-123")

        plain = hashlib.sha256(b"student_login:STUDENT-123").hexdigest()
        self.assertNotEqual(first, plain)
        self.assertNotEqual(first, second)
        self.assertNotIn("STUDENT-123", first)

    def test_invalid_forwarded_ip_cannot_create_arbitrary_bucket_key(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            self.assertEqual(
                rate_limit.request_subject(_request(forwarded="attacker-controlled-value")),
                "ip:10.0.0.1",
            )

    def test_forwarded_ip_is_normalized_on_vercel(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            self.assertEqual(
                rate_limit.request_subject(_request(forwarded="2001:0db8::1")),
                "ip:2001:db8::1",
            )

    def test_untrusted_proxy_header_is_ignored_outside_managed_edge(self):
        with patch.dict(
            os.environ,
            {"VERCEL": "", "VERCEL_ENV": "", "TRUST_PROXY_HEADERS": ""},
            clear=False,
        ):
            self.assertEqual(
                rate_limit.request_subject(
                    _request(forwarded="203.0.113.99", client="198.51.100.20")
                ),
                "ip:198.51.100.20",
            )

    def test_session_mutation_policy_covers_high_write_student_routes(self):
        expected = {
            ("POST", "/api/student/quizzes/12/start"): "student_quiz_start",
            ("PUT", "/api/student/attempts/99/answer"): "student_answer_save",
            ("POST", "/api/student/quizzes/12/submit"): "student_quiz_submit",
            ("POST", "/api/student/lessons/7/diagnostic"): "student_diagnostic_submit",
        }
        for (method, path), name in expected.items():
            policy = security_hardening.student_mutation_policy(path, method)
            self.assertIsNotNone(policy)
            self.assertEqual(policy[0], name)

    def test_session_mutation_middleware_guards_both_admin_and_student_cookies(self):
        source = inspect.getsource(security_hardening.enforce_browser_session_mutation_guards)
        self.assertIn("ADMIN_COOKIE_NAME", source)
        self.assertIn("STUDENT_COOKIE_NAME", source)
        self.assertIn("same_origin_request", source)
        self.assertIn("enforce_subject_policy", source)

    def test_admin_login_payload_is_bounded(self):
        with self.assertRaises(ValidationError):
            admin_auth.LoginIn(key="x" * 513)

    def test_student_answer_payloads_are_bounded(self):
        with self.assertRaises(ValidationError):
            student_quiz.SaveAnswer(question_id=1, answer="x" * 5001)
        with self.assertRaises(ValidationError):
            student_quiz.SubmitAttempt(
                answers=[
                    student_quiz.AnswerIn(question_id=i + 1, answer="ok")
                    for i in range(201)
                ]
            )
        with self.assertRaises(ValidationError):
            student_lesson.DiagnosticSubmit(
                answers=[
                    student_lesson.DiagnosticAnswer(question_id=i + 1, answer="ok")
                    for i in range(101)
                ]
            )

    def test_whatsapp_webhook_uses_streaming_size_guard_before_json_decode(self):
        source = inspect.getsource(whatsapp_webhook.whatsapp_webhook)
        self.assertIn("_read_limited_body", source)
        self.assertIn('media_type != "application/json"', source)


class WebhookBodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_content_length_over_limit_is_rejected(self):
        with patch.object(whatsapp_webhook, "MAX_WEBHOOK_BYTES", 16):
            with self.assertRaises(HTTPException) as ctx:
                await whatsapp_webhook._read_limited_body(
                    _streaming_request(b"{}", content_length=17)
                )
        self.assertEqual(ctx.exception.status_code, 413)

    async def test_stream_over_limit_is_rejected_without_unbounded_buffer(self):
        with patch.object(whatsapp_webhook, "MAX_WEBHOOK_BYTES", 8):
            with self.assertRaises(HTTPException) as ctx:
                await whatsapp_webhook._read_limited_body(
                    _streaming_request(b"0123456789")
                )
        self.assertEqual(ctx.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
