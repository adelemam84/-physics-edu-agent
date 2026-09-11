from __future__ import annotations

import unittest
from unittest.mock import patch

from app import technical_observability as obs
from app.services.runtime_identity import runtime_identity


class RuntimeIdentityTests(unittest.TestCase):
    def test_secret_values_never_affect_fingerprint_when_presence_is_same(self):
        first = runtime_identity({
            "DATABASE_URL": "postgresql://one",
            "ADMIN_API_KEY": "secret-one",
            "STUDENT_SESSION_SECRET": "student-one",
            "AWS_ACCESS_KEY_ID": "a",
            "AWS_SECRET_ACCESS_KEY": "b",
            "AWS_ENDPOINT_URL_S3": "https://one.example",
            "AWS_REGION": "us-east-1",
            "GEMINI_API_KEY": "gemini-one",
        }, application_version="1.8.1")
        second = runtime_identity({
            "DATABASE_URL": "postgresql://two",
            "ADMIN_API_KEY": "secret-two",
            "STUDENT_SESSION_SECRET": "student-two",
            "AWS_ACCESS_KEY_ID": "x",
            "AWS_SECRET_ACCESS_KEY": "y",
            "AWS_ENDPOINT_URL_S3": "https://two.example",
            "AWS_REGION": "eu-west-1",
            "GEMINI_API_KEY": "gemini-two",
        }, application_version="1.8.1")
        self.assertEqual(first["config_fingerprint"], second["config_fingerprint"])
        self.assertFalse(first["config_fingerprint_contains_secret_values"])
        self.assertNotIn("secret-one", repr(first))
        self.assertNotIn("postgresql://one", repr(first))

    def test_config_presence_change_changes_fingerprint(self):
        configured = runtime_identity({"DATABASE_URL": "configured"})
        missing = runtime_identity({"DATABASE_URL": ""})
        self.assertNotEqual(
            configured["config_fingerprint"],
            missing["config_fingerprint"],
        )

    def test_production_requires_main_and_commit_sha(self):
        healthy = runtime_identity({
            "VERCEL": "1",
            "VERCEL_ENV": "production",
            "VERCEL_GIT_COMMIT_REF": "main",
            "VERCEL_GIT_COMMIT_SHA": "a" * 40,
        })
        self.assertTrue(healthy["current_runtime_is_production_main"])
        self.assertEqual(healthy["drift_state"], "production_main")
        self.assertEqual(healthy["provenance_source"], "vercel_git")

        invalid = runtime_identity({
            "VERCEL": "1",
            "VERCEL_ENV": "production",
            "VERCEL_GIT_COMMIT_REF": "feature/test",
            "VERCEL_GIT_COMMIT_SHA": "b" * 40,
        })
        self.assertFalse(invalid["current_runtime_is_production_main"])
        self.assertEqual(invalid["drift_state"], "production_metadata_invalid")

    def test_controlled_release_provenance_is_used_when_vercel_git_metadata_is_absent(self):
        identity = runtime_identity({
            "VERCEL": "1",
            "VERCEL_ENV": "production",
            "RELEASE_GIT_REF": "main",
            "RELEASE_GIT_SHA": "d" * 40,
        })
        self.assertTrue(identity["current_runtime_is_production_main"])
        self.assertEqual(identity["git_ref"], "main")
        self.assertEqual(identity["git_commit_sha"], "d" * 40)
        self.assertEqual(identity["provenance_source"], "controlled_release")

    def test_native_vercel_git_metadata_wins_over_controlled_release_fallback(self):
        identity = runtime_identity({
            "VERCEL": "1",
            "VERCEL_ENV": "production",
            "VERCEL_GIT_COMMIT_REF": "feature/wrong",
            "VERCEL_GIT_COMMIT_SHA": "e" * 40,
            "RELEASE_GIT_REF": "main",
            "RELEASE_GIT_SHA": "f" * 40,
        })
        self.assertFalse(identity["current_runtime_is_production_main"])
        self.assertEqual(identity["git_ref"], "feature/wrong")
        self.assertEqual(identity["provenance_source"], "vercel_git")

    def test_preview_is_not_reported_as_production_drift(self):
        preview = runtime_identity({
            "VERCEL": "1",
            "VERCEL_ENV": "preview",
            "VERCEL_GIT_COMMIT_REF": "feature/test",
            "VERCEL_GIT_COMMIT_SHA": "c" * 40,
        })
        self.assertEqual(preview["drift_state"], "preview")
        self.assertFalse(preview["production_environment"])

    def test_observability_marks_invalid_production_metadata_as_error(self):
        readiness = {
            "ready_for_technical_handoff": True,
            "technical_blockers": [],
            "content_gates": [],
        }
        with patch.object(obs, "_database_probe", return_value={"ok": True, "latency_ms": 10, "error": None}), \
             patch.object(obs, "_ai_probe", return_value={
                 "ok": True, "state": "no_recent_calls", "calls": 0,
                 "failures": 0, "failure_pct": 0.0, "avg_latency_ms": 0,
             }), \
             patch.object(obs, "_sync_probe", return_value={
                 "state": "not_initialized", "ok": True, "total": 0,
                 "active": 0, "processing": 0, "failed": 0, "stale_processing": 0,
             }), \
             patch.object(obs, "_rate_limit_probe", return_value={
                 "ok": True, "state": "idle", "active_subjects": 0,
                 "near_limit_subjects": 0, "blocked_subjects": 0,
                 "scopes": [], "privacy": {},
             }), \
             patch.object(obs, "runtime_identity", return_value={
                 "provider": "vercel",
                 "production_environment": True,
                 "current_runtime_is_production_main": False,
                 "drift_state": "production_metadata_invalid",
                 "git_commit_short": "deadbeef",
             }), \
             patch.object(obs, "_int_env", side_effect=lambda name, default: default), \
             patch.object(obs, "_float_env", side_effect=lambda name, default: default):
            data = obs.technical_observability_snapshot(
                readiness_snapshot=readiness
            )
        self.assertEqual(data["state"], "unhealthy")
        signal = next(x for x in data["signals"] if x["id"] == "deployment_drift")
        self.assertEqual(signal["severity"], "error")


if __name__ == "__main__":
    unittest.main()
