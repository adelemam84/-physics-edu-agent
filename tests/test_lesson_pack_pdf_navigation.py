import unittest

import fitz

from app.services.lesson_pack_pdf_navigation import (
    _marker_token,
    final_review_html,
    navigation_index_html,
    navigation_items,
)
from app.services.lesson_pack_student_handout_v2 import (
    _render_enhanced,
    render_enhanced_student_handout_pdf,
)


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
        self.assertIn("شرح الدرس", index)
        self.assertIn("تدريبات الدرس", index)
        self.assertIn("المراجعة النهائية", review)
        self.assertIn("V = I × R", review)
        self.assertIn("خلط وحدة المقاومة", review)
        self.assertIn("قانون أوم يربط الجهد", review)

    def test_raw_pdf_contains_index_and_every_target_marker(self):
        pack = self._pack()
        raw, _positions = _render_enhanced(pack)
        doc = fitz.open(stream=raw, filetype="pdf")
        try:
            extracted = "\n".join(page.get_text() for page in doc)
            missing = []
            index_token = _marker_token("I", "nav-index")
            if index_token not in extracted:
                missing.append(index_token)
            for item in navigation_items(pack):
                token = _marker_token("T", item.anchor)
                if token not in extracted:
                    missing.append(token)
            self.assertEqual(missing, [], f"Missing raw navigation markers: {missing}")
        finally:
            doc.close()

    def test_student_pdf_has_outline_and_internal_links(self):
        pack = self._pack()
        data = render_enhanced_student_handout_pdf(pack)
        self.assertTrue(data.startswith(b"%PDF"))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            toc = doc.get_toc()
            labels = [row[1] for row in toc]
            expected_labels = [item.label for item in navigation_items(pack)]
            for label in expected_labels:
                self.assertIn(label, labels)
            links = [
                link
                for page in doc
                for link in page.get_links()
                if link.get("kind") == fitz.LINK_GOTO
            ]
            self.assertEqual(len(links), len(expected_labels))
            extracted = "\n".join(page.get_text() for page in doc)
            self.assertNotIn("LPNI", extracted)
            self.assertNotIn("LPNT", extracted)
        finally:
            doc.close()

    def test_final_review_destination_is_after_index_page(self):
        data = render_enhanced_student_handout_pdf(self._pack())
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            index_pages = [
                i
                for i, page in enumerate(doc)
                if any(link.get("kind") == fitz.LINK_GOTO for link in page.get_links())
            ]
            self.assertEqual(len(index_pages), 1)
            toc = doc.get_toc()
            final_rows = [row for row in toc if row[1] == "المراجعة النهائية"]
            self.assertEqual(len(final_rows), 1)
            final_page_zero_based = int(final_rows[0][2]) - 1
            self.assertGreater(final_page_zero_based, index_pages[0])
        finally:
            doc.close()
