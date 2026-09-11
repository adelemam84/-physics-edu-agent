from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.teacher_intervention_cases import PAGE, validate_transition


class TeacherInterventionCaseTests(unittest.TestCase):
    def test_active_cases_can_move_to_planned_done_or_dismissed(self):
        for current in ("open", "planned"):
            for target in ("open", "planned", "done", "dismissed"):
                validate_transition(current, target)

    def test_closed_cases_are_terminal(self):
        for current in ("done", "dismissed"):
            with self.assertRaises(HTTPException) as ctx:
                validate_transition(current, "open")
            self.assertEqual(ctx.exception.status_code, 409)

    def test_ui_keeps_teacher_in_control(self):
        self.assertIn("المنصة تقيس إشارات الخطر فقط", PAGE)
        self.assertIn("/api/admin/interventions", PAGE)
        self.assertIn("/api/admin/intervention-queue", PAGE)
        self.assertNotIn("auto_send", PAGE)


if __name__ == "__main__":
    unittest.main()
