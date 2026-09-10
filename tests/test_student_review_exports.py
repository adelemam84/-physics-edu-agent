from __future__ import annotations

import base64
import io
import inspect
import unittest

import fitz
from PIL import Image

from app.student_portal import PAGE as STUDENT_PORTAL_PAGE
from app.student_review_exports import (
    _compact_asset_data_uri,
    _review_html,
    render_student_review_pdf,
    student_attempt_review_pdf,
    student_mistakes_review_pdf,
)


class StudentReviewExportTests(unittest.TestCase):
    """Protect student-owned review exports and source-backed PDF composition."""

    def test_pdf_renders_attempt_answers_and_arabic(self):
        """Attempt review keeps question, student answer, accepted answer and solution."""
        rows = [{
            "position": 1,
            "text_verbatim": "احسب شدة التيار",
            "answer_text": "2 A",
            "accepted_answer": "3 A",
            "solution_verbatim": "من قانون أوم",
            "is_correct": False,
            "difficulty": "medium",
            "lesson_title": "قانون أوم",
            "source_filename": "source.pdf",
            "source_page": 4,
        }]
        data = render_student_review_pdf(
            title="مراجعة الاختبار",
            subtitle="الطالب: أحمد",
            rows=rows,
            mistakes_only=False,
            score_line="الدرجة: 0 / 1",
        )
        self.assertTrue(data.startswith(b"%PDF"))
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        normalized = " ".join(text.split())
        self.assertIn("2 A", normalized)
        self.assertIn("3 A", normalized)
        self.assertGreater(len(text.strip()), 80)
        doc.close()

    def test_source_asset_can_be_embedded(self):
        """Exact source visuals survive as images inside the exported PDF."""
        image = Image.new("RGB", (120, 80), "white")
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        uri = _compact_asset_data_uri(buf.getvalue())
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        base64.b64decode(uri.split(",", 1)[1], validate=True)
        data = render_student_review_pdf(
            title="مذكرة أخطائي",
            subtitle="طالب",
            rows=[{
                "text_verbatim": "سؤال بصري",
                "answer_text": "أ",
                "accepted_answer": "ب",
                "is_correct": False,
                "asset_data_uri": uri,
            }],
            mistakes_only=True,
        )
        doc = fitz.open(stream=data, filetype="pdf")
        self.assertTrue(any(page.get_images(full=True) for page in doc))
        doc.close()

    def test_unavailable_visual_is_explicit_not_recreated(self):
        """A missing source visual is reported explicitly rather than synthesized."""
        html = _review_html(
            title="مراجعة",
            subtitle="طالب",
            rows=[{
                "text_verbatim": "سؤال",
                "answer_text": "أ",
                "accepted_answer": "ب",
                "is_correct": False,
                "asset_unavailable": True,
            }],
            mistakes_only=True,
        )
        self.assertIn("لم يتم إنشاء رسم بديل", html)

    def test_pdf_html_escapes_student_and_source_text(self):
        """Student/source HTML cannot inject markup into the review document."""
        html = _review_html(
            title="<script>x</script>",
            subtitle="طالب",
            rows=[{
                "text_verbatim": "<b>Q</b>",
                "answer_text": "<img>",
                "accepted_answer": "A&B",
                "is_correct": False,
            }],
            mistakes_only=True,
        )
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;b&gt;Q&lt;/b&gt;", html)
        self.assertIn("A&amp;B", html)

    def test_student_portal_keeps_past_attempt_downloads_available(self):
        """A student can return later and download any listed completed attempt review."""
        self.assertIn("downloadAttemptFromPortal", STUDENT_PORTAL_PAGE)
        self.assertIn("/review-pdf", STUDENT_PORTAL_PAGE)
        self.assertIn("تنزيل مذكرة أخطائي PDF", STUDENT_PORTAL_PAGE)

    def test_student_export_routes_use_post_and_student_ownership(self):
        """Exports stay POST-only and the attempt lookup binds the student code."""
        attempt_source = inspect.getsource(student_attempt_review_pdf)
        mistakes_source = inspect.getsource(student_mistakes_review_pdf)
        self.assertIn('@app.post("/api/student/attempts/{attempt_id}/review-pdf")', attempt_source)
        self.assertIn('@app.post("/api/student/review/mistakes-pdf")', mistakes_source)
        from app import student_review_exports as module
        ownership_source = inspect.getsource(module._attempt_bundle)
        self.assertIn("s.external_code=%s", ownership_source)
        self.assertIn("completed_at", ownership_source)


if __name__ == "__main__":
    unittest.main()
