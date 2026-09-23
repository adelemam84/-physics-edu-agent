from __future__ import annotations

import unittest
from pathlib import Path

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
            "/admin/feature-status",
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
            "/admin/exam-engine",
            "/admin/exam-analytics",
            "/admin/students",
            "/admin/lesson-studio/workspace",
            "/admin/alerts",
        ):
            self.assertIn(path, PAGE)

    def test_dashboard_uses_current_lesson_source_schema(self):
        source = Path("app/admin_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("lsm.mapping_status='approved'", source)
        self.assertIn("d.kind IN ('lesson','explanation','textbook','notes')", source)
        self.assertNotIn("lsm.approved=TRUE", source)
        self.assertNotIn("d.source_kind", source)

    def test_dashboard_keeps_responsive_kpi_layout(self):
        self.assertIn("@media(max-width:1100px)", PAGE)
        self.assertIn("@media(max-width:520px)", PAGE)
        self.assertIn(".cards,.status-grid{grid-template-columns:1fr}", PAGE)


    def test_dashboard_has_accessible_navigation_and_refresh_controls(self):
        for token in (
            'class=skip-link href="#main"',
            'aria-label="التنقل الإداري"',
            'id=navSearch',
            'aria-live=polite',
            'id=refreshBtn',
            "fetch('/health/ready')",
            'رفع المحتوى مؤجل ومغلق',
        ):
            self.assertIn(token, PAGE)

    def test_dashboard_does_not_persist_admin_credentials_in_browser_storage(self):
        self.assertNotIn("localStorage", PAGE)
        self.assertNotIn("sessionStorage", PAGE)


    def test_dashboard_supports_non_secret_operator_preferences(self):
        for token in (
            "تخصيص الواجهة",
            "كثافة العرض",
            "مريح",
            "مدمج",
            "إظهار كل البطاقات",
            "document.cookie",
            "edu_dashboard_prefs",
        ):
            self.assertIn(token, PAGE)

    def test_dashboard_can_hide_operational_widgets_without_removing_them(self):
        for token in (
            'data-widget="platform-status"',
            'data-widget="daily-overview"',
            'data-widget="student-readiness"',
            'data-widget="student-followup"',
            'data-widget="guardian-messages"',
            "applyWidgetPreferences",
        ):
            self.assertIn(token, PAGE)

    def test_dashboard_preserves_content_lock_and_avoids_secret_storage(self):
        self.assertIn("رفع المحتوى مؤجل ومغلق", PAGE)
        self.assertIn("content_ingestion==='locked'", PAGE)
        self.assertNotIn("localStorage", PAGE)
        self.assertNotIn("sessionStorage", PAGE)


    def test_dashboard_customizer_has_accessible_expansion_and_reset(self):
        for token in (
            'id=customizerToggle',
            'aria-controls=customizer',
            'aria-expanded=false',
            "setAttribute('aria-expanded'",
            "resetDashboardPrefs",
            "إعادة الضبط",
        ):
            self.assertIn(token, PAGE)

    def test_dashboard_display_cookie_is_strict_and_secure_on_https(self):
        self.assertIn("SameSite=Strict", PAGE)
        self.assertIn("location.protocol==='https:'?'; Secure':''", PAGE)
        self.assertNotIn("SameSite=Lax", PAGE)

    def test_dashboard_customizer_uses_explicit_dom_references(self):
        for token in (
            "document.getElementById('customizer')",
            "document.getElementById('customizerToggle')",
            "document.getElementById('refreshBtn')",
            "customizerPanel.hidden",
            "refreshButton.disabled",
        ):
            self.assertIn(token, PAGE)


    def test_dashboard_surfaces_operational_work_and_ai_activity(self):
        for token in (
            'data-widget="operations-attention"',
            'id=acceptanceSummary',
            'id=interventionSummary',
            'id=contentPipeline',
            'id=aiUsageSummary',
            "/api/admin/acceptance-work-queue",
            "/api/admin/intervention-queue",
            "/api/admin/content-completion",
            "/api/admin/ai-operations/usage?hours=24",
            "الوضع المجاني",
        ):
            self.assertIn(token, PAGE)

    def test_dashboard_operational_widgets_are_customizable(self):
        self.assertIn("'operations-attention':true", PAGE)
        self.assertIn("data-widget-toggle=operations-attention", PAGE)
        self.assertIn("قبول بشري", PAGE)
        self.assertIn("تدخل المدرس", PAGE)

if __name__ == "__main__":
    unittest.main()
