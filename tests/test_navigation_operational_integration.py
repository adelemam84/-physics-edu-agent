from __future__ import annotations

import unittest

from app import progress_dashboard, student_portal


class NavigationOperationalIntegrationTests(unittest.TestCase):
    def test_student_portal_exposes_command_center_as_primary_action(self):
        page = student_portal.PAGE
        self.assertIn('/student/command-center', page)
        self.assertIn('مهمة اليوم ومركز القيادة', page)
        self.assertIn('اعرض لي مهمة واحدة واضحة لليوم', page)

    def test_mobile_student_navigation_exposes_today_mission(self):
        page = student_portal.PAGE
        self.assertIn("location.href='/student/command-center'", page)
        self.assertIn('>مهمة اليوم</button>', page)

    def test_progress_dashboard_uses_canonical_intervention_engine(self):
        source = progress_dashboard.PAGE
        self.assertIn('/admin/intervention-queue', source)
        self.assertIn('نفس محرك التدخل الحتمي', source)
        self.assertNotIn('x.weakest', source)

    def test_progress_api_exposes_intervention_contract(self):
        source = __import__('inspect').getsource(progress_dashboard.progress_dashboard)
        self.assertIn('build_intervention_queue', source)
        self.assertIn('intervention_summary', source)
        self.assertIn('intervention_policy', source)


if __name__ == '__main__':
    unittest.main()
