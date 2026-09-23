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
        self.assertIn(".side nav{display:flex;flex-direction:column;max-height:42vh;overflow-y:auto;overflow-x:hidden", PAGE)
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


    def test_dashboard_has_priority_action_center(self):
        for token in (
            'data-widget="priority-actions"',
            'id=priorityActions',
            "/api/admin/alert-center",
            "buildPriorityActions",
            "الإجراءات ذات الأولوية",
            "فتح الإجراء",
        ):
            self.assertIn(token, PAGE)

    def test_priority_action_center_remains_read_only(self):
        self.assertIn("قراءة فقط", PAGE)
        self.assertNotIn("fetch('/api/admin/alert-center',{method:'POST'", PAGE)
        self.assertNotIn("fetch('/api/admin/acceptance-work-queue',{method:'POST'", PAGE)
        self.assertNotIn("fetch('/api/admin/intervention-queue',{method:'POST'", PAGE)


    def test_desktop_sidebar_has_independent_vertical_scroll(self):
        for token in (
            ".side{background:#111827;color:white;padding:20px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column;overflow:hidden}",
            ".side nav{min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable",
            ".nav-search{position:sticky;top:0;z-index:2",
            "scrollbar-width:thin",
        ):
            self.assertIn(token, PAGE)

    def test_mobile_sidebar_uses_compact_vertical_navigation(self):
        for token in (
            ".side{height:auto;position:static;overflow:visible;padding:8px 10px}",
            ".side nav{display:flex;flex-direction:column;max-height:42vh;overflow-y:auto;overflow-x:hidden",
            "overscroll-behavior:contain",
        ):
            self.assertIn(token, PAGE)


    def test_mobile_sidebar_is_compact_scrollable_and_non_overlay(self):
        for token in (
            ".side{height:auto;position:static;overflow:visible;padding:8px 10px}",
            ".side nav{display:flex;flex-direction:column;max-height:42vh;overflow-y:auto;overflow-x:hidden",
            "-webkit-overflow-scrolling:touch",
            ".nav-search{position:sticky;top:0;z-index:3",
            ".nav-group{display:flex;flex-wrap:wrap",
            ".side a{white-space:normal",
            ".main{padding:14px;padding-top:10px}",
        ):
            self.assertIn(token, PAGE)


    def test_mobile_sidebar_has_accessible_toggle(self):
        for token in (
            'id=mobileNavToggle',
            'aria-controls=adminNav',
            'aria-expanded=false',
            'id=adminNav',
            "toggleMobileNav",
            "setAttribute('aria-expanded'",
            ".mobile-nav-toggle{display:none",
            ".mobile-nav-toggle{display:flex",
            ".side nav.mobile-collapsed{display:none}",
        ):
            self.assertIn(token, PAGE)

    def test_mobile_sidebar_adapts_to_short_viewports(self):
        for token in (
            "@media(max-width:850px) and (max-height:700px)",
            ".side nav{max-height:32vh}",
            "@media(max-width:520px)",
            ".side nav{max-height:34vh}",
        ):
            self.assertIn(token, PAGE)

    def test_mobile_nav_preference_is_non_secret_and_persisted(self):
        for token in (
            "mobileNavOpen:false",
            "parsed.mobileNavOpen",
            "dashboardPrefs.mobileNavOpen",
            "persistDashboardPrefs()",
        ):
            self.assertIn(token, PAGE)


    def test_sidebar_marks_current_page_accessibly(self):
        for token in (
            ".side a.active-nav",
            "aria-current",
            "markActiveNav",
            "location.pathname",
        ):
            self.assertIn(token, PAGE)

    def test_mobile_sidebar_auto_closes_after_navigation_choice(self):
        for token in (
            "setupMobileNavAutoClose",
            "mobileNav.addEventListener('click'",
            "window.matchMedia('(max-width:850px)').matches",
            "dashboardPrefs.mobileNavOpen=false",
            "applyMobileNavPreference()",
        ):
            self.assertIn(token, PAGE)


    def test_mobile_navigation_groups_are_collapsible_and_accessible(self):
        for token in (
            ".nav-group.group-collapsed a{display:none}",
            ".nav-label{cursor:pointer",
            "setupCollapsibleNavGroups",
            "toggleNavGroup",
            "setAttribute('aria-expanded'",
            "setAttribute('role','button')",
            "setAttribute('tabindex','0')",
        ):
            self.assertIn(token, PAGE)

    def test_active_group_stays_open_and_search_expands_matches(self):
        for token in (
            "active-nav",
            "active?.closest('.nav-group')",
            "syncNavGroupState(activeGroup,false)",
            "if(q)g.classList.remove('group-collapsed')",
            "syncNavGroupState",
        ):
            self.assertIn(token, PAGE)


    def test_mobile_nav_group_state_is_persisted_safely(self):
        for token in (
            "navGroups:{}",
            "parsed.navGroups",
            "dashboardPrefs.navGroups",
            "group.dataset.groupKey",
            "persistDashboardPrefs()",
            "applyRememberedNavGroupStates",
        ):
            self.assertIn(token, PAGE)

    def test_search_clear_restores_remembered_group_state(self):
        for token in (
            "if(q)g.classList.remove('group-collapsed')",
            "if(!q)applyRememberedNavGroupStates()",
            "active?.closest('.nav-group')",
        ):
            self.assertIn(token, PAGE)


    def test_mobile_nav_has_open_all_and_close_all_controls(self):
        for token in (
            'id=navGroupControls',
            "فتح الكل",
            "إغلاق الكل",
            "setAllNavGroups(false)",
            "setAllNavGroups(true)",
            "function setAllNavGroups",
        ):
            self.assertIn(token, PAGE)

    def test_open_close_all_persists_group_state_and_keeps_active_group_open(self):
        for token in (
            "dashboardPrefs.navGroups[group.dataset.groupKey]=collapsed",
            "persistDashboardPrefs()",
            "applyRememberedNavGroupStates()",
            "let activeGroup=active?.closest('.nav-group')",
            "syncNavGroupState(activeGroup,false)",
        ):
            self.assertIn(token, PAGE)

    def test_remembered_group_state_is_reapplied_during_initialization(self):
        init = "readDashboardPrefs();applyWidgetPreferences();applyMobileNavPreference();markActiveNav();updateSmartSortControl();setupCollapsibleNavGroups();"
        self.assertIn(init, PAGE)
        self.assertIn("applyRememberedNavGroupStates()", PAGE)


    def test_mobile_nav_supports_favorites_and_usage_ordering(self):
        for token in (
            "navUsage:{}",
            "favorites:[]",
            "trackNavUsage",
            "renderFavoriteGroup",
            "sortNavGroupsByUsage",
            "toggleFavorite",
            "data-favorite-toggle",
            "المفضلة",
        ):
            self.assertIn(token, PAGE)

    def test_mobile_nav_usage_is_bounded_and_non_secret(self):
        for token in (
            "MAX_NAV_USAGE_ENTRIES=20",
            "MAX_FAVORITES=8",
            "trimNavUsage",
            "dashboardPrefs.navUsage",
            "dashboardPrefs.favorites",
            "persistDashboardPrefs()",
        ):
            self.assertIn(token, PAGE)

    def test_favorites_group_is_kept_above_usage_sorted_groups(self):
        for token in (
            "data-system-group=\"favorites\"",
            "mobileNav.insertBefore(favoriteGroup",
            "regularGroups.sort",
            "usageScoreForGroup",
        ):
            self.assertIn(token, PAGE)


    def test_mobile_nav_has_personalization_reset_controls(self):
        for token in (
            "مسح المفضلة",
            "إعادة ترتيب الاستخدام",
            "clearFavorites",
            "resetUsageOrdering",
            "navPersonalizationControls",
        ):
            self.assertIn(token, PAGE)

    def test_personalization_resets_only_ui_preferences(self):
        for token in (
            "dashboardPrefs.favorites=[]",
            "dashboardPrefs.navUsage={}",
            "persistDashboardPrefs()",
            "renderFavoriteGroup()",
            "sortNavGroupsByUsage()",
        ):
            self.assertIn(token, PAGE)
        self.assertNotIn("fetch('/api/", PAGE[PAGE.find("function clearFavorites"):PAGE.find("function decorateFavoriteControls")])


    def test_mobile_nav_shows_favorites_count(self):
        for token in (
            "favoriteCountBadge",
            "updateFavoriteCount",
            "المفضلة",
            "(dashboardPrefs.favorites||[]).length",
        ):
            self.assertIn(token, PAGE)

    def test_mobile_nav_can_disable_smart_sort_without_losing_usage(self):
        for token in (
            "smartSortEnabled:true",
            "parsed.smartSortEnabled",
            "dashboardPrefs.smartSortEnabled",
            "toggleSmartSort",
            "الترتيب الذكي",
            "sortNavGroupsByUsage",
            "dataset.originalIndex",
        ):
            self.assertIn(token, PAGE)

    def test_smart_sort_off_preserves_usage_history(self):
        start = PAGE.find("function toggleSmartSort")
        end = PAGE.find("function resetUsageOrdering")
        snippet = PAGE[start:end]
        self.assertIn("dashboardPrefs.smartSortEnabled", snippet)
        self.assertIn("persistDashboardPrefs()", snippet)
        self.assertNotIn("dashboardPrefs.navUsage={}", snippet)

if __name__ == "__main__":
    unittest.main()
