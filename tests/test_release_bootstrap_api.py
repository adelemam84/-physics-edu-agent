from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app import release_bootstrap_api


class ReleaseBootstrapApiTests(unittest.TestCase):
    def _request(self, token: str):
        request = MagicMock()
        request.headers.get.return_value = token
        return request

    def test_authenticated_production_main_stage_runs_bootstrap(self):
        with patch.dict(
            os.environ,
            {
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
                "RELEASE_GIT_SHA": "abc123",
                "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
            },
            clear=False,
        ), patch.object(
            release_bootstrap_api, "apply_startup_bootstrap"
        ) as bootstrap:
            result = release_bootstrap_api.release_bootstrap(
                self._request("temporary-release-token")
            )

        bootstrap.assert_called_once_with()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["runtime_bootstrap"], "applied")
        self.assertEqual(result["release_git_sha"], "abc123")

    def test_missing_or_wrong_token_is_hidden(self):
        for supplied in ("", "wrong-token"):
            with self.subTest(supplied=supplied), patch.dict(
                os.environ,
                {
                    "VERCEL_ENV": "production",
                    "RELEASE_GIT_REF": "main",
                    "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
                },
                clear=False,
            ), patch.object(
                release_bootstrap_api, "apply_startup_bootstrap"
            ) as bootstrap:
                with self.assertRaises(HTTPException) as error:
                    release_bootstrap_api.release_bootstrap(
                        self._request(supplied)
                    )

                self.assertEqual(error.exception.status_code, 404)
                bootstrap.assert_not_called()

    def test_endpoint_is_hidden_without_ephemeral_token(self):
        with patch.dict(
            os.environ,
            {
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
                "RELEASE_BOOTSTRAP_TOKEN": "",
            },
            clear=False,
        ), patch.object(
            release_bootstrap_api, "apply_startup_bootstrap"
        ) as bootstrap:
            with self.assertRaises(HTTPException) as error:
                release_bootstrap_api.release_bootstrap(
                    self._request("anything")
                )

        self.assertEqual(error.exception.status_code, 404)
        bootstrap.assert_not_called()

    def test_endpoint_is_hidden_outside_production_main(self):
        cases = (
            {"VERCEL_ENV": "preview", "RELEASE_GIT_REF": "main"},
            {"VERCEL_ENV": "production", "RELEASE_GIT_REF": "feature/test"},
        )
        for env in cases:
            with self.subTest(env=env), patch.dict(
                os.environ,
                {
                    **env,
                    "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
                },
                clear=False,
            ), patch.object(
                release_bootstrap_api, "apply_startup_bootstrap"
            ) as bootstrap:
                with self.assertRaises(HTTPException) as error:
                    release_bootstrap_api.release_bootstrap(
                        self._request("temporary-release-token")
                    )
                self.assertEqual(error.exception.status_code, 404)
                bootstrap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
