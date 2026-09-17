import unittest

import fitz

from app.services.lesson_pack_pdf_navigation import (
    _marker_token,
    final_review_html,
    navigation_index_html,
    navigation_items,
    normalize_final_review_settings,
    question_navigation_html,
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
                {"prompt": "ما العلاقة؟", "options": ["طردية", "عكسية"], "difficulty": "easy"},
                {"prompt": "احسب التيار", "options": [], "difficulty": "medium"},
                {"prompt": "قارن بين حالتين", "options": [], "difficulty": "hard"},
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

    def test_final_review_defaults_follow_pack_mode_without_new_science(self):
        pack = self._pack()
        pack["pack_mode"] = "exam_revision"
        settings = normalize_final_review_settings(pack)
        self.assertEqual(settings["style"], "exam_focus")
        review = final_review_html(pack)
        self.assertIn("مراجعة ما قبل الاختبار", review)
        self.assertIn(pack["summary"], review)
        self.assertIn(pack["equations_or_rules"][0]["expression"], review)

    def test_custom_final_review_can_hide_sections_and_change_heading(self):
        pack = self._pack()
        pack["final_review"] = {
            "style": "concept_focus",
            "title": "راجع الفكرة الأساسية",
            "lead": "ثبت فهمك قبل التدريب.",
            "show_summary": True,
            "show_quick_revision": True,
            "show_laws": False,
            "show_mistakes": False,
            "show_checklist": False,
        }
        review = final_review_html(pack)
        self.assertIn("راجع الفكرة الأساسية", review)
        self.assertIn("ثبت فهمك قبل التدريب", review)
        self.assertIn(pack["summary"], review)
        self.assertNotIn("قوانين سريعة", review)
        self.assertNotIn("قبل الامتحان: تجنب", review)
        self.assertNotIn("تأكد قبل ما تقفل الملزمة", review)
        self.assertEqual(navigation_items(pack)[-1].label, "راجع الفكرة الأساسية")

    def test_question_map_html_is_visible_and_has_every_question(self):
        html = question_navigation_html(self._pack())
        self.assertIn("خريطة الأسئلة", html)
        self.assertIn("سؤال 1", html)
        self.assertIn("سؤال 2", html)
        self.assertIn("سؤال 3", html)

    def test_raw_pdf_contains_main_and_question_navigation_markers(self):
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
                if item.anchor == "nav-final-review":
                    continue
                token = _marker_token("T", item.anchor)
                if token not in extracted:
                    missing.append(token)
            if _marker_token("M", "nav-question-map") not in extracted:
                missing.append(_marker_token("M", "nav-question-map"))
            for number in range(1, 4):
                anchor = f"nav-question-{number}"
                for role in ("S", "T", "B"):
                    token = _marker_token(role, anchor)
                    if token not in extracted:
                        missing.append(token)
            self.assertEqual(missing, [], f"Missing raw navigation markers: {missing}")
        finally:
            doc.close()

    def test_student_pdf_has_main_and_question_outline_and_internal_links(self):
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
            for number in range(1, 4):
                rows = [row for row in toc if row[1] == f"سؤال {number}"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], 2)

            links = [
                link
                for page in doc
                for link in page.get_links()
                if link.get("kind") == fitz.LINK_GOTO
            ]
            self.assertGreaterEqual(len(links), len(expected_labels) + 6)
            extracted = "\n".join(page.get_text() for page in doc)
            for marker_prefix in ("LPNI", "LPNT", "LPNS", "LPNB", "LPNM"):
                self.assertNotIn(marker_prefix, extracted)
        finally:
            doc.close()

    def test_question_navigation_has_forward_and_return_destinations(self):
        data = render_enhanced_student_handout_pdf(self._pack())
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            toc = doc.get_toc()
            question_pages = {
                row[1]: int(row[2]) - 1
                for row in toc
                if row[0] == 2 and row[1].startswith("سؤال ")
            }
            self.assertEqual(set(question_pages), {"سؤال 1", "سؤال 2", "سؤال 3"})
            all_links = [
                (page_index, link)
                for page_index, page in enumerate(doc)
                for link in page.get_links()
                if link.get("kind") == fitz.LINK_GOTO
            ]
            for page_index in question_pages.values():
                self.assertTrue(any(int(link.get("page")) == page_index for _, link in all_links))
            first_question_page = min(question_pages.values())
            return_targets = [int(link.get("page")) for _, link in all_links if int(link.get("page")) < first_question_page]
            self.assertTrue(return_targets)
        finally:
            doc.close()

    def test_final_review_is_the_last_page_and_navigation_targets_it(self):
        pack = self._pack()
        pack["final_review"] = {
            "style": "balanced",
            "title": "مراجعة الدرس الأخيرة",
            "lead": "راجع ثم حل.",
        }
        data = render_enhanced_student_handout_pdf(pack)
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            toc = doc.get_toc()
            final_rows = [row for row in toc if row[1] == "مراجعة الدرس الأخيرة"]
            self.assertEqual(len(final_rows), 1)
            self.assertEqual(int(final_rows[0][2]), doc.page_count)
            pages_linking_to_final = [
                i
                for i, page in enumerate(doc)
                if any(
                    link.get("kind") == fitz.LINK_GOTO
                    and int(link.get("page")) == doc.page_count - 1
                    for link in page.get_links()
                )
            ]
            self.assertEqual(len(pages_linking_to_final), 1)
        finally:
            doc.close()

    def test_no_practice_pack_still_renders_without_question_navigation(self):
        pack = self._pack()
        pack["practice_questions"] = []
        data = render_enhanced_student_handout_pdf(pack)
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            labels = [row[1] for row in doc.get_toc()]
            self.assertNotIn("تدريبات الدرس", labels)
            self.assertFalse(any(label.startswith("سؤال ") for label in labels))
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
