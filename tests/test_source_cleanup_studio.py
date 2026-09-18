import inspect
import unittest
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.services.source_cleanup import analyze_page, enhance_page, normalize_params


class _Result:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConnection:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((str(sql), params))
        return _Result()


class SourceCleanupStudioTests(unittest.TestCase):
    def _scan_bytes(self):
        image = Image.new("RGB", (900, 1200), (235, 233, 228))
        draw = ImageDraw.Draw(image)
        for i in range(12):
            y = 90 + i * 62
            draw.text((80, y), f"Q{i+1}: V = I x R     Answer: {i+2}", fill=(70, 70, 70))
        draw.rectangle((80, 850, 820, 1050), outline=(95, 95, 95), width=2)
        for x in (260, 500, 680):
            draw.line((x, 850, x, 1050), fill=(100, 100, 100), width=2)
        for y in (910, 970):
            draw.line((80, y, 820, y), fill=(100, 100, 100), width=2)
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()

    def test_cleanup_is_non_generative_and_preserves_geometry(self):
        result = enhance_page(
            self._scan_bytes(),
            profile="balanced",
            params={"deskew": False, "region_aware": True},
        )
        self.assertTrue(result.visual_png.startswith(b"\x89PNG"))
        self.assertTrue(result.ocr_png.startswith(b"\x89PNG"))
        self.assertTrue(result.diff_png.startswith(b"\x89PNG"))
        self.assertTrue(result.fidelity["geometry_preserved"])
        self.assertFalse(result.fidelity["content_synthesis_used"])
        self.assertFalse(result.fidelity["inpainting_used"])
        original = Image.open(BytesIO(self._scan_bytes()))
        enhanced = Image.open(BytesIO(result.visual_png))
        self.assertEqual(original.size, enhanced.size)

    def test_profiles_and_manual_region_are_guarded(self):
        params = normalize_params(
            "tables_priority",
            {
                "contrast": 1.3,
                "sharpness": 1.5,
                "region": {"x": .1, "y": .2, "width": .5, "height": .4},
            },
        )
        self.assertEqual(params["region"], (.1, .2, .5, .4))
        with self.assertRaises(ValueError):
            normalize_params("balanced", {"raw_css": "filter:blur(2px)"})
        with self.assertRaises(ValueError):
            normalize_params("generative_repair", {})

    def test_quality_analysis_suggests_safe_known_profile(self):
        report = analyze_page(self._scan_bytes())
        self.assertIn(report["suggested_profile"], {
            "balanced", "text_priority", "tables_priority", "diagrams_priority", "safe"
        })
        self.assertIn("overall", report["metrics"])
        self.assertFalse(report["content_synthesis_used"])

    def test_schema_adds_separate_cleanup_table(self):
        from app.services import lesson_pack_schema

        fake = _FakeConnection()

        @contextmanager
        def fake_connect():
            yield fake

        with patch.object(lesson_pack_schema, "connect", fake_connect):
            lesson_pack_schema.ensure_lesson_pack_schema()
        sql = "\n".join(item[0] for item in fake.sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS lesson_pack_page_enhancements", sql)
        self.assertIn("original_object_key text NOT NULL", sql)
        self.assertIn("teacher_approved boolean NOT NULL DEFAULT false", sql)
        self.assertIn("ocr_comparison_json jsonb", sql)

    def test_cleanup_routes_and_ui_are_registered(self):
        import index
        from app import lesson_pack_studio_ui

        paths = {route.path for route in index.app.routes}
        required = {
            "/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/analyze",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/enhance",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/approve",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/verify-ocr",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/preview/{variant}",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/batch-enhance",
        }
        self.assertTrue(required.issubset(paths), required - paths)
        preview = lesson_pack_studio_ui._preview_page("job-1")
        self.assertIn("Source Cleanup Studio", preview)

    def test_workspace_exposes_all_cleanup_modes(self):
        from app.source_cleanup_studio_ui import _cleanup_page

        html = _cleanup_page("job-1")
        for marker in (
            "Source Cleanup Studio",
            "Text Priority",
            "Tables Priority",
            "Diagrams Priority",
            "Low-Noise Safe",
            "Difference Overlay",
            "Manual Rescue Region",
            "OCR Before/After",
            "Batch",
            "continueOcr",
        ):
            self.assertIn(marker, html)

    def test_lesson_pack_ocr_prefers_only_teacher_approved_cleanup(self):
        from app import lesson_pack_studio

        src = inspect.getsource(lesson_pack_studio.process_next_lesson_pack_page)
        self.assertIn("lesson_pack_page_enhancements", src)
        self.assertIn("teacher_approved=TRUE", src)
        self.assertIn('"approved_enhanced"', src)
        self.assertIn('"original"', src)


if __name__ == "__main__":
    unittest.main()
