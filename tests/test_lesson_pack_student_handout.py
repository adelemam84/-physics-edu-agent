from __future__ import annotations

import inspect
import unittest

import fitz

from app import lesson_pack_student_handout_runtime, lesson_pack_studio
from app.services import lesson_pack_student_renderer
from app.services.lesson_pack_student_renderer import render_student_handout_pdf


class LessonPackStudentHandoutTests(unittest.TestCase):
    def _pack(self) -> dict:
        return {
            "title": "قانون أوم",
            "subject": "physics",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["فهم العلاقة بين الجهد والتيار والمقاومة"],
            "sections": [
                {
                    "heading": "الفكرة الأساسية",
                    "body": "يوضح الدرس العلاقة بين الجهد والتيار والمقاومة.",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "key_terms": [
                {
                    "term": "المقاومة",
                    "definition": "مقدار يصف ممانعة مرور التيار.",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "equations_or_rules": [
                {
                    "label": "قانون أوم",
                    "expression": "V = I R",
                    "notes": "استخدم الوحدات القياسية.",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "worked_examples": [
                {
                    "title": "حساب فرق الجهد",
                    "problem": "إذا كانت I = 2 A و R = 6 Ω احسب V.",
                    "solution_steps": ["نكتب V = IR", "نعوض بالقيم"],
                    "answer": "12 V",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "common_mistakes": [
                {
                    "text": "لا تخلط بين الجهد والتيار.",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "practice_questions": [
                {
                    "prompt": "احسب المقاومة عند V = 10 V و I = 2 A.",
                    "difficulty": "medium",
                    "options": [],
                    "answer": "PRACTICE_SECRET_5_OHM",
                    "explanation": "R = V/I",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "quick_revision": [
                {
                    "text": "V = IR",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                }
            ],
            "summary": "اربط بين الكميات الثلاث باستخدام قانون أوم.",
        }

    def _text(self, data: bytes) -> str:
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()

    def _normalized_text(self, data: bytes) -> str:
        # PDF layout engines may split a value and its unit across visual lines.
        # Normalize whitespace so the contract tests content, not extraction layout.
        return " ".join(self._text(data).split())

    def test_student_cover_is_a_dedicated_first_page_with_configurable_identity(self):
        pack = self._pack()
        pack["cover"] = {
            "student_name": "STUDENT_ADEL",
            "class_label": "CLASS_3A",
            "teacher_name": "TEACHER_NAME",
            "school_name": "SCHOOL_NAME",
            "academic_term": "TERM_2026",
        }
        data = render_student_handout_pdf(pack)
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            self.assertGreaterEqual(doc.page_count, 2)
            first = " ".join(doc[0].get_text().split())
            rest = " ".join(page.get_text() for page in doc[1:]).replace("\n", " ")
            self.assertIn("STUDENT_ADEL", first)
            self.assertIn("CLASS_3A", first)
            self.assertIn("TEACHER_NAME", first)
            self.assertIn("SCHOOL_NAME", first)
            self.assertIn("TERM_2026", first)
            self.assertIn("V = I R", rest)
        finally:
            doc.close()

    def test_explicit_empty_cover_class_stays_blank(self):
        pack = self._pack()
        pack["cover"] = {"class_label": ""}
        html = lesson_pack_student_renderer._document_html(pack)
        self.assertIn("الصف / الفصل", html)
        self.assertIn("blank-field", html)

    def test_cover_values_are_html_escaped(self):
        pack = self._pack()
        pack["cover"] = {"student_name": "<script>bad()</script>"}
        html = lesson_pack_student_renderer._document_html(pack)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()</script>", html)
        data = render_student_handout_pdf(pack)
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            self.assertEqual(sum(len(page.get_links()) for page in doc), 0)
        finally:
            doc.close()

    def test_student_handout_is_valid_a4_pdf(self):
        data = render_student_handout_pdf(self._pack())
        self.assertTrue(data.startswith(b"%PDF"))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            self.assertGreaterEqual(doc.page_count, 1)
            self.assertAlmostEqual(doc[0].rect.width, 595.0, delta=1.0)
            self.assertAlmostEqual(doc[0].rect.height, 842.0, delta=1.0)
        finally:
            doc.close()

    def test_student_sees_fully_solved_worked_example_but_not_practice_answer(self):
        text = self._normalized_text(render_student_handout_pdf(self._pack()))
        self.assertIn("12 V", text)
        self.assertNotIn("PRACTICE_SECRET_5_OHM", text)

    def test_student_copy_hides_internal_source_references(self):
        text = self._text(render_student_handout_pdf(self._pack()))
        self.assertNotIn("lesson.pdf", text)
        self.assertNotIn("ملف 1", text)

    def test_student_copy_contains_study_and_practice_surfaces(self):
        text = self._normalized_text(render_student_handout_pdf(self._pack()))
        self.assertIn("V = I R", text)
        self.assertIn("12 V", text)
        self.assertIn("10 V", text)

    def test_runtime_routes_student_export_to_dedicated_renderer(self):
        self.assertIn(
            "render_student_handout_pdf",
            inspect.getsource(lesson_pack_student_handout_runtime._render_lesson_pack_pdf),
        )
        self.assertIs(
            lesson_pack_studio.render_pdf,
            lesson_pack_student_handout_runtime._render_lesson_pack_pdf,
        )


if __name__ == "__main__":
    unittest.main()
