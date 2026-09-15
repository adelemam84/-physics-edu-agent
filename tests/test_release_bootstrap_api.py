from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app import release_bootstrap_api


class ReleaseBootstrapApiTests(unittest.TestCase):
    def _request(self, token: str = ""):
        request = MagicMock()
        request.headers = {"x-release-bootstrap-token": token}
        return request

    def test_route_is_inert_without_ephemeral_token(self):
        with patch.dict(
            os.environ,
            {
                "RELEASE_BOOTSTRAP_TOKEN": "",
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as ctx:
                release_bootstrap_api._authorize_release_bootstrap(self._request())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_wrong_token_is_rejected(self):
        with patch.dict(
            os.environ,
            {
                "RELEASE_BOOTSTRAP_TOKEN": "expected-token",
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as ctx:
                release_bootstrap_api._authorize_release_bootstrap(
                    self._request("wrong-token")
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_bootstrap_is_production_main_only(self):
        with patch.dict(
            os.environ,
            {
                "RELEASE_BOOTSTRAP_TOKEN": "token",
                "VERCEL_ENV": "preview",
                "RELEASE_GIT_REF": "main",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as ctx:
                release_bootstrap_api._authorize_release_bootstrap(
                    self._request("token")
                )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_valid_ephemeral_token_applies_bootstrap_once(self):
        with patch.dict(
            os.environ,
            {
                "RELEASE_BOOTSTRAP_TOKEN": "token",
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
                "RELEASE_GIT_SHA": "1234567890abcdef",
            },
            clear=False,
        ), patch.object(
            release_bootstrap_api, "apply_startup_bootstrap"
        ) as bootstrap:
            data = release_bootstrap_api.release_bootstrap(self._request("token"))

        bootstrap.assert_called_once_with()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["runtime_bootstrap"], "applied")
        self.assertEqual(data["release_sha"], "1234567890ab")


if __name__ == "__main__":
    unittest.main()
