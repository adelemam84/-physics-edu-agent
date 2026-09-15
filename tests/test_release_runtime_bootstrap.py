from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app import main


class ReleaseRuntimeBootstrapTests(unittest.TestCase):
    def request(self, token: str):
        request = MagicMock()
        request.headers.get.return_value = token
        return request

    def test_authenticated_production_stage_runs_bootstrap(self):
        with patch.dict(
            "os.environ",
            {
                "VERCEL_ENV": "production",
                "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
                "RELEASE_GIT_SHA": "abc123",
            },
            clear=False,
        ), patch.object(main, "apply_startup_bootstrap") as bootstrap:
            result = main.release_runtime_bootstrap(
                self.request("temporary-release-token")
            )

        bootstrap.assert_called_once_with()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["release_git_sha"], "abc123")

    def test_missing_or_wrong_token_is_not_found_and_does_not_bootstrap(self):
        for supplied in ("", "wrong-token"):
            with self.subTest(supplied=supplied), patch.dict(
                "os.environ",
                {
                    "VERCEL_ENV": "production",
                    "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
                },
                clear=False,
            ), patch.object(main, "apply_startup_bootstrap") as bootstrap:
                with self.assertRaises(HTTPException) as error:
                    main.release_runtime_bootstrap(self.request(supplied))

                self.assertEqual(error.exception.status_code, 404)
                bootstrap.assert_not_called()

    def test_endpoint_is_disabled_without_ephemeral_release_token(self):
        with patch.dict(
            "os.environ",
            {"VERCEL_ENV": "production", "RELEASE_BOOTSTRAP_TOKEN": ""},
            clear=False,
        ), patch.object(main, "apply_startup_bootstrap") as bootstrap:
            with self.assertRaises(HTTPException) as error:
                main.release_runtime_bootstrap(self.request("anything"))

        self.assertEqual(error.exception.status_code, 404)
        bootstrap.assert_not_called()

    def test_endpoint_is_disabled_outside_production(self):
        with patch.dict(
            "os.environ",
            {
                "VERCEL_ENV": "preview",
                "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
            },
            clear=False,
        ), patch.object(main, "apply_startup_bootstrap") as bootstrap:
            with self.assertRaises(HTTPException) as error:
                main.release_runtime_bootstrap(
                    self.request("temporary-release-token")
                )

        self.assertEqual(error.exception.status_code, 404)
        bootstrap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
