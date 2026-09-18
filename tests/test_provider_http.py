from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from app.services import provider_http


class _Client:
    queue = []
    calls = 0
    instances = 0

    def __init__(self, timeout):
        type(self).instances += 1
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(self, method, url, **kwargs):
        type(self).calls += 1
        item = type(self).queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(status: int, *, retry_after: str | None = None) -> httpx.Response:
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return httpx.Response(status, headers=headers, request=httpx.Request("POST", "https://provider.test"))


class ProviderHttpTests(unittest.TestCase):
    def setUp(self):
        _Client.queue = []
        _Client.calls = 0
        _Client.instances = 0

    def test_transient_status_retries_same_request_until_success(self):
        _Client.queue = [_response(503), _response(429), _response(200)]
        sleeps = []
        with patch.object(provider_http.httpx, "Client", _Client), patch.dict(
            os.environ,
            {
                "AI_PROVIDER_RETRY_ATTEMPTS": "3",
                "AI_PROVIDER_RETRY_BASE_DELAY_MS": "10",
                "AI_PROVIDER_RETRY_MAX_DELAY_MS": "20",
            },
            clear=False,
        ):
            response = provider_http.request_with_retries(
                "POST",
                "https://provider.test",
                timeout=5,
                json={"safe": True},
                sleep=sleeps.append,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_Client.calls, 3)
        self.assertEqual(_Client.instances, 1)
        self.assertEqual(provider_http.provider_attempts(response), 3)
        self.assertEqual(sleeps, [0.01, 0.02])

    def test_non_retryable_4xx_returns_immediately(self):
        _Client.queue = [_response(400), _response(200)]
        with patch.object(provider_http.httpx, "Client", _Client):
            response = provider_http.request_with_retries(
                "POST",
                "https://provider.test",
                timeout=5,
                sleep=lambda _: None,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(_Client.calls, 1)

    def test_transport_error_is_retried(self):
        request = httpx.Request("POST", "https://provider.test")
        _Client.queue = [httpx.ConnectError("temporary", request=request), _response(200)]
        with patch.object(provider_http.httpx, "Client", _Client):
            response = provider_http.request_with_retries(
                "POST",
                "https://provider.test",
                timeout=5,
                sleep=lambda _: None,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_Client.calls, 2)

    def test_retry_after_is_bounded_by_operator_maximum(self):
        _Client.queue = [_response(429, retry_after="30"), _response(200)]
        sleeps = []
        with patch.object(provider_http.httpx, "Client", _Client), patch.dict(
            os.environ,
            {
                "AI_PROVIDER_RETRY_ATTEMPTS": "2",
                "AI_PROVIDER_RETRY_MAX_DELAY_MS": "1200",
            },
            clear=False,
        ):
            provider_http.request_with_retries(
                "POST",
                "https://provider.test",
                timeout=5,
                sleep=sleeps.append,
            )
        self.assertEqual(sleeps, [1.2])

    def test_mutating_provider_request_can_disable_replay(self):
        _Client.queue = [_response(503), _response(200)]
        with patch.object(provider_http.httpx, "Client", _Client):
            response = provider_http.request_with_retries(
                "POST",
                "https://provider.test",
                timeout=5,
                retry=False,
                sleep=lambda _: None,
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(_Client.calls, 1)

    def test_policy_is_bounded(self):
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER_RETRY_ATTEMPTS": "999",
                "AI_PROVIDER_RETRY_BASE_DELAY_MS": "-4",
                "AI_PROVIDER_RETRY_MAX_DELAY_MS": "999999",
            },
            clear=False,
        ):
            policy = provider_http.retry_policy()
        self.assertEqual(policy.attempts, 5)
        self.assertEqual(policy.base_delay_ms, 0)
        self.assertEqual(policy.max_delay_ms, 10000)


if __name__ == "__main__":
    unittest.main()
