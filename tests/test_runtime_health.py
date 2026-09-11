from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from app import runtime_health


class RuntimeHealthTests(unittest.TestCase):
    def _readiness(
        self,
        *,
        technical=True,
        controlled=False,
        content_ready=False,
        content_gates=None,
        blockers=None,
    ):
        return {
            "ready_for_technical_handoff": technical,
            "ready_for_controlled_launch": controlled,
            "content_release_ready": content_ready,
            "release_state": "runtime_ready_content_gate_open",
            "technical_blockers": list(blockers or []),
            "content_gates": list(content_gates or []),
        }

    def _observability(
        self,
        *,
        state="healthy",
        errors=0,
        warnings=0,
        signals=None,
        identity=None,
    ):
        return {
            "state": state,
            "error_count": errors,
            "warning_count": warnings,
            "signals": list(signals or []),
            "runtime_identity": identity or {
                "provider": "vercel",
                "environment": "production",
                "target_environment": "production",
                "git_ref": "main",
                "git_commit_short": "abcdef123456",
                "deployment_id": "dpl_test",
                "application_version": "1.8.1",
                "drift_state": "production_main",
                "current_runtime_is_production_main": True,
                "config_state": {
                    "database": True,
                    "admin_access": True,
                    "student_session": True,
                    "object_storage": True,
                    "gemini": True,
                    "openai_reviewer": False,
                    "mathpix": False,
                },
                "config_fingerprint": "1234567890abcdef",
            },
        }

    def _snapshot(self, readiness, observability):
        with patch.object(
            runtime_health,
            "build_operations_readiness",
            return_value=readiness,
        ), patch.object(
            runtime_health,
            "technical_observability_snapshot",
            return_value=observability,
        ):
            return runtime_health.runtime_health_snapshot()

    def test_content_gate_does_not_make_technical_runtime_unhealthy(self):
        data = self._snapshot(
            self._readiness(
                technical=True,
                controlled=False,
                content_ready=False,
                content_gates=["23+23 exam bank gap: objective=0, essay=16"],
            ),
            self._observability(state="healthy"),
        )
        self.assertEqual(data["state"], "healthy")
        self.assertTrue(data["ready_for_technical_handoff"])
        self.assertFalse(data["ready_for_controlled_launch"])
        self.assertEqual(data["content_gate_count"], 1)

    def test_observability_warning_degrades_runtime_health(self):
        data = self._snapshot(
            self._readiness(technical=True),
            self._observability(state="degraded", warnings=1),
        )
        self.assertEqual(data["state"], "degraded")
        self.assertFalse(data["healthy"])

    def test_technical_blocker_is_unhealthy(self):
        data = self._snapshot(
            self._readiness(
                technical=False,
                blockers=[{"id": "database_runtime"}],
            ),
            self._observability(state="healthy"),
        )
        self.assertEqual(data["state"], "unhealthy")
        self.assertEqual(data["technical_blocker_count"], 1)

    def test_raw_signal_evidence_is_omitted(self):
        data = self._snapshot(
            self._readiness(technical=True),
            self._observability(
                signals=[{
                    "id": "database_probe",
                    "name": "Database",
                    "severity": "info",
                    "ok": True,
                    "detail": "ok",
                    "path": "/admin/diagnostics",
                    "evidence": {
                        "secret": "must-not-leak",
                        "subject_hash": "must-not-leak",
                    },
                }]
            ),
        )
        serialized = repr(data)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("subject_hash", serialized)
        self.assertTrue(data["policy"]["raw_signal_evidence_omitted"])

    def test_configuration_values_are_boolean_only(self):
        identity = self._observability()["runtime_identity"]
        identity["config_state"] = {
            "database": "postgresql://secret",
            "gemini": "api-key-secret",
            "optional": "",
        }
        data = self._snapshot(
            self._readiness(technical=True),
            self._observability(identity=identity),
        )
        self.assertEqual(
            data["configuration"]["state"],
            {"database": True, "gemini": True, "optional": False},
        )
        self.assertNotIn("postgresql://secret", repr(data))
        self.assertNotIn("api-key-secret", repr(data))

    def test_runtime_health_endpoint_is_admin_only_and_no_store(self):
        source = inspect.getsource(runtime_health)
        self.assertIn('dependencies=[Depends(require_admin)]', source)
        self.assertIn('response.headers["Cache-Control"] = "no-store"', source)


if __name__ == "__main__":
    unittest.main()
