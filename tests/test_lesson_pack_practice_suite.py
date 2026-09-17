import unittest

import fitz

from app.services.lesson_pack_practice_layout import (
    answer_sheet_html,
    decorate_practice_html,
    prepare_practice_pack,
    self_test_html,
    self_test_items,
    teacher_self_test_key_html,
)
from app.services.lesson_pack_student_handout_v2 import render_enhanced_student_handout_pdf
from app.services.lesson_pack_student_renderer import _document_html
from app.services.lesson_pack_teacher_practice_appendix import _render_appendix


class LessonPackPracticeSuiteTests(unittest.TestCase):
    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["يطبق قانون أوم"],
            "sections": [{"heading": "الفكرة", "body": "يربط قانون أوم بين V و I و R."}],
            "equations_or_rules": [{"label": "قانون أوم", "expression": "V = I × R", "notes": ""}],
            "worked_examples": [],
            "common_mistakes": [],
            "practice_layout": {"self_test_count": 4, "show_answer_sheet": True},
            "practice_questions": [
                {
                    "id": "H1",
                    "difficulty": "hard",
                    "prompt": "حل المسألة المتقدمة H1",
                    "options": [],
                    "answer": "SECRET_ANSWER_H1",
                    "explanation": "SECRET_EXPLANATION_H1",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                },
                {
                    "id": "E1",
                    "difficulty": "easy",
                    "prompt": "اختر العلاقة الصحيحة E1",
                    "options": ["A", "B", "C"],
                    "answer": "SECRET_ANSWER_E1",
                    "explanation": "SECRET_EXPLANATION_E1",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                },
                {
                    "id": "M1",
                    "difficulty": "medium",
                    "prompt": "احسب قيمة التيار M1",
                    "options": [],
                    "answer": "SECRET_ANSWER_M1",
                    "explanation": "SECRET_EXPLANATION_M1",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                },
                {
                    "id": "E2",
                    "difficulty": "easy",
                    "prompt": "سؤال تأسيسي ثان E2",
                    "options": ["A", "B"],
                    "answer": "SECRET_ANSWER_E2",
                    "explanation": "SECRET_EXPLANATION_E2",
                    "source_refs": ["ملف 1: lesson.pdf · صفحة 1"],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                },
            ],
            "quick_revision": [{"text": "V = I × R"}],
            "summary": "قانون أوم يربط الجهد والتيار والمقاومة.",
            "question_policy": {
                "generated_practice_only": True,
                "official_question_bank_write": False,
                "auto_publish": False,
                "teacher_review_required": True,
            },
        }

    def test_practice_order_is_stable_and_does_not_mutate_persisted_pack(self):
        pack = self._pack()
        original_ids = [q["id"] for q in pack["practice_questions"]]
        rendered = prepare_practice_pack(pack)
        self.assertEqual(original_ids, ["H1", "E1", "M1", "E2"])
        self.assertEqual([q["id"] for q in pack["practice_questions"]], original_ids)
        self.assertEqual([q["id"] for q in rendered["practice_questions"]], ["E1", "E2", "M1", "H1"])

    def test_self_test_is_balanced_deterministic_and_subset_only(self):
        rendered = prepare_practice_pack(self._pack())
        selected = self_test_items(rendered)
        self.assertEqual([item["question"]["id"] for item in selected], ["E1", "M1", "H1", "E2"])
        source_ids = {q["id"] for q in rendered["practice_questions"]}
        self.assertTrue(all(item["question"]["id"] in source_ids for item in selected))
        self.assertEqual(len(selected), 4)

    def test_student_html_groups_levels_and_has_separate_self_test_and_answer_sheet(self):
        rendered = prepare_practice_pack(self._pack())
        html = decorate_practice_html(_document_html(rendered), rendered)
        self.assertIn("المستوى الأول", html)
        self.assertIn("المستوى الثاني", html)
        self.assertIn("المستوى المتقدم", html)
        self.assertIn("اختبر نفسك", html)
        self.assertIn("ورقة إجابة الطالب", html)
        self.assertIn("اختر العلاقة الصحيحة E1", html)
        self.assertNotIn("SECRET_ANSWER_E1", html)
        self.assertNotIn("SECRET_EXPLANATION_E1", html)

    def test_student_self_test_and_answer_sheet_never_render_answers(self):
        rendered = prepare_practice_pack(self._pack())
        student_html = self_test_html(rendered) + answer_sheet_html(rendered)
        for question in rendered["practice_questions"]:
            self.assertNotIn(question["answer"], student_html)
            self.assertNotIn(question["explanation"], student_html)

    def test_teacher_key_is_separate_and_contains_answer_explanation_and_source(self):
        rendered = prepare_practice_pack(self._pack())
        key_html = teacher_self_test_key_html(rendered)
        self.assertIn("نسخة المدرس فقط", key_html)
        self.assertIn("SECRET_ANSWER_E1", key_html)
        self.assertIn("SECRET_EXPLANATION_E1", key_html)
        self.assertIn("lesson.pdf", key_html)
        data = _render_appendix(rendered)
        self.assertTrue(data.startswith(b"%PDF"))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            text = "\n".join(page.get_text() for page in doc)
            self.assertIn("SECRET_ANSWER_E1", text)
            self.assertIn("SECRET_EXPLANATION_E1", text)
        finally:
            doc.close()

    def test_rendering_preserves_generated_practice_policy(self):
        pack = self._pack()
        rendered = prepare_practice_pack(pack)
        self.assertEqual(rendered["question_policy"], pack["question_policy"])
        self.assertFalse(rendered["question_policy"]["official_question_bank_write"])
        for question in rendered["practice_questions"]:
            self.assertTrue(question["generated"])
            self.assertFalse(question["official_question_bank"])
            self.assertFalse(question["question_bank_eligible"])

    def test_final_student_pdf_is_valid_and_hides_answer_secrets(self):
        data = render_enhanced_student_handout_pdf(self._pack())
        self.assertTrue(data.startswith(b"%PDF"))
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            text = "\n".join(page.get_text() for page in doc)
            for token in (
                "SECRET_ANSWER_E1",
                "SECRET_ANSWER_E2",
                "SECRET_ANSWER_M1",
                "SECRET_ANSWER_H1",
                "SECRET_EXPLANATION_E1",
            ):
                self.assertNotIn(token, text)
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
