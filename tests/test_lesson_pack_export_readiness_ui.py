import unittest
from unittest.mock import patch

from app import lesson_pack_export_readiness_ui as readiness_ui
from app import lesson_pack_student_handout_runtime as runtime


class LessonPackExportReadinessTests(unittest.TestCase):
    def _pack_report(self, ready=True):
        return {
            "kind": "lesson_pack",
            "ready": ready,
            "blocking_failures": [] if ready else ["generated_practice_policy"],
            "checks": [],
        }

    def _pdf_report(self, ready=True):
        return {
            "kind": "lesson_pack_pdf",
            "ready": ready,
            "blocking_failures": [] if ready else ["student_navigation_contract"],
            "checks": [],
            "page_count": 5,
        }

    def test_preflight_ready_does_not_bypass_teacher_approval(self):
        job = {"pack_json": {"title": "pack"}, "teacher_approved": False}
        with patch.object(runtime.lesson_pack_studio, "_job", return_value=(job, [])), \
             patch.object(runtime.lesson_pack_studio, "allowed_source_refs", return_value=[]), \
             patch.object(runtime, "pack_preflight", return_value=self._pack_report()), \
             patch.object(runtime, "_render_lesson_pack_pdf_unchecked", return_value=b"%PDF-test"), \
             patch.object(runtime, "pdf_preflight", return_value=self._pdf_report()):
            result = runtime.lesson_pack_export_preflight("job-1", "student")
        self.assertTrue(result["ready"])
        self.assertTrue(result["preflight_ready"])
        self.assertFalse(result["teacher_approved"])
        self.assertFalse(result["export_ready"])
        self.assertFalse(result["official_question_bank_write"])
        self.assertTrue(result["content_ingestion_unchanged"])

    def test_teacher_approved_and_preflight_ready_allows_export_readiness(self):
        job = {"pack_json": {"title": "pack"}, "teacher_approved": True}
        with patch.object(runtime.lesson_pack_studio, "_job", return_value=(job, [])), \
             patch.object(runtime.lesson_pack_studio, "allowed_source_refs", return_value=[]), \
             patch.object(runtime, "pack_preflight", return_value=self._pack_report()), \
             patch.object(runtime, "_render_lesson_pack_pdf_unchecked", return_value=b"%PDF-test"), \
             patch.object(runtime, "pdf_preflight", return_value=self._pdf_report()):
            result = runtime.lesson_pack_export_preflight("job-2", "teacher")
        self.assertTrue(result["preflight_ready"])
        self.assertTrue(result["teacher_approved"])
        self.assertTrue(result["export_ready"])

    def test_failed_pack_preflight_never_renders_pdf_or_allows_export(self):
        job = {"pack_json": {"title": "pack"}, "teacher_approved": True}
        with patch.object(runtime.lesson_pack_studio, "_job", return_value=(job, [])), \
             patch.object(runtime.lesson_pack_studio, "allowed_source_refs", return_value=[]), \
             patch.object(runtime, "pack_preflight", return_value=self._pack_report(False)), \
             patch.object(runtime, "_render_lesson_pack_pdf_unchecked") as render_mock:
            result = runtime.lesson_pack_export_preflight("job-3", "student")
        render_mock.assert_not_called()
        self.assertFalse(result["preflight_ready"])
        self.assertFalse(result["export_ready"])
        self.assertIn("generated_practice_policy", result["pack"]["blocking_failures"])

    def test_preview_ui_exposes_student_and_teacher_readiness_without_removing_server_gate(self):
        html = readiness_ui._preview_page_with_export_readiness("job-ui")
        self.assertIn("جاهزية التصدير النهائي", html)
        self.assertIn("preflight?edition='+edition", html)
        self.assertIn("student&&student.export_ready", html)
        self.assertIn("teacher&&teacher.export_ready", html)
        self.assertIn("/export-pdf?edition=student", html)
        self.assertIn("/export-pdf?edition=teacher", html)
        self.assertIn("official", "official")  # no generated official-bank action is introduced

    def test_ui_patch_fails_closed_when_upstream_template_anchor_changes(self):
        source = "<html><body>upstream changed</body></html>"
        self.assertEqual(readiness_ui.enhance_lesson_pack_preview_html(source), source)


if __name__ == "__main__":
    unittest.main()
