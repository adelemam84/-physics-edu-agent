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
        rate_limits=None,
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
        rate_limits = rate_limits or {
            "ok": True,
            "state": "idle",
            "active_subjects": 0,
            "near_limit_subjects": 0,
            "blocked_subjects": 0,
            "scopes": [],
            "privacy": {
                "raw_subjects_returned": False,
                "subject_hashes_returned": False,
                "only_aggregates_returned": True,
            },
        }
        readiness = readiness or self._readiness()
        with patch.object(obs, "_database_probe", return_value=db), \
             patch.object(obs, "_ai_probe", return_value=ai), \
             patch.object(obs, "_sync_probe", return_value=sync), \
             patch.object(obs, "_rate_limit_probe", return_value=rate_limits), \
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

    def test_rate_limit_near_threshold_degrades_without_exposing_subjects(self):
        rate_limits = {
            "ok": True,
            "state": "observed",
            "active_subjects": 2,
            "near_limit_subjects": 1,
            "blocked_subjects": 0,
            "scopes": [{
                "scope": "admin_ai_research",
                "limit": 30,
                "window_seconds": 3600,
                "active_subjects": 2,
                "near_limit_subjects": 1,
                "blocked_subjects": 0,
                "max_hits": 25,
            }],
            "privacy": {
                "raw_subjects_returned": False,
                "subject_hashes_returned": False,
                "only_aggregates_returned": True,
            },
        }
        data = self._snapshot(rate_limits=rate_limits)
        self.assertEqual(data["state"], "degraded")
        signal = next(x for x in data["signals"] if x["id"] == "rate_limit_near")
        self.assertEqual(signal["severity"], "warning")
        self.assertFalse(signal["evidence"]["privacy"]["subject_hashes_returned"])
        self.assertFalse(signal["evidence"]["privacy"]["raw_subjects_returned"])
        for scope in signal["evidence"]["scopes"]:
            self.assertNotIn("subject_hash", scope)
            self.assertNotIn("subject", scope)

    def test_repeated_rate_limit_blocks_are_unhealthy(self):
        rate_limits = {
            "ok": True,
            "state": "observed",
            "active_subjects": 7,
            "near_limit_subjects": 7,
            "blocked_subjects": 5,
            "scopes": [{
                "scope": "admin_login",
                "limit": 8,
                "window_seconds": 900,
                "active_subjects": 7,
                "near_limit_subjects": 7,
                "blocked_subjects": 5,
                "max_hits": 12,
            }],
            "privacy": {
                "raw_subjects_returned": False,
                "subject_hashes_returned": False,
                "only_aggregates_returned": True,
            },
        }
        data = self._snapshot(rate_limits=rate_limits)
        self.assertEqual(data["state"], "unhealthy")
        signal = next(x for x in data["signals"] if x["id"] == "rate_limit_pressure")
        self.assertEqual(signal["severity"], "error")

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
