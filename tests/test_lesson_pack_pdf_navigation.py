import unittest

import fitz

from app.services.lesson_pack_pdf_navigation import final_review_html, navigation_index_html
from app.services.lesson_pack_student_renderer import render_student_handout_pdf


class LessonPackPdfNavigationTests(unittest.TestCase):
    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "cover": {"student_name": "طالب تجريبي", "class_label": "3/أ"},
            "learning_objectives": ["يربط بين الجهد والتيار والمقاومة"],
            "sections": [
                {"heading": "العلاقة بين الجهد والتيار", "body": "يزداد التيار بزيادة الجهد عند ثبات المقاومة."},
                {"heading": "المقاومة الكهربائية", "body": "تحدد المقاومة مقدار التيار المار في الدائرة."},
            ],
            "equations_or_rules": [
                {"label": "قانون أوم", "expression": "V = I × R", "notes": "استخدم وحدات SI"}
            ],
            "worked_examples": [
                {"title": "مثال", "problem": "احسب V", "solution_steps": ["عوّض في القانون"], "answer": "6 V"}
            ],
            "common_mistakes": [{"text": "خلط وحدة المقاومة بوحدة التيار"}],
            "practice_questions": [
                {"prompt": "ما العلاقة؟", "options": ["طردية", "عكسية"], "difficulty": "easy"}
            ],
            "quick_revision": [{"text": "V = I × R"}],
            "summary": "قانون أوم يربط الجهد بالتيار والمقاومة.",
        }

    def test_index_and_final_review_are_grounded_in_pack(self):
        pack = self._pack()
        index = navigation_index_html(pack)
        review = final_review_html(pack)
        self.assertIn("فهرس الملزمة", index)
        self.assertIn("العلاقة بين الجهد والتيار", index)
        self.assertIn("المراجعة النهائية", review)
        self.assertIn("V = I × R", review)
        self.assertIn("خلط وحدة المقاومة", review)
        self.assertIn("قانون أوم يربط الجهد", review)

    def test_student_pdf_has_outline_and_internal_links(self):
        data = render_student_handout_pdf(self._pack())
        self.assertTrue(data.startswith(b"%PDF"))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            text = "\n".join(page.get_text() for page in doc)
            self.assertIn("فهرس الملزمة", text)
            self.assertIn("المراجعة النهائية", text)
            toc = doc.get_toc()
            self.assertGreaterEqual(len(toc), 3)
            self.assertTrue(any(row[1] == "تدريبات الدرس" for row in toc))
            index_page = None
            for page in doc:
                if "فهرس الملزمة" in page.get_text():
                    index_page = page
                    break
            self.assertIsNotNone(index_page)
            links = index_page.get_links()
            self.assertTrue(any(link.get("kind") == fitz.LINK_GOTO for link in links))
        finally:
            doc.close()

    def test_final_review_is_after_index(self):
        data = render_student_handout_pdf(self._pack())
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            index_pages = []
            review_pages = []
            for i, page in enumerate(doc):
                txt = page.get_text()
                if "فهرس الملزمة" in txt:
                    index_pages.append(i)
                if "المراجعة النهائية" in txt:
                    review_pages.append(i)
            self.assertEqual(len(index_pages), 1)
            self.assertGreaterEqual(len(review_pages), 1)
            self.assertGreater(review_pages[-1], index_pages[0])
        finally:
            doc.close()
