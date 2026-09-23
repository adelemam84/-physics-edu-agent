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
        self.assertEqual(result["bootstrap_attempts"], 1)
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


    def test_transient_startup_lock_timeout_retries_then_succeeds(self):
        timeout = RuntimeError("Timed out waiting for startup migration lock")
        with patch.dict(
            os.environ,
            {
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
                "RELEASE_GIT_SHA": "abc123",
                "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
                "RELEASE_BOOTSTRAP_LOCK_RETRIES": "2",
                "RELEASE_BOOTSTRAP_LOCK_RETRY_DELAY_SECONDS": "0.1",
            },
            clear=False,
        ), patch.object(
            release_bootstrap_api,
            "apply_startup_bootstrap",
            side_effect=[timeout, timeout, None],
        ) as bootstrap, patch.object(
            release_bootstrap_api.time, "sleep"
        ) as sleep:
            result = release_bootstrap_api.release_bootstrap(
                self._request("temporary-release-token")
            )

        self.assertEqual(bootstrap.call_count, 3)
        self.assertEqual(result["bootstrap_attempts"], 3)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [0.1, 0.2],
        )

    def test_non_lock_runtime_error_is_not_retried(self):
        with patch.dict(
            os.environ,
            {
                "VERCEL_ENV": "production",
                "RELEASE_GIT_REF": "main",
                "RELEASE_BOOTSTRAP_TOKEN": "temporary-release-token",
            },
            clear=False,
        ), patch.object(
            release_bootstrap_api,
            "apply_startup_bootstrap",
            side_effect=RuntimeError("migration failed"),
        ) as bootstrap, patch.object(
            release_bootstrap_api.time, "sleep"
        ) as sleep:
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                release_bootstrap_api.release_bootstrap(
                    self._request("temporary-release-token")
                )

        bootstrap.assert_called_once_with()
        sleep.assert_not_called()

    def test_retry_policy_is_bounded_and_uses_safe_defaults(self):
        with patch.dict(
            os.environ,
            {
                "RELEASE_BOOTSTRAP_LOCK_RETRIES": "999",
                "RELEASE_BOOTSTRAP_LOCK_RETRY_DELAY_SECONDS": "99",
            },
            clear=False,
        ):
            self.assertEqual(
                release_bootstrap_api._release_bootstrap_retry_policy(),
                (3, 5.0),
            )
        with patch.dict(
            os.environ,
            {
                "RELEASE_BOOTSTRAP_LOCK_RETRIES": "not-a-number",
                "RELEASE_BOOTSTRAP_LOCK_RETRY_DELAY_SECONDS": "bad",
            },
            clear=False,
        ):
            self.assertEqual(
                release_bootstrap_api._release_bootstrap_retry_policy(),
                (2, 1.0),
            )


if __name__ == "__main__":
    unittest.main()
