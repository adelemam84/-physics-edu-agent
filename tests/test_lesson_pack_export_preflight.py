import copy
import unittest

import fitz
from fastapi import HTTPException

from app.lesson_pack_student_handout_runtime import (
    _render_lesson_pack_pdf,
    _render_lesson_pack_pdf_unchecked,
)
from app.services.lesson_pack_export_preflight import pack_preflight, pdf_preflight
from app.services.lesson_pack_student_handout_v2 import render_enhanced_student_handout_pdf


class LessonPackExportPreflightTests(unittest.TestCase):
    SOURCE_REF = "ملف 1: lesson.pdf · صفحة 1"

    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "pack_mode": "balanced",
            "learning_objectives": ["يطبق قانون أوم"],
            "sections": [
                {
                    "heading": "الفكرة",
                    "body": "يربط قانون أوم بين الجهد والتيار والمقاومة.",
                    "source_refs": [self.SOURCE_REF],
                }
            ],
            "key_terms": [],
            "equations_or_rules": [
                {
                    "label": "قانون أوم",
                    "expression": "V = I × R",
                    "notes": "",
                    "source_refs": [self.SOURCE_REF],
                }
            ],
            "worked_examples": [],
            "common_mistakes": [],
            "diagram_specs": [],
            "source_visuals": [],
            "practice_layout": {"self_test_count": 3, "show_answer_sheet": True},
            "practice_questions": [
                {
                    "id": "E1",
                    "type": "mcq",
                    "difficulty": "easy",
                    "prompt": "اختر العلاقة الصحيحة E1",
                    "options": ["V = IR", "V = I/R"],
                    "answer": "V = IR",
                    "explanation": "الإجابة تدريبية ومبنية على العلاقة الموجودة في المصدر.",
                    "source_refs": [self.SOURCE_REF],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                    "teacher_review_required": True,
                },
                {
                    "id": "M1",
                    "type": "calculation",
                    "difficulty": "medium",
                    "prompt": "احسب قيمة التيار M1",
                    "options": [],
                    "answer": "2 A",
                    "explanation": "أرقام تدريبية مولدة والعلاقة المستخدمة مدعومة بالمصدر.",
                    "source_refs": [self.SOURCE_REF],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                    "teacher_review_required": True,
                },
                {
                    "id": "H1",
                    "type": "conceptual",
                    "difficulty": "hard",
                    "prompt": "فسر العلاقة H1",
                    "options": [],
                    "answer": "تفسير تدريبي",
                    "explanation": "تفسير تدريبي مولد من محتوى الدرس فقط.",
                    "source_refs": [self.SOURCE_REF],
                    "generated": True,
                    "provenance": "ai_generated_source_grounded_practice",
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                    "teacher_review_required": True,
                },
            ],
            "quick_revision": [{"text": "V = I × R", "source_refs": [self.SOURCE_REF]}],
            "uncertain_items": [],
            "summary": "قانون أوم يربط الجهد والتيار والمقاومة.",
            "question_policy": {
                "generated_practice_only": True,
                "official_question_bank_write": False,
                "auto_publish": False,
                "teacher_review_required": True,
            },
            "artifact_policy": {
                "artifact_kind": "lesson_pack",
                "source_grounded_only": True,
                "generated_explanations_allowed": True,
                "generated_practice_questions_allowed": True,
                "official_question_bank_write": False,
                "teacher_approval_required_for_final_export": True,
                "generated_visuals_must_be_labeled": True,
            },
        }

    def test_pack_preflight_is_ready_and_non_mutating(self):
        pack = self._pack()
        original = copy.deepcopy(pack)
        report = pack_preflight(pack, [self.SOURCE_REF])
        self.assertTrue(report["ready"], report)
        self.assertEqual(pack, original)
        self.assertEqual(report["blocking_failures"], [])

    def test_pack_preflight_blocks_official_question_policy_drift(self):
        pack = self._pack()
        pack["practice_questions"][0]["official_question_bank"] = True
        report = pack_preflight(pack, [self.SOURCE_REF])
        self.assertFalse(report["ready"])
        self.assertIn("generated_practice_policy", report["blocking_failures"])

    def test_pack_preflight_blocks_unreviewed_source_visual(self):
        pack = self._pack()
        pack["source_visuals"] = [
            {
                "id": "visual-1",
                "source_refs": [self.SOURCE_REF],
                "review_required": True,
                "approved": False,
                "rejected": False,
            }
        ]
        report = pack_preflight(pack, [self.SOURCE_REF])
        self.assertFalse(report["ready"])
        self.assertIn("source_visual_review_complete", report["blocking_failures"])

    def test_student_pdf_passes_navigation_and_practice_preflight(self):
        pack = self._pack()
        data = render_enhanced_student_handout_pdf(pack)
        report = pdf_preflight(data, pack, "student")
        self.assertTrue(report["ready"], report)
        self.assertGreater(report["page_count"], 0)

    def test_teacher_pdf_has_separate_answer_appendix(self):
        pack = self._pack()
        data = _render_lesson_pack_pdf_unchecked(pack, "teacher")
        report = pdf_preflight(data, pack, "teacher")
        self.assertTrue(report["ready"], report)

    def test_pdf_preflight_blocks_non_a4_output(self):
        doc = fitz.open()
        try:
            doc.new_page(width=300, height=300)
            data = doc.tobytes()
        finally:
            doc.close()
        report = pdf_preflight(data, self._pack(), "student")
        self.assertFalse(report["ready"])
        self.assertIn("a4_page_geometry", report["blocking_failures"])

    def test_runtime_gate_rejects_policy_drift_before_rendering(self):
        pack = self._pack()
        pack["question_policy"]["official_question_bank_write"] = True
        with self.assertRaises(HTTPException) as ctx:
            _render_lesson_pack_pdf(pack, "student")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("generated_practice_policy", ctx.exception.detail["preflight"]["blocking_failures"])

    def test_preflight_admin_route_is_registered(self):
        import index

        paths = {route.path for route in index.app.routes}
        self.assertIn(
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preflight",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
