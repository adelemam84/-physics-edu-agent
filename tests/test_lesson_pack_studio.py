from __future__ import annotations

import inspect
import unittest

from app import content_phase_guard, lesson_pack_guard, lesson_pack_studio
from app.services import lesson_pack_core


class LessonPackStudioTests(unittest.TestCase):
    def test_lesson_pack_gate_is_independent_from_curriculum_gate(self):
        env = {
            "VERCEL_ENV": "production",
            "CONTENT_INGESTION_ENABLED": "false",
        }
        self.assertFalse(content_phase_guard.content_ingestion_enabled(env))
        self.assertTrue(lesson_pack_guard.lesson_pack_ingestion_enabled(env))

    def test_lesson_pack_gate_can_be_disabled_explicitly(self):
        self.assertFalse(
            lesson_pack_guard.lesson_pack_ingestion_enabled(
                {"LESSON_PACK_INGESTION_ENABLED": "false"}
            )
        )

    def test_lesson_pack_upload_uses_dedicated_guard(self):
        source = inspect.getsource(lesson_pack_studio.create_lesson_pack_job)
        self.assertIn("require_lesson_pack_ingestion_enabled()", source)
        self.assertNotIn("require_content_ingestion_enabled()", source)

    def test_source_ref_is_page_precise(self):
        ref = lesson_pack_core.source_ref(
            {
                "file_index": 2,
                "original_filename": "lesson.pdf",
                "original_page": 7,
            }
        )
        self.assertEqual(ref, "ملف 2: lesson.pdf · صفحة 7")

    def test_generated_questions_can_never_enter_official_bank(self):
        pack = lesson_pack_core.normalize_generated_questions(
            {
                "practice_questions": [
                    {
                        "prompt": "ما العلاقة؟",
                        "answer": "إجابة",
                        "source_refs": ["ملف 1: a.pdf · صفحة 1"],
                    }
                ]
            }
        )
        question = pack["practice_questions"][0]
        self.assertTrue(question["generated"])
        self.assertFalse(question["official_question_bank"])
        self.assertFalse(question["question_bank_eligible"])
        self.assertTrue(question["teacher_review_required"])
        self.assertFalse(pack["question_policy"]["official_question_bank_write"])

    def test_provenance_validation_rejects_unknown_or_missing_refs(self):
        good = "ملف 1: a.pdf · صفحة 1"
        pack = {
            "sections": [{"heading": "أ", "body": "ب", "source_refs": [good]}],
            "practice_questions": [
                {"prompt": "س1", "source_refs": [good]},
                {"prompt": "س2", "source_refs": []},
                {"prompt": "س3", "source_refs": ["مصدر غير معروف"]},
            ],
        }
        result = lesson_pack_core.validate_pack_provenance(pack, [good])
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["invalid_refs"]), 1)
        self.assertIn("practice_questions[2]", result["missing_refs"])

    def test_student_pdf_payload_hides_answers(self):
        pack = {
            "title": "قانون أوم",
            "subject": "physics",
            "grade_label": "الثالث الثانوي",
            "sections": [
                {
                    "heading": "القانون",
                    "body": "V = IR",
                    "source_refs": ["ملف 1: a.pdf · صفحة 1"],
                }
            ],
            "practice_questions": [
                {
                    "prompt": "اكتب القانون",
                    "answer": "V = IR",
                    "explanation": "من المصدر",
                    "difficulty": "easy",
                    "source_refs": ["ملف 1: a.pdf · صفحة 1"],
                }
            ],
            "summary": "ملخص",
        }
        student = lesson_pack_core.render_payload(pack, "student")
        teacher = lesson_pack_core.render_payload(pack, "teacher")
        student_text = "\n".join(
            str(item.get("body") or "") for item in student["sections"]
        )
        teacher_text = "\n".join(
            str(item.get("body") or "") for item in teacher["sections"]
        )
        student_headings = " ".join(
            str(item.get("heading") or "") for item in student["sections"]
        )
        teacher_headings = " ".join(
            str(item.get("heading") or "") for item in teacher["sections"]
        )
        self.assertNotIn("نموذج الإجابة", student_headings)
        self.assertNotIn("الإجابة: V = IR", student_text)
        self.assertIn("نموذج الإجابة والتفسير", teacher_headings)
        self.assertIn("الإجابة: V = IR", teacher_text)

    def test_teacher_and_student_editions_render_valid_pdf(self):
        pack = {
            "title": "درس تجريبي",
            "subject": "physics",
            "grade_label": "الثالث الثانوي",
            "mode": "student_simple",
            "learning_objectives": ["فهم الفكرة"],
            "sections": [
                {
                    "heading": "تعريف",
                    "body": "شرح من المصدر.",
                    "source_refs": ["ملف 1: a.pdf · صفحة 1"],
                }
            ],
            "practice_questions": [
                {
                    "prompt": "سؤال تدريبي؟",
                    "options": ["أ", "ب"],
                    "answer": "أ",
                    "explanation": "تفسير",
                    "difficulty": "easy",
                    "source_refs": ["ملف 1: a.pdf · صفحة 1"],
                }
            ],
            "summary": "ملخص",
        }
        for edition in ("student", "teacher"):
            with self.subTest(edition=edition):
                data = lesson_pack_core.render_pdf(pack, edition)
                self.assertTrue(data.startswith(b"%PDF"))
                self.assertGreater(len(data), 500)


if __name__ == "__main__":
    unittest.main()
