import copy
import unittest

from app.services.lesson_presentation_blueprint import (
    CARD_FEATURE_SPECS,
    build_presentation_blueprint,
    presentation_preflight,
    project_edition,
)


class LessonPresentationStudioTests(unittest.TestCase):
    REF = "ملف 1: lesson.pdf · صفحة 1"

    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["يشرح العلاقة بين الجهد والتيار", "يطبق قانون أوم"],
            "summary": "يربط قانون أوم بين فرق الجهد وشدة التيار والمقاومة.",
            "sections": [
                {"heading": "الفكرة", "body": "فرق الجهد يتناسب مع شدة التيار عند ثبوت المقاومة.", "source_refs": [self.REF]},
                {"heading": "التطبيق", "body": "تستخدم العلاقة V = IR لحساب الكميات الكهربائية.", "source_refs": [self.REF]},
            ],
            "equations_or_rules": [
                {"label": "قانون أوم", "expression": "V = I × R", "notes": "", "source_refs": [self.REF]}
            ],
            "worked_examples": [
                {
                    "title": "مثال",
                    "problem": "احسب التيار عند قيم معطاة.",
                    "solution_steps": ["اكتب العلاقة", "عوّض بالقيم"],
                    "answer": "2 A",
                    "source_refs": [self.REF],
                }
            ],
            "source_visuals": [
                {"title": "رسم الدائرة", "approved": True, "object_key": "source/visual.png", "source_refs": [self.REF]}
            ],
            "diagram_specs": [
                {"kind": "simple_circuit", "title": "دائرة بسيطة", "description": "دائرة مرتبطة بالقانون", "source_refs": [self.REF]}
            ],
            "practice_questions": [
                {
                    "id": "Q1",
                    "prompt": "اختر العلاقة الصحيحة.",
                    "answer": "V = IR",
                    "explanation": "العلاقة مدعومة بالمصدر.",
                    "source_refs": [self.REF],
                    "official_question_bank": False,
                    "question_bank_eligible": False,
                }
            ],
            "common_mistakes": [{"text": "الخلط بين الجهد والتيار.", "source_refs": [self.REF]}],
            "quick_revision": [{"text": "V = IR", "source_refs": [self.REF]}],
        }

    def test_all_twenty_cards_are_registered(self):
        self.assertEqual(len(CARD_FEATURE_SPECS), 20)
        self.assertEqual([item["card"] for item in CARD_FEATURE_SPECS], list(range(1, 21)))
        audio = next(item for item in CARD_FEATURE_SPECS if item["card"] == 10)
        self.assertFalse(audio["enabled"])
        self.assertEqual(audio["status"], "reserved_for_separate_review")

    def test_blueprint_is_deterministic_and_non_mutating(self):
        pack = self._pack()
        original = copy.deepcopy(pack)
        request = {"mode": "lesson_explanation", "audience": "teacher", "language": "ar", "length": "medium"}
        a = build_presentation_blueprint(pack, request, source_lesson_pack_id="pack-1")
        b = build_presentation_blueprint(pack, request, source_lesson_pack_id="pack-1")
        self.assertEqual(pack, original)
        self.assertEqual(a["deck_id"], b["deck_id"])
        self.assertEqual([x["slide_id"] for x in a["slides"]], [x["slide_id"] for x in b["slides"]])
        self.assertFalse(a["generated_content_policy"]["official_question_bank_write"])
        self.assertTrue(a["generated_content_policy"]["content_ingestion_unchanged"])

    def test_factual_blocks_keep_source_refs(self):
        blueprint = build_presentation_blueprint(self._pack(), {"mode": "lesson_explanation"}, source_lesson_pack_id="pack-1")
        report = presentation_preflight(blueprint)
        self.assertTrue(report["ready"], report)
        self.assertNotIn("source_grounding", report["blocking_failures"])

    def test_student_projection_removes_answers_and_speaker_notes(self):
        blueprint = build_presentation_blueprint(
            self._pack(),
            {"mode": "lesson_explanation", "audience": "teacher", "include": {"speaker_notes": True}},
            source_lesson_pack_id="pack-1",
        )
        student = project_edition(blueprint, "student")
        self.assertTrue(student["preflight"]["ready"], student["preflight"])
        self.assertFalse(any(slide.get("speaker_notes") for slide in student["slides"]))
        self.assertFalse(any(block.get("teacher_only") for slide in student["slides"] for block in slide.get("content_blocks", [])))

    def test_teacher_projection_preserves_answer_key_blocks(self):
        blueprint = build_presentation_blueprint(
            self._pack(),
            {"mode": "question_driven", "audience": "teacher"},
            source_lesson_pack_id="pack-1",
        )
        teacher = project_edition(blueprint, "teacher")
        kinds = [block.get("kind") for slide in teacher["slides"] for block in slide.get("content_blocks", [])]
        self.assertIn("answer", kinds)
        self.assertTrue(teacher["preflight"]["ready"], teacher["preflight"])

    def test_bilingual_mode_fails_closed_until_translation_is_complete(self):
        blueprint = build_presentation_blueprint(
            self._pack(),
            {"mode": "lesson_explanation", "language": "bilingual"},
            source_lesson_pack_id="pack-1",
        )
        self.assertFalse(blueprint["preflight"]["ready"])
        self.assertIn("bilingual_translation_complete", blueprint["preflight"]["blocking_failures"])

    def test_objectives_are_covered_in_teaching_mode(self):
        blueprint = build_presentation_blueprint(self._pack(), {"mode": "interactive_class"}, source_lesson_pack_id="pack-1")
        self.assertNotIn("objective_coverage", blueprint["preflight"]["blocking_failures"])

    def test_registered_api_routes(self):
        import index

        paths = {route.path for route in index.app.routes}
        self.assertIn("/api/admin/lesson-pack-studio/presentation/feature-specs", paths)
        self.assertIn("/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/blueprint", paths)
        self.assertIn("/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/edition/{edition}", paths)
        self.assertIn("/api/admin/lesson-pack-studio/presentation/preflight", paths)


if __name__ == "__main__":
    unittest.main()
