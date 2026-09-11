from __future__ import annotations

import unittest
from unittest.mock import patch

from app import technical_observability as obs
from app.alert_center import _observability_alerts


class TechnicalObservabilityTests(unittest.TestCase):
    def _readiness(self, ready=True, content_gates=None):
        return {
            "ready_for_technical_handoff": ready,
            "technical_blockers": [] if ready else [{"id": "runtime", "name": "Runtime"}],
            "content_gates": list(content_gates or []),
        }

    def _snapshot(
        self,
        *,
        db=None,
        ai=None,
        sync=None,
        readiness=None,
    ):
        db = db or {"ok": True, "latency_ms": 25, "error": None}
        ai = ai or {
            "ok": True,
            "state": "observed",
            "calls": 1,
            "failures": 0,
            "failure_pct": 0.0,
            "avg_latency_ms": 280,
        }
        sync = sync or {
            "state": "not_initialized",
            "ok": True,
            "total": 0,
            "active": 0,
            "processing": 0,
            "failed": 0,
            "stale_processing": 0,
        }
        readiness = readiness or self._readiness()
        with patch.object(obs, "_database_probe", return_value=db), \
             patch.object(obs, "_ai_probe", return_value=ai), \
             patch.object(obs, "_sync_probe", return_value=sync), \
             patch.object(obs, "_int_env", side_effect=lambda name, default: default), \
             patch.object(obs, "_float_env", side_effect=lambda name, default: default):
            return obs.technical_observability_snapshot(readiness_snapshot=readiness)

    def test_current_low_volume_state_is_healthy(self):
        data = self._snapshot()
        self.assertEqual(data["state"], "healthy")
        self.assertTrue(data["healthy"])
        self.assertEqual(data["error_count"], 0)
        self.assertEqual(data["warning_count"], 0)
        sync = next(x for x in data["signals"] if x["id"] == "source_sync")
        self.assertTrue(sync["ok"])
        self.assertIn("طبيعية", sync["detail"])

    def test_content_gates_do_not_become_technical_errors(self):
        data = self._snapshot(
            readiness=self._readiness(
                True,
                ["23+23 exam bank gap: objective=0, essay=16"],
            )
        )
        self.assertEqual(data["state"], "healthy")
        tech = next(x for x in data["signals"] if x["id"] == "technical_readiness")
        self.assertTrue(tech["ok"])

    def test_database_latency_can_degrade_without_false_outage(self):
        data = self._snapshot(db={"ok": True, "latency_ms": 750, "error": None})
        self.assertEqual(data["state"], "degraded")
        signal = next(x for x in data["signals"] if x["id"] == "database_latency")
        self.assertEqual(signal["severity"], "warning")

    def test_ai_failure_rate_errors_only_after_minimum_sample(self):
        ai = {
            "ok": True,
            "state": "observed",
            "calls": 8,
            "failures": 3,
            "failure_pct": 37.5,
            "avg_latency_ms": 500,
        }
        data = self._snapshot(ai=ai)
        self.assertEqual(data["state"], "unhealthy")
        signal = next(x for x in data["signals"] if x["id"] == "ai_failure_rate")
        self.assertEqual(signal["severity"], "error")

    def test_source_sync_failure_is_warning_not_runtime_outage(self):
        sync = {
            "state": "active",
            "ok": False,
            "total": 2,
            "active": 1,
            "processing": 0,
            "failed": 1,
            "stale_processing": 0,
        }
        data = self._snapshot(sync=sync)
        self.assertEqual(data["state"], "degraded")
        signal = next(x for x in data["signals"] if x["id"] == "source_sync_failed")
        self.assertEqual(signal["severity"], "warning")

    def test_observability_alert_adapter_ignores_green_and_duplicate_readiness(self):
        alerts = _observability_alerts({
            "signals": [
                {
                    "id": "database_probe",
                    "name": "Database probe",
                    "severity": "info",
                    "ok": True,
                    "detail": "ok",
                    "path": "/admin/diagnostics",
                },
                {
                    "id": "technical_readiness",
                    "name": "Technical readiness",
                    "severity": "error",
                    "ok": False,
                    "detail": "duplicate",
                    "path": "/admin/operations-readiness",
                },
                {
                    "id": "ai_latency",
                    "name": "AI latency",
                    "severity": "warning",
                    "ok": False,
                    "detail": "slow",
                    "path": "/admin/ai-operations",
                },
            ]
        })
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["source"], "observability")
        self.assertEqual(alerts[0]["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
