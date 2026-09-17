import unittest

from app.lesson_presentation_studio_ui import _enhance_pack_preview, _workspace
from app.services.lesson_presentation_blueprint import build_presentation_blueprint
from app.services.lesson_presentation_pptx import pptx_preflight, render_presentation_pptx


class LessonPresentationWorkspaceTests(unittest.TestCase):
    REF = "ملف 1: lesson.pdf · صفحة 1"

    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["يطبق قانون أوم"],
            "summary": "يربط القانون بين الجهد والتيار والمقاومة.",
            "sections": [
                {"heading": "الفكرة", "body": "العلاقة V = IR تربط الكميات الكهربائية.", "source_refs": [self.REF]}
            ],
            "equations_or_rules": [
                {"label": "قانون أوم", "expression": "V = IR", "notes": "", "source_refs": [self.REF]}
            ],
            "worked_examples": [],
            "source_visuals": [],
            "diagram_specs": [],
            "practice_questions": [
                {"id": "Q1", "prompt": "اختر العلاقة الصحيحة", "answer": "V = IR", "explanation": "مدعومة بالمصدر", "source_refs": [self.REF]}
            ],
            "common_mistakes": [],
            "quick_revision": [{"text": "V = IR", "source_refs": [self.REF]}],
        }

    def test_student_pptx_is_valid_and_matches_blueprint_slide_count(self):
        blueprint = build_presentation_blueprint(
            self._pack(),
            {"mode": "lesson_explanation", "audience": "student", "language": "ar", "length": "medium"},
            source_lesson_pack_id="pack-1",
        )
        data = render_presentation_pptx(blueprint, "student")
        report = pptx_preflight(data, len(blueprint["slides"]))
        self.assertTrue(report["ready"], report)
        self.assertGreater(len(data), 1000)

    def test_teacher_pptx_is_valid(self):
        blueprint = build_presentation_blueprint(
            self._pack(),
            {"mode": "question_driven", "audience": "teacher", "language": "ar", "length": "short"},
            source_lesson_pack_id="pack-1",
        )
        data = render_presentation_pptx(blueprint, "teacher")
        report = pptx_preflight(data, len(blueprint["slides"]))
        self.assertTrue(report["ready"], report)

    def test_workspace_exposes_blueprint_and_both_exports(self):
        html = _workspace("job-1")
        self.assertIn("Lesson Presentation Studio", html)
        self.assertIn("presentation/blueprint", html)
        self.assertIn("export-pptx/'+edition", html)
        self.assertIn("20 بطاقة", html)

    def test_lesson_pack_preview_gets_presentation_link(self):
        source = '<div class=box><a href="/admin/lesson-pack-studio">Lesson Pack Studio</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>'
        html = _enhance_pack_preview(source, "job-1")
        self.assertIn("/admin/lesson-pack-studio/jobs/job-1/presentation", html)

    def test_routes_are_registered(self):
        import index

        paths = {route.path for route in index.app.routes}
        self.assertIn("/admin/lesson-pack-studio/jobs/{job_id}/presentation", paths)
        self.assertIn("/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/export-pptx/{edition}", paths)


if __name__ == "__main__":
    unittest.main()
