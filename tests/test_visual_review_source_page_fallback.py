from __future__ import annotations

from pathlib import Path
import unittest

from app.visual_review_assistant import (
    _candidate_ordinal,
    _prepare_source_row,
    _source_fingerprint,
    _suggestion_prompt,
)


SOURCE = Path("app/visual_review_assistant.py").read_text(encoding="utf-8")


class VisualReviewSourcePageFallbackTests(unittest.TestCase):
    def test_queue_and_single_question_queries_allow_missing_crop_assets(self):
        self.assertGreaterEqual(
            SOURCE.count("LEFT JOIN question_assets a ON a.question_id=q.id"),
            2,
        )
        self.assertNotIn(
            "JOIN question_assets a ON a.question_id=q.id\n          JOIN documents",
            SOURCE.replace("LEFT JOIN", "LEFT_JOIN"),
        )

    def test_candidate_ordinal_is_read_from_source_placeholder(self):
        self.assertEqual(
            _candidate_ordinal(
                "[SOURCE-IMAGE-CANDIDATE 2026/2027 P12 Q5] النص محفوظ في الأصل البصري"
            ),
            5,
        )
        self.assertIsNone(_candidate_ordinal("ordinary reviewed text"))

    def test_missing_crop_uses_authoritative_full_source_page(self):
        row, mode, ordinal = _prepare_source_row(
            {
                "document_id": 5,
                "source_page": 12,
                "text_verbatim": "[SOURCE-IMAGE-CANDIDATE 2026/2027 P12 Q5]",
                "object_key": None,
                "page_number": None,
                "crop_x": None,
                "crop_y": None,
                "crop_width": None,
                "crop_height": None,
                "storage_url": "https://drive.google.com/file/d/source/view",
            }
        )
        self.assertEqual(mode, "full_source_page_fallback")
        self.assertEqual(ordinal, 5)
        self.assertEqual(row["object_key"], "source-drive:5:12:full-page-fallback")
        self.assertEqual(row["page_number"], 12)
        self.assertEqual(
            (row["crop_x"], row["crop_y"], row["crop_width"], row["crop_height"]),
            (0.0, 0.0, 1.0, 1.0),
        )

    def test_fallback_prompt_binds_model_to_requested_question_only(self):
        prompt = _suggestion_prompt("full_source_page_fallback", 5)
        self.assertIn("السؤال رقم 5", prompt)
        self.assertIn("لا تنقل سؤالًا آخر", prompt)
        self.assertIn("uncertain_parts", prompt)
        self.assertIn("بدل التخمين", prompt)

    def test_fingerprint_distinguishes_full_page_candidate_ordinal(self):
        row = {
            "document_id": 5,
            "source_page": 12,
            "object_key": "source-drive:5:12:full-page-fallback",
            "crop_x": 0,
            "crop_y": 0,
            "crop_width": 1,
            "crop_height": 1,
        }
        one = _source_fingerprint(row, "full_source_page_fallback", 1)
        two = _source_fingerprint(row, "full_source_page_fallback", 2)
        self.assertNotEqual(one, two)


if __name__ == "__main__":
    unittest.main()
