from __future__ import annotations

from contextlib import contextmanager
import os
import unittest
from unittest.mock import patch

from fastapi import Response

from app import runtime_probe


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, *, store=True):
        self.store = store
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append(sql)
        if "SELECT 1 ok" == " ".join(str(sql).split()):
            return _Cursor({"ok": 1})
        if "gemini_file_search_store" in str(sql):
            return _Cursor({"ok": 1} if self.store else None)
        raise AssertionError(f"Unexpected SQL: {sql}")


@contextmanager
def _connect(store=True):
    yield _Connection(store=store)


class LightweightRuntimeReadinessTests(unittest.TestCase):
    def _identity(self, *, production=True, main=True, gemini=True, object_storage=True):
        return {
            "provider": "vercel",
            "production_environment": production,
            "current_runtime_is_production_main": main,
            "config_state": {
                "database": True,
                "admin_access": True,
                "student_session": True,
                "object_storage": object_storage,
                "gemini": gemini,
            },
        }

    def test_ready_when_critical_runtime_dependencies_are_present(self):
        with patch.object(runtime_probe, "runtime_identity", return_value=self._identity()), \
             patch.object(runtime_probe, "connect", side_effect=lambda: _connect(True)), \
             patch.dict(os.environ, {"GEMINI_FILE_SEARCH_STORE": ""}, clear=False):
            data = runtime_probe.lightweight_runtime_readiness()
        self.assertTrue(data["ready"])
        self.assertTrue(data["database"])
        self.assertTrue(all(data["critical_config"].values()))
        self.assertTrue(data["optional_capabilities"]["gemini"])
        self.assertTrue(data["optional_capabilities"]["file_search_store"])
        self.assertTrue(data["deployment_ok"])

    def test_missing_persisted_file_search_store_does_not_block_technical_readiness(self):
        with patch.object(runtime_probe, "runtime_identity", return_value=self._identity()), \
             patch.object(runtime_probe, "connect", side_effect=lambda: _connect(False)), \
             patch.dict(os.environ, {"GEMINI_FILE_SEARCH_STORE": ""}, clear=False):
            data = runtime_probe.lightweight_runtime_readiness()
        self.assertTrue(data["ready"])
        self.assertFalse(data["optional_capabilities"]["file_search_store"])
        self.assertNotIn("file_search_store", data["critical_config"])

    def test_missing_gemini_does_not_block_technical_readiness(self):
        with patch.object(
            runtime_probe,
            "runtime_identity",
            return_value=self._identity(gemini=False),
        ), patch.object(runtime_probe, "connect", side_effect=lambda: _connect(False)), \
             patch.dict(os.environ, {"GEMINI_FILE_SEARCH_STORE": ""}, clear=False):
            data = runtime_probe.lightweight_runtime_readiness()
        self.assertTrue(data["ready"])
        self.assertFalse(data["optional_capabilities"]["gemini"])

    def test_missing_object_storage_remains_a_technical_blocker(self):
        with patch.object(
            runtime_probe,
            "runtime_identity",
            return_value=self._identity(object_storage=False),
        ), patch.object(runtime_probe, "connect", side_effect=lambda: _connect(True)), \
             patch.dict(os.environ, {"GEMINI_FILE_SEARCH_STORE": ""}, clear=False):
            data = runtime_probe.lightweight_runtime_readiness()
        self.assertFalse(data["ready"])
        self.assertFalse(data["critical_config"]["object_storage"])

    def test_invalid_production_provenance_is_not_ready(self):
        with patch.object(
            runtime_probe,
            "runtime_identity",
            return_value=self._identity(production=True, main=False),
        ), patch.object(runtime_probe, "connect", side_effect=lambda: _connect(True)), \
             patch.dict(os.environ, {"GEMINI_FILE_SEARCH_STORE": ""}, clear=False):
            data = runtime_probe.lightweight_runtime_readiness()
        self.assertFalse(data["ready"])
        self.assertFalse(data["deployment_ok"])

    def test_preview_does_not_require_production_main_metadata(self):
        with patch.object(
            runtime_probe,
            "runtime_identity",
            return_value=self._identity(production=False, main=False),
        ), patch.object(runtime_probe, "connect", side_effect=lambda: _connect(True)), \
             patch.dict(os.environ, {"GEMINI_FILE_SEARCH_STORE": ""}, clear=False):
            data = runtime_probe.lightweight_runtime_readiness()
        self.assertTrue(data["ready"])
        self.assertTrue(data["deployment_ok"])

    def test_public_probe_returns_only_minimal_payload_and_no_store(self):
        response = Response()
        with patch.object(
            runtime_probe,
            "lightweight_runtime_readiness",
            return_value={"ready": True},
        ):
            payload = runtime_probe.health_ready(response)
        self.assertEqual(
            set(payload),
            {"status", "service", "version"},
        )
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_public_probe_returns_503_when_not_ready(self):
        response = Response()
        with patch.object(
            runtime_probe,
            "lightweight_runtime_readiness",
            return_value={"ready": False},
        ):
            payload = runtime_probe.health_ready(response)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["status"], "not_ready")


if __name__ == "__main__":
    unittest.main()
