from __future__ import annotations

import unittest
from unittest.mock import patch

import fitz

from app import lesson_pack_studio
from app.services.lesson_pack_core import validate_pack_provenance
from app.services.lesson_pack_student_renderer import render_student_handout_pdf


class LessonPackSourceVisualTests(unittest.TestCase):
    def _page_png(self) -> bytes:
        doc = fitz.open()
        page = doc.new_page(width=400, height=600)
        page.draw_rect(fitz.Rect(70, 120, 330, 360), color=(0, 0, 0), width=3)
        page.insert_text((110, 210), "SOURCE FIGURE", fontsize=20)
        png = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False).tobytes("png")
        doc.close()
        return png

    def _pack(self) -> dict:
        ref = "ملف 1: lesson.pdf · صفحة 1"
        return {
            "title": "قانون أوم",
            "subject": "physics",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["فهم العلاقة بين الجهد والتيار والمقاومة"],
            "sections": [
                {"heading": "الفكرة الأساسية", "body": "شرح الدرس.", "source_refs": [ref]}
            ],
            "practice_questions": [
                {
                    "prompt": "سؤال تدريبي",
                    "difficulty": "medium",
                    "options": [],
                    "answer": "إجابة مخفية",
                    "source_refs": [ref],
                }
            ],
            "source_visuals": [
                {
                    "id": "source-visual-1",
                    "title": "شكل من المصدر",
                    "description": "الرسم الأصلي المرتبط بالشرح.",
                    "source_ref": ref,
                    "source_refs": [ref],
                    "page_id": 1,
                    "bbox": {"x": 0.15, "y": 0.18, "width": 0.7, "height": 0.5},
                    "approved": True,
                    "review_required": False,
                    "object_key": "lesson-pack/job/source-visuals/source-visual-1.png",
                    "media_type": "image/png",
                }
            ],
            "summary": "خلاصة.",
        }

    def test_bbox_normalization_clamps_to_page(self):
        box = lesson_pack_studio._normalize_visual_bbox(
            {"x": -1, "y": 0.9, "width": 2, "height": 2}
        )
        self.assertEqual(box["x"], 0.0)
        self.assertGreaterEqual(box["width"], 0.03)
        self.assertLessEqual(box["x"] + box["width"], 1.0)
        self.assertLessEqual(box["y"] + box["height"], 1.0)

    def test_source_crop_uses_original_page_pixels(self):
        page = {"object_key": "page.png"}
        with patch("app.lesson_pack_studio.get_bytes", return_value=self._page_png()):
            cropped = lesson_pack_studio._crop_page_image(
                page,
                {"x": 0.1, "y": 0.15, "width": 0.8, "height": 0.55},
            )
        self.assertTrue(cropped.startswith(b"\x89PNG"))
        source = fitz.open(stream=self._page_png(), filetype="png")
        crop = fitz.open(stream=cropped, filetype="png")
        try:
            self.assertLess(crop[0].rect.width, source[0].rect.width * 1.25)
            self.assertLess(crop[0].rect.height, source[0].rect.height)
        finally:
            source.close()
            crop.close()

    def test_source_visual_provenance_is_validated(self):
        pack = self._pack()
        good_ref = "ملف 1: lesson.pdf · صفحة 1"
        self.assertTrue(validate_pack_provenance(pack, [good_ref])["passed"])
        pack["source_visuals"][0]["source_refs"] = ["ملف 9: fake.pdf · صفحة 99"]
        result = validate_pack_provenance(pack, [good_ref])
        self.assertFalse(result["passed"])
        self.assertTrue(any(x["location"].startswith("source_visuals") for x in result["invalid_refs"]))

    def test_student_pdf_embeds_only_approved_original_crop(self):
        pack = self._pack()
        with patch(
            "app.services.lesson_pack_student_renderer.get_bytes",
            return_value=self._page_png(),
        ):
            data = render_student_handout_pdf(pack)
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            self.assertGreaterEqual(sum(len(page.get_images(full=True)) for page in doc), 1)
        finally:
            doc.close()

    def test_unapproved_source_visual_is_not_loaded(self):
        pack = self._pack()
        pack["source_visuals"][0]["approved"] = False
        with patch(
            "app.services.lesson_pack_student_renderer.get_bytes",
            side_effect=AssertionError("unapproved source visual must not load"),
        ):
            data = render_student_handout_pdf(pack)
        self.assertTrue(data.startswith(b"%PDF"))

    def test_preview_stamp_keeps_pdf_valid(self):
        base = render_student_handout_pdf({**self._pack(), "source_visuals": []})
        preview = lesson_pack_studio._preview_stamp(base, "student")
        self.assertTrue(preview.startswith(b"%PDF"))
        doc = fitz.open(stream=preview, filetype="pdf")
        try:
            self.assertGreaterEqual(doc.page_count, 1)
        finally:
            doc.close()

    def test_page_preview_renders_single_png_and_reports_total(self):
        base = render_student_handout_pdf({**self._pack(), "source_visuals": []})
        preview = lesson_pack_studio._preview_stamp(base, "student")
        png, total = lesson_pack_studio._preview_page_png(preview, 1)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreaterEqual(total, 2)

    def test_page_preview_rejects_out_of_range_page(self):
        base = render_student_handout_pdf({**self._pack(), "source_visuals": []})
        preview = lesson_pack_studio._preview_stamp(base, "student")
        with self.assertRaises(Exception) as ctx:
            lesson_pack_studio._preview_page_png(preview, 999)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    def test_cover_value_is_normalized_and_bounded(self):
        self.assertEqual(
            lesson_pack_studio._clean_cover_value("  ADEL   EMAM  "),
            "ADEL EMAM",
        )
        self.assertEqual(len(lesson_pack_studio._clean_cover_value("x" * 200)), 120)

    def test_new_preview_and_visual_routes_are_registered(self):
        paths = {route.path for route in lesson_pack_studio.app.routes}
        required = {
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/suggest",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/{visual_id}/preview",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/{visual_id}/review",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/cover",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-pdf",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-manifest",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-page/{page_number}",
        }
        self.assertTrue(required.issubset(paths), required - paths)


if __name__ == "__main__":
    unittest.main()
