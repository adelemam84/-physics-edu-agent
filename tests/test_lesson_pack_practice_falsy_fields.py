import unittest

from app.services.lesson_pack_practice_layout import (
    _esc,
    _lines,
    self_test_html,
    teacher_self_test_key_html,
)


class LessonPackPracticeFalsyFieldTests(unittest.TestCase):
    def test_escape_preserves_non_null_falsy_values(self):
        self.assertEqual(_esc(None), "")
        self.assertEqual(_esc(0), "0")
        self.assertEqual(_esc(False), "False")
        self.assertEqual(_esc("<unsafe>"), "&lt;unsafe&gt;")
        self.assertEqual(_lines(0), "0")
        self.assertEqual(_lines(False), "False")

    def test_renderers_preserve_falsy_prompt_answer_and_explanation(self):
        pack = {
            "practice_layout": {"self_test_count": 1},
            "practice_questions": [
                {
                    "id": "E0",
                    "difficulty": "easy",
                    "prompt": 0,
                    "options": [],
                    "answer": False,
                    "explanation": 0,
                    "source_refs": ["lesson.pdf · page 1"],
                    "generated": True,
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                }
            ],
        }

        student_html = self_test_html(pack)
        teacher_html = teacher_self_test_key_html(pack)

        self.assertIn('<div class="self-test-prompt">0</div>', student_html)
        self.assertNotIn("False", student_html)
        self.assertIn("<b>الإجابة:</b> False", teacher_html)
        self.assertIn("<b>التفسير:</b> 0", teacher_html)
        self.assertIn("lesson.pdf", teacher_html)


if __name__ == "__main__":
    unittest.main()
