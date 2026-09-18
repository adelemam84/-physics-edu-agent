import unittest
from copy import deepcopy

from app.services.lesson_presentation_blueprint import build_presentation_blueprint
from app.services.lesson_presentation_editor import presentation_editor_base_hash, validate_presentation_edits
from app.services.presentation_subject_acceptance import presentation_subject_acceptance
from app.services.science_subject_profiles import (
    normalize_subject,
    notation_kind_allowed,
    subject_profile,
    subject_profiles_catalog,
    visual_domain_allowed,
)


class ScienceSubjectProfileTests(unittest.TestCase):
    REF = "ملف: lesson.pdf · صفحة 1"

    def _pack(self, subject):
        return {
            "title": "درس علمي",
            "subject": subject,
            "grade_label": "الصف التجريبي",
            "learning_objectives": ["يفسر الفكرة من المصدر"],
            "summary": "ملخص مصدر.",
            "sections": [
                {"heading": "الفكرة", "body": "محتوى علمي من المصدر.", "source_refs": [self.REF]},
                {"heading": "التطبيق", "body": "تطبيق موثق بالمصدر.", "source_refs": [self.REF]},
            ],
            "equations_or_rules": [],
            "worked_examples": [],
            "source_visuals": [],
            "diagram_specs": [],
            "practice_questions": [],
            "common_mistakes": [],
            "quick_revision": [{"text": "مراجعة من المصدر.", "source_refs": [self.REF]}],
        }

    def _blueprint(self, subject):
        return build_presentation_blueprint(
            self._pack(subject),
            {
                "mode": "lesson_explanation",
                "audience": "teacher",
                "language": "ar",
                "length": "short",
                "include": {"speaker_notes": True},
            },
            source_lesson_pack_id=f"pack-{normalize_subject(subject)}",
        )

    def test_catalog_has_three_explicit_science_profiles(self):
        catalog = subject_profiles_catalog()
        ids = [x["id"] for x in catalog["profiles"]]
        self.assertEqual(ids, ["physics", "chemistry", "middle_school_science"])
        self.assertFalse(catalog["policy"]["official_question_bank_write"])
        self.assertTrue(catalog["policy"]["content_ingestion_unchanged"])

    def test_aliases_normalize_without_guessing_other_subjects(self):
        self.assertEqual(normalize_subject("فيزياء"), "physics")
        self.assertEqual(normalize_subject("Chemistry"), "chemistry")
        self.assertEqual(normalize_subject("علوم"), "middle_school_science")
        self.assertEqual(normalize_subject("history"), "unknown")

    def test_domain_rules_match_subject_scope(self):
        self.assertTrue(visual_domain_allowed("فيزياء", "physics"))
        self.assertTrue(visual_domain_allowed("فيزياء", "cross_science"))
        self.assertFalse(visual_domain_allowed("فيزياء", "chemistry"))
        self.assertTrue(visual_domain_allowed("علوم", "physics"))
        self.assertTrue(visual_domain_allowed("علوم", "chemistry"))
        self.assertTrue(visual_domain_allowed("علوم", "middle_school_science"))

    def test_notation_rules_are_subject_aware(self):
        self.assertTrue(notation_kind_allowed("كيمياء", "chemical_equation"))
        self.assertFalse(notation_kind_allowed("فيزياء", "chemical_equation"))
        self.assertTrue(notation_kind_allowed("علوم", "chemical_formula_candidate"))
        self.assertTrue(notation_kind_allowed("علوم", "physics_or_math_equation"))

    def test_blueprint_binds_exact_profile_and_editor_cannot_mutate_it(self):
        bp = self._blueprint("كيمياء")
        self.assertEqual(bp["subject_profile"], subject_profile("كيمياء"))
        edited = deepcopy(bp)
        edited["subject_profile"]["id"] = "physics"
        report = validate_presentation_edits(
            bp,
            edited,
            supplied_base_hash=presentation_editor_base_hash(bp),
        )
        self.assertFalse(report["ready"])
        self.assertIn("immutable_subject_profile", report["blocking_failures"])

    def test_acceptance_matrix_runs_student_and_teacher_artifacts_for_all_subjects(self):
        for subject in ("فيزياء", "كيمياء", "علوم"):
            with self.subTest(subject=subject):
                bp = self._blueprint(subject)
                report = presentation_subject_acceptance(bp, render_artifacts=True)
                self.assertTrue(report["ready"], report)
                self.assertEqual(report["summary"]["stages_blocked"], 0)
                self.assertTrue(report["pptx_reports"]["student"]["ready"])
                self.assertTrue(report["pptx_reports"]["teacher"]["ready"])

    def test_acceptance_fails_closed_when_profile_is_tampered(self):
        bp = self._blueprint("فيزياء")
        bp["subject_profile"] = subject_profile("كيمياء")
        report = presentation_subject_acceptance(bp, render_artifacts=False)
        self.assertFalse(report["ready"])
        blocker_ids = [x["id"] for x in report["blockers"]]
        self.assertIn("subject_profile_binding", blocker_ids)

    def test_student_projection_removes_teacher_only_content(self):
        pack = self._pack("علوم")
        pack["practice_questions"] = [{
            "id": "q1",
            "prompt": "سؤال من المصدر",
            "answer": "إجابة من المصدر",
            "explanation": "تفسير من المصدر",
            "source_refs": [self.REF],
        }]
        bp = build_presentation_blueprint(
            pack,
            {
                "mode": "lesson_explanation",
                "audience": "teacher",
                "language": "ar",
                "length": "short",
                "include": {"checkpoints": True, "speaker_notes": True},
            },
            source_lesson_pack_id="pack-science-student-leak-test",
        )
        report = presentation_subject_acceptance(bp, render_artifacts=True)
        self.assertTrue(report["ready"], report)
        self.assertTrue(report["edition_reports"]["student"]["ready"])
        self.assertNotIn("student_answer_leak", report["edition_reports"]["student"]["blocking_failures"])


if __name__ == "__main__":
    unittest.main()
