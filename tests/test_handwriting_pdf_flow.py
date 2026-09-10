from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from app.lesson_studio_handwriting_pipeline import handwriting_pipeline_snapshot
from app.lesson_studio_workspace import WORKSPACE


class HandwritingPdfFlowTests(unittest.TestCase):
    """Protect the teacher-facing handwritten lesson to reviewed PDF flow."""

    @patch("app.lesson_studio_handwriting_pipeline.build_quality_snapshot")
    @patch("app.lesson_studio_handwriting_pipeline._job")
    def test_pipeline_exposes_exact_quality_and_pdf_readiness(self, job_mock, quality_mock):
        """The handwriting snapshot must reuse the canonical quality gate rather than inventing readiness."""
        job_mock.return_value = (
            {
                "subject": "physics",
                "status": "structured",
                "structured_json": {
                    "uncertain_items": [],
                    "diagram_specs": [],
                    "notation_quality": {"review_required": 0},
                },
            },
            [{
                "id": 1,
                "position": 1,
                "filename": "note.jpg",
                "extracted_text": "V = I R",
                "confidence": 0.98,
                "ocr_conflicts": [],
                "ocr_confidence_band": "green",
                "requires_review": False,
            }],
        )
        quality_mock.return_value = {
            "checks": [
                {"id": "source_preserved", "ok": True},
                {"id": "source_transcript_binding", "ok": True},
                {"id": "ocr_review_clear", "ok": True},
                {"id": "structured_content_ready", "ok": True},
            ],
            "preapproval_ready": True,
            "teacher_approved": True,
            "teacher_approval_fresh": True,
            "final_ready": True,
        }
        snapshot = handwriting_pipeline_snapshot("job-1")
        self.assertTrue(snapshot["summary"]["study_note_ready_for_teacher_review"])
        self.assertTrue(snapshot["summary"]["teacher_approval_fresh"])
        self.assertTrue(snapshot["summary"]["final_export_ready"])
        self.assertIsNone(snapshot["next_action"])
        self.assertTrue(all(stage["ok"] for stage in snapshot["stages"]))
        quality_mock.assert_called_once()

    @patch("app.lesson_studio_handwriting_pipeline.build_quality_snapshot")
    @patch("app.lesson_studio_handwriting_pipeline._job")
    def test_pipeline_points_to_first_blocking_stage(self, job_mock, quality_mock):
        """Low OCR readiness remains the next action and PDF export stays blocked."""
        job_mock.return_value = (
            {"subject": "physics", "status": "ocr", "structured_json": {}},
            [{
                "id": 2,
                "position": 1,
                "filename": "hand.jpg",
                "extracted_text": "I = ?",
                "confidence": 0.55,
                "ocr_conflicts": [],
                "ocr_confidence_band": "red",
                "requires_review": True,
            }],
        )
        quality_mock.return_value = {
            "checks": [
                {"id": "source_preserved", "ok": True},
                {"id": "source_transcript_binding", "ok": True},
                {"id": "ocr_review_clear", "ok": False},
                {"id": "structured_content_ready", "ok": False},
            ],
            "preapproval_ready": False,
            "teacher_approved": False,
            "teacher_approval_fresh": False,
            "final_ready": False,
        }
        snapshot = handwriting_pipeline_snapshot("job-2")
        self.assertEqual(snapshot["next_action"]["id"], "ocr_review")
        self.assertEqual(snapshot["next_action"]["tab"], "ocr")
        self.assertFalse(snapshot["summary"]["final_export_ready"])

    def test_workspace_has_direct_a4_and_mobile_pdf_actions(self):
        """The handwriting tab exposes a complete guided path and both PDF presets."""
        self.assertIn("Smart Study Note → PDF", WORKSPACE)
        self.assertIn("exportHandwritingPdf('a4')", WORKSPACE)
        self.assertIn("exportHandwritingPdf('mobile')", WORKSPACE)
        self.assertIn("أكمل البوابة الحالية أولًا", WORKSPACE)

    def test_handwriting_snapshot_is_read_only(self):
        """The diagnostics function itself contains no SQL mutation path."""
        source = inspect.getsource(handwriting_pipeline_snapshot).upper()
        for token in ("UPDATE ", "INSERT ", "DELETE ", "ALTER TABLE", "CREATE TABLE", "DROP TABLE"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
