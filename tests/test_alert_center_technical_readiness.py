from __future__ import annotations

import unittest

from app.alert_center import _technical_readiness_alerts


class AlertCenterTechnicalReadinessTests(unittest.TestCase):
    def test_content_gates_do_not_create_false_technical_alerts(self):
        alerts = _technical_readiness_alerts({
            "ready_for_technical_handoff": True,
            "technical_blockers": [],
            "content_gates": ["23+23 exam bank gap: essay=16"],
        })
        self.assertEqual(alerts, [])

    def test_each_technical_blocker_becomes_error_alert(self):
        alerts = _technical_readiness_alerts({
            "ready_for_technical_handoff": False,
            "technical_blockers": [
                {
                    "id": "object_storage",
                    "name": "تخزين ملفات المصدر",
                    "detail": "إعدادات Object Storage غير مكتملة",
                    "path": "/admin/readiness",
                },
                {
                    "id": "runtime_activation",
                    "name": "Runtime / AI activation",
                    "detail": "File Search missing",
                    "path": "/api/admin/next-release/status",
                },
            ],
        })
        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(x["severity"] == "error" for x in alerts))
        self.assertTrue(all(x["source"] == "technical_readiness" for x in alerts))
        self.assertIn("object", alerts[0]["detail"].lower())

    def test_false_readiness_without_blocker_fails_closed(self):
        alerts = _technical_readiness_alerts({
            "ready_for_technical_handoff": False,
            "technical_blockers": [],
        })
        self.assertEqual(len(alerts), 1)
        self.assertIn("تعارض", alerts[0]["title"])

    def test_malformed_blocker_contract_fails_closed(self):
        alerts = _technical_readiness_alerts({
            "ready_for_technical_handoff": False,
            "technical_blockers": "not-a-list",
        })
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "error")


if __name__ == "__main__":
    unittest.main()
