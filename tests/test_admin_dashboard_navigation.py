from __future__ import annotations

import unittest

from app.admin_dashboard import PAGE


class AdminDashboardNavigationTests(unittest.TestCase):
    """Protect the grouped admin command-center navigation and mobile behavior."""

    def test_dashboard_groups_high_value_workflows(self):
        for label in (
            "القيادة",
            "المحتوى والمصادر",
            "الاختبارات والتعلم",
            "القبول والجودة",
            "الإدارة",
        ):
            self.assertIn(label, PAGE)

    def test_dashboard_exposes_ai_and_acceptance_shortcuts(self):
        for path in (
            "/admin/operations-readiness",
            "/admin/ai-operations",
            "/admin/ai-budget",
            "/admin/interventions",
            "/admin/research-engine",
            "/admin/lesson-studio/workspace",
            "/admin/e2e-content-acceptance",
            "/admin/acceptance-work-queue",
        ):
            self.assertIn(path, PAGE)

    def test_dashboard_never_puts_student_codes_in_urls(self):
        self.assertNotIn("student_code=", PAGE)
        self.assertNotIn("encodeURIComponent(a.external_code)", PAGE)

    def test_mobile_navigation_remains_scrollable_not_hidden(self):
        self.assertIn(".side nav{display:flex;overflow:auto", PAGE)
        self.assertNotIn(".side{display:none", PAGE)

    def test_dashboard_uses_command_center_design_system(self):
        for token in (
            "--brand:",
            "--radius:",
            "--shadow:",
            "class=hero",
            "class=status-grid",
            "class=quick-actions",
            "يحتاج انتباهك",
            "نظرة عامة",
        ):
            self.assertIn(token, PAGE)

    def test_dashboard_has_high_value_quick_actions(self):
        for path in (
            "/admin/quiz-builder",
            "/admin/students",
            "/admin/lesson-studio/workspace",
            "/admin/alerts",
        ):
            self.assertIn(path, PAGE)

    def test_dashboard_keeps_responsive_kpi_layout(self):
        self.assertIn("@media(max-width:1100px)", PAGE)
        self.assertIn("@media(max-width:520px)", PAGE)
        self.assertIn(".cards,.status-grid{grid-template-columns:1fr}", PAGE)


if __name__ == "__main__":
    unittest.main()
