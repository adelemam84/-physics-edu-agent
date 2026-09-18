import unittest
from copy import deepcopy

from app.services.lesson_diagram_integrity import diagram_spec_hash
from app.services.lesson_presentation_blueprint import presentation_preflight
from app.services.presentation_visual_qa import presentation_visual_preflight


class PresentationVisualQATests(unittest.TestCase):
    def _blueprint(self, *, subject="فيزياء", kind="force_diagram", parameters=None, engine=None, refs=None):
        parameters = parameters or {
            "object_label": "جسم",
            "object_x": 0.5,
            "object_y": 0.5,
            "forces": [{"label": "F", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.5}],
        }
        visual = {
            "kind": kind,
            "title": "رسم علمي",
            "description": "من المصدر",
            "source_refs": refs if refs is not None else ["ملف: lesson.pdf · صفحة 1"],
            "generated": True,
            "label": "generated_visual",
            "parameters": parameters,
            "diagram_engine": engine or {},
        }
        return {
            "deck_id": "deck-qa",
            "subject": subject,
            "grade_label": "الثالث الثانوي",
            "request": {"mode": "lesson_explanation", "language": "ar", "length": "short"},
            "objectives": [],
            "slides": [{
                "slide_id": "slide-1",
                "order": 1,
                "kind": "diagram_specs",
                "title": "رسم",
                "content_blocks": [],
                "source_refs": list(visual["source_refs"]),
                "objective_ids": [],
                "visual_specs": [visual],
                "table_specs": [],
                "speaker_notes": [],
            }],
            "generated_content_policy": {
                "official_question_bank_write": False,
                "content_ingestion_unchanged": True,
            },
        }

    def _approved_engine(self, kind, parameters):
        return {
            "schema_validated": True,
            "teacher_reviewed": True,
            "review_required": False,
            "approved_spec_hash": diagram_spec_hash({"kind": kind, "parameters": parameters}),
        }

    def test_strict_visual_requires_teacher_review(self):
        bp = self._blueprint(engine={"schema_validated": True, "review_required": True})
        report = presentation_visual_preflight(bp)
        self.assertFalse(report["ready"])
        self.assertIn("visual_teacher_review_required", report["blocking_failures"])

    def test_exact_hash_teacher_review_passes(self):
        params = {
            "object_label": "جسم",
            "object_x": 0.5,
            "object_y": 0.5,
            "forces": [{"label": "F", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.5}],
        }
        bp = self._blueprint(parameters=params, engine=self._approved_engine("force_diagram", params))
        report = presentation_visual_preflight(bp)
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["strict_visual_total"], 1)
        self.assertEqual(report["strict_reviewed_total"], 1)

    def test_parameter_change_makes_approval_stale(self):
        params = {
            "object_label": "جسم",
            "object_x": 0.5,
            "object_y": 0.5,
            "forces": [{"label": "F", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.5}],
        }
        bp = self._blueprint(parameters=params, engine=self._approved_engine("force_diagram", params))
        changed = deepcopy(bp)
        changed["slides"][0]["visual_specs"][0]["parameters"]["forces"][0]["x2"] = 0.7
        report = presentation_visual_preflight(changed)
        self.assertFalse(report["ready"])
        self.assertIn("visual_approval_stale", report["blocking_failures"])

    def test_missing_source_reference_is_blocking(self):
        params = {
            "object_label": "جسم",
            "object_x": 0.5,
            "object_y": 0.5,
            "forces": [{"label": "F", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.5}],
        }
        bp = self._blueprint(parameters=params, refs=[], engine=self._approved_engine("force_diagram", params))
        report = presentation_visual_preflight(bp)
        self.assertFalse(report["ready"])
        self.assertIn("visual_source_grounding", report["blocking_failures"])

    def test_invalid_science_schema_is_blocking(self):
        bp = self._blueprint(parameters={
            "object_label": "جسم",
            "object_x": 0.5,
            "object_y": 0.5,
            "forces": [],
        })
        report = presentation_visual_preflight(bp)
        self.assertFalse(report["ready"])
        self.assertIn("visual_schema_invalid", report["blocking_failures"])

    def test_domain_mismatch_is_advisory_not_silent_rejection(self):
        params = {
            "cell_type": "animal",
            "parts": [{"label": "النواة", "x": 0.5, "y": 0.5}],
        }
        bp = self._blueprint(
            subject="فيزياء",
            kind="cell_structure",
            parameters=params,
            engine=self._approved_engine("cell_structure", params),
        )
        report = presentation_visual_preflight(bp)
        self.assertTrue(report["ready"], report)
        self.assertIn("visual_domain_subject_mismatch", report["warnings"])

    def test_middle_school_science_accepts_branch_visual_domains(self):
        params = {
            "reactants_label": "R",
            "products_label": "P",
            "energy_unit": "kJ/mol",
            "reactants_energy": 20,
            "products_energy": 10,
            "transition_energy": 50,
        }
        bp = self._blueprint(
            subject="علوم",
            kind="reaction_profile",
            parameters=params,
            engine=self._approved_engine("reaction_profile", params),
        )
        report = presentation_visual_preflight(bp)
        self.assertTrue(report["ready"], report)
        self.assertNotIn("visual_domain_subject_mismatch", report["warnings"])

    def test_main_presentation_preflight_includes_visual_qa(self):
        params = {
            "object_label": "جسم",
            "object_x": 0.5,
            "object_y": 0.5,
            "forces": [{"label": "F", "x1": 0.5, "y1": 0.5, "x2": 0.8, "y2": 0.5}],
        }
        bp = self._blueprint(parameters=params, engine=self._approved_engine("force_diagram", params))
        report = presentation_preflight(bp)
        self.assertIn("visual_qa", report)
        self.assertTrue(report["visual_qa"]["ready"])


if __name__ == "__main__":
    unittest.main()
