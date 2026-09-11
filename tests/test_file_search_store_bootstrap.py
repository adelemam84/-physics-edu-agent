from __future__ import annotations

from contextlib import contextmanager
import inspect
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import file_search_store, main


class _FakeRow(dict):
    pass


class _FakeConnection:
    def __init__(self, acquired: bool = True):
        self.acquired = acquired
        self.unlocks = 0

    def execute(self, sql: str, params=()):
        if "pg_try_advisory_lock" in sql:
            return _FakeCursor({"acquired": self.acquired})
        if "pg_advisory_unlock" in sql:
            self.unlocks += 1
            return _FakeCursor({"pg_advisory_unlock": True})
        raise AssertionError(f"Unexpected SQL: {sql}")


class _FakeCursor:
    def __init__(self, row):
        self.row = _FakeRow(row)

    def fetchone(self):
        return self.row


@contextmanager
def _fake_connect(acquired: bool = True):
    yield _FakeConnection(acquired=acquired)


class FileSearchProductionBootstrapTests(unittest.TestCase):
    def test_preview_never_auto_provisions_external_store(self):
        with patch.dict(
            os.environ,
            {"VERCEL_ENV": "preview", "GEMINI_FILE_SEARCH_AUTO_PROVISION": "true"},
            clear=False,
        ), patch.object(file_search_store, "configured_store_name", return_value=""), \
             patch.object(file_search_store, "ensure_store") as ensure:
            result = file_search_store.bootstrap_store_if_enabled()
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "non_production")
        ensure.assert_not_called()

    def test_production_bootstrap_is_idempotent_and_lock_guarded(self):
        with patch.dict(
            os.environ,
            {"VERCEL_ENV": "production", "GEMINI_FILE_SEARCH_AUTO_PROVISION": "true"},
            clear=False,
        ), patch.object(file_search_store.research_engine, "GEMINI_API_KEY", "configured"), \
             patch.object(file_search_store, "configured_store_name", side_effect=["", ""]), \
             patch.object(file_search_store, "connect", _fake_connect), \
             patch.object(
                 file_search_store,
                 "ensure_store",
                 return_value={
                     "created": True,
                     "reused": False,
                     "name": "fileSearchStores/physics-prod",
                 },
             ) as ensure:
            result = file_search_store.bootstrap_store_if_enabled()
        self.assertTrue(result["attempted"])
        self.assertTrue(result["configured"])
        self.assertEqual(result["name"], "fileSearchStores/physics-prod")
        ensure.assert_called_once()

    def test_busy_bootstrap_lock_skips_duplicate_creation(self):
        @contextmanager
        def busy_connect():
            yield _FakeConnection(acquired=False)

        with patch.dict(
            os.environ,
            {"VERCEL_ENV": "production", "GEMINI_FILE_SEARCH_AUTO_PROVISION": "true"},
            clear=False,
        ), patch.object(file_search_store.research_engine, "GEMINI_API_KEY", "configured"), \
             patch.object(file_search_store, "configured_store_name", return_value=""), \
             patch.object(file_search_store, "connect", busy_connect), \
             patch.object(file_search_store, "ensure_store") as ensure:
            result = file_search_store.bootstrap_store_if_enabled()
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "bootstrap_lock_busy")
        ensure.assert_not_called()

    def test_provider_failure_does_not_abort_application_startup(self):
        with patch.dict(
            os.environ,
            {"VERCEL_ENV": "production", "GEMINI_FILE_SEARCH_AUTO_PROVISION": "true"},
            clear=False,
        ), patch.object(file_search_store.research_engine, "GEMINI_API_KEY", "configured"), \
             patch.object(file_search_store, "configured_store_name", side_effect=["", ""]), \
             patch.object(file_search_store, "connect", _fake_connect), \
             patch.object(
                 file_search_store,
                 "ensure_store",
                 side_effect=HTTPException(502, "provider unavailable"),
             ):
            result = file_search_store.bootstrap_store_if_enabled()
        self.assertTrue(result["attempted"])
        self.assertFalse(result["configured"])
        self.assertEqual(result["reason"], "provider_error")
        self.assertEqual(result["status_code"], 502)

    def test_application_lifespan_runs_safe_bootstrap_after_db_bootstrap(self):
        source = inspect.getsource(main.lifespan)
        self.assertIn("with startup_migration_lock():", source)
        self.assertIn("run_phase2_bootstrap(release_schema_ready=True)", source)
        self.assertIn("bootstrap_store_if_enabled()", source)
        self.assertLess(
            source.index("run_phase2_bootstrap(release_schema_ready=True)"),
            source.index("bootstrap_store_if_enabled()"),
        )


if __name__ == "__main__":
    unittest.main()
