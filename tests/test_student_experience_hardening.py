from __future__ import annotations

from pathlib import Path
import unittest


class StudentExperienceHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portal = Path("app/student_portal.py").read_text(encoding="utf-8")
        cls.quiz = Path("app/student_quiz.py").read_text(encoding="utf-8")
        cls.diagnostics = Path("app/exam_diagnostics.py").read_text(encoding="utf-8")
        cls.study = Path("app/study_intelligence.py").read_text(encoding="utf-8")
        cls.command = Path("app/student_command_center.py").read_text(encoding="utf-8")

    def test_portal_login_is_form_based_session_only_and_uses_explicit_dom_refs(self):
        for token in (
            "id=studentLoginForm",
            'onsubmit="loginPortal(event)"',
            "const studentCodeInput=document.getElementById('code')",
            "const studentCodeInput=",
            "role=status",
            "table-wrap",
            "/api/student/session",
        ):
            self.assertIn(token, self.portal)
        self.assertNotIn("?student_code=", self.portal)
        self.assertNotIn("sessionStorage", self.portal)

    def test_exam_flushes_pending_autosaves_before_deadline_and_guards_submission(self):
        for token in (
            'onsubmit="startAttempt(event)"',
            'role="progressbar"',
            "async function flushPendingSaves()",
            "ms<=5000&&!expiryFlushTriggered",
            "submitInFlight",
            "unanswered&&!confirm(",
            "beforeunload",
        ):
            self.assertIn(token, self.quiz)
        self.assertNotIn("?student_code=", self.quiz)
        self.assertNotIn("sessionStorage", self.quiz)

    def test_exam_uses_explicit_dom_references_for_critical_controls(self):
        for token in (
            "sessionBadge=document.getElementById('sessionBadge')",
            "code=document.getElementById('code')",
            "submitBtn=document.getElementById('submitBtn')",
            "result=document.getElementById('result')",
        ):
            self.assertIn(token, self.quiz)

    def test_student_diagnostic_has_session_guard_responsive_tables_and_busy_action(self):
        for token in (
            "/api/student/session",
            "if(!s.authenticated){location.href='/student';return}",
            "table-wrap",
            "weakBtn.disabled=true",
            "role=status",
        ):
            self.assertIn(token, self.diagnostics)

    def test_study_queue_uses_session_guard_localized_status_and_inline_errors(self):
        for token in (
            "/api/student/session",
            "if(!ses.authenticated){location.href='/student';return}",
            "statusLabels=",
            "taskMsg",
            "button:disabled",
        ):
            self.assertIn(token, self.study)
        self.assertNotIn("alert(", self.study)

    def test_command_center_uses_explicit_status_and_output_references(self):
        self.assertIn(
            "const msg=document.getElementById('msg'),out=document.getElementById('out');",
            self.command,
        )
        self.assertIn("prefers-reduced-motion", self.command)

    def test_student_experience_does_not_add_commercial_or_content_ingestion_paths(self):
        combined = "\n".join(
            (self.portal, self.quiz, self.diagnostics, self.study, self.command)
        ).lower()
        for forbidden in (
            "subscription_plan",
            "billing_customer",
            "exam_credit",
            "paywall",
            "content_ingestion_enabled=true",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
