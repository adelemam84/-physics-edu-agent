import unittest
from copy import deepcopy

from app import lesson_presentation_editor_productivity  # noqa: F401
from app import lesson_presentation_editor_productivity_ui  # noqa: F401
from app import lesson_presentation_studio_ui
from app.services.lesson_presentation_blueprint import build_presentation_blueprint
from app.services.lesson_presentation_editor import presentation_editor_base_hash
from app.lesson_presentation_editor_productivity import validate_presentation_productivity_edits


class LessonPresentationEditorProductivityTests(unittest.TestCase):
    REF = "ملف 1: lesson.pdf · صفحة 1"

    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["يطبق قانون أوم"],
            "summary": "يربط القانون بين الجهد والتيار والمقاومة.",
            "sections": [{"heading": "الفكرة", "body": "العلاقة V = IR.", "source_refs": [self.REF]}],
            "equations_or_rules": [
                {"label": "قانون أوم", "expression": "V = IR", "notes": "علاقة أساسية", "source_refs": [self.REF]}
            ],
            "worked_examples": [],
            "source_visuals": [],
            "diagram_specs": [],
            "practice_questions": [],
            "common_mistakes": [],
            "quick_revision": [{"text": "V = IR", "source_refs": [self.REF]}],
        }

    def _blueprint(self):
        return build_presentation_blueprint(
            self._pack(),
            {"mode": "lesson_explanation", "audience": "teacher", "language": "ar", "length": "medium"},
            source_lesson_pack_id="pack-1",
        )

    def _validate(self, base, edited):
        return validate_presentation_productivity_edits(
            base,
            edited,
            supplied_base_hash=presentation_editor_base_hash(base),
        )

    def test_safe_duplicate_slide_is_allowed_and_requires_reapproval(self):
        base = self._blueprint()
        edited = deepcopy(base)
        source = edited["slides"][2]
        duplicate = deepcopy(source)
        duplicate["slide_id"] = f"dup-{source['slide_id']}-0123456789abcdef"
        duplicate["duplicate_of"] = source["slide_id"]
        duplicate["title"] += " — نسخة"
        edited["slides"].insert(3, duplicate)
        for i, slide in enumerate(edited["slides"], 1):
            slide["order"] = i
        report = self._validate(base, edited)
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["duplicate_slide_count"], 1)
        self.assertTrue(report["teacher_reapproval_required"])
        self.assertFalse(report["prepared_blueprint"]["approval_state"]["teacher_approved"])

    def test_duplicate_cannot_forge_source_grounding(self):
        base = self._blueprint()
        edited = deepcopy(base)
        source = edited["slides"][2]
        duplicate = deepcopy(source)
        duplicate["slide_id"] = f"dup-{source['slide_id']}-0123456789abcdef"
        duplicate["duplicate_of"] = source["slide_id"]
        duplicate["source_refs"] = ["forged-source"]
        edited["slides"].append(duplicate)
        report = self._validate(base, edited)
        self.assertFalse(report["ready"])
        self.assertIn("immutable_slide_source_refs", report["blocking_failures"])

    def test_smart_table_cells_are_editable_but_structure_is_locked(self):
        base = self._blueprint()
        edited = deepcopy(base)
        table_slide = next(slide for slide in edited["slides"] if slide.get("table_specs"))
        table_slide["table_specs"][0]["rows"][0]["notes"] = "صياغة أوضح للمدرس"
        report = self._validate(base, edited)
        self.assertTrue(report["ready"], report)
        self.assertTrue(report["smart_table_editing"])
        self.assertTrue(report["changed"])

        bad = deepcopy(edited)
        table_slide_bad = next(slide for slide in bad["slides"] if slide.get("table_specs"))
        table_slide_bad["table_specs"][0]["columns"].append("forged")
        blocked = self._validate(base, bad)
        self.assertFalse(blocked["ready"])
        self.assertIn("table_columns_immutable", blocked["blocking_failures"])

    def test_table_source_refs_cannot_change(self):
        base = self._blueprint()
        edited = deepcopy(base)
        table_slide = next(slide for slide in edited["slides"] if slide.get("table_specs"))
        table_slide["table_specs"][0]["rows"][0]["source_refs"] = ["forged"]
        report = self._validate(base, edited)
        self.assertFalse(report["ready"])
        self.assertIn("table_source_refs_immutable", report["blocking_failures"])

    def test_workspace_exposes_undo_redo_autosave_diff_duplicate_and_table_editor(self):
        html = lesson_presentation_studio_ui._workspace("job-1")
        for token in (
            "undoEdit",
            "redoEdit",
            "Autosave Draft",
            "lesson-presentation-draft:",
            "compareBefore",
            "compareAfter",
            "duplicateSlide",
            "Smart Tables",
            "data-table-cell",
            "teacherReapproved=false",
        ):
            self.assertIn(token, html)


if __name__ == "__main__":
    unittest.main()
