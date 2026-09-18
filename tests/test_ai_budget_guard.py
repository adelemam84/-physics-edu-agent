from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import (
    file_search_store,
    lesson_studio_reference_review,
    lesson_studio_second_reviewer,
    research_engine,
    science_lesson_studio,
    source_indexing,
)
from app.ai_budget_guard import ai_route_policy
from app.services.ai_budget import budget_snapshot, enforce_ai_budget


class AIBudgetGuardTests(unittest.TestCase):
    def test_budget_is_disabled_by_default(self):
        with patch.dict(
            os.environ,
            {
                "AI_DAILY_CALL_BUDGET": "",
                "AI_DAILY_COST_BUDGET_USD": "",
                "AI_MONTHLY_COST_BUDGET_USD": "",
            },
            clear=False,
        ):
            snap = enforce_ai_budget(provider="gemini", task="source_analysis", model="gemini-2.5-flash")
        self.assertFalse(snap["configured"])
        self.assertFalse(snap["hard_block_active"])

    def test_free_only_blocks_paid_or_unapproved_models_before_budget_checks(self):
        with patch.dict(os.environ, {"PROJECT_FREE_ONLY": "true"}, clear=False):
            for provider, model in (
                ("openai", "gpt-5.6-sol"),
                ("mathpix", "mathpix-v3-text"),
                ("gemini", "gemini-3.8-flash"),
            ):
                with self.subTest(provider=provider, model=model):
                    with self.assertRaises(HTTPException) as ctx:
                        enforce_ai_budget(provider=provider, task="test", model=model)
                    self.assertEqual(ctx.exception.status_code, 403)
                    self.assertEqual(ctx.exception.detail["reason"], "project_free_only_policy")

    def test_free_only_allows_verified_free_tier_gemini_models(self):
        with patch.dict(
            os.environ,
            {
                "PROJECT_FREE_ONLY": "true",
                "AI_DAILY_CALL_BUDGET": "",
                "AI_DAILY_COST_BUDGET_USD": "",
                "AI_MONTHLY_COST_BUDGET_USD": "",
            },
            clear=False,
        ):
            for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
                snap = enforce_ai_budget(provider="gemini", task="test", model=model)
                self.assertFalse(snap["hard_block_active"])

    def test_budget_snapshot_warns_at_eighty_percent(self):
        with patch.dict(
            os.environ,
            {
                "AI_DAILY_CALL_BUDGET": "100",
                "AI_DAILY_COST_BUDGET_USD": "",
                "AI_MONTHLY_COST_BUDGET_USD": "",
            },
            clear=False,
        ), patch(
            "app.services.ai_budget._usage_totals",
            return_value={"daily_calls": 80, "daily_cost_usd": 0, "monthly_cost_usd": 0},
        ):
            snap = budget_snapshot()
        self.assertEqual(snap["level"], "warning")
        self.assertFalse(snap["hard_block_active"])
        self.assertEqual(snap["checks"]["daily_calls"]["ratio"], 0.8)

    def test_explicit_exhausted_budget_blocks_external_ai_call(self):
        with patch.dict(
            os.environ,
            {
                "AI_DAILY_CALL_BUDGET": "10",
                "AI_DAILY_COST_BUDGET_USD": "",
                "AI_MONTHLY_COST_BUDGET_USD": "",
            },
            clear=False,
        ), patch(
            "app.services.ai_budget._usage_totals",
            return_value={"daily_calls": 10, "daily_cost_usd": 0, "monthly_cost_usd": 0},
        ):
            with self.assertRaises(HTTPException) as ctx:
                enforce_ai_budget(provider="gemini", task="visual_review", model="gemini-2.5-flash")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail["reason"], "ai_budget_exhausted")
        self.assertIn("daily_calls", ctx.exception.detail["exceeded"])

    def test_only_external_ai_routes_are_guarded(self):
        guarded = (
            "/api/admin/research-engine/query",
            "/api/admin/current-corpus/visual-review/7/suggest",
            "/api/admin/lesson-studio/jobs/abc/process",
            "/api/admin/lesson-studio/jobs/abc/second-review",
            "/api/admin/lesson-studio/jobs/abc/reference-review",
            "/api/admin/research-engine/file-search-store/ensure",
            "/api/admin/research-engine/index/document/7",
            "/api/admin/research-engine/index/refresh/7",
        )
        for path in guarded:
            self.assertIsNotNone(ai_route_policy(path, "POST"), path)

        unguarded = (
            ("/api/admin/lesson-studio/jobs/abc/export-pdf", "POST"),
            ("/api/student/quizzes/9/submit", "POST"),
            ("/api/admin/research-engine/query", "GET"),
            ("/api/admin/lesson-studio/jobs/abc/handwriting-pipeline", "GET"),
            ("/api/admin/research-engine/index/status", "GET"),
            ("/api/admin/research-engine/file-search-store/status", "GET"),
        )
        for path, method in unguarded:
            self.assertIsNone(ai_route_policy(path, method), (path, method))

    def test_provider_boundaries_enforce_budget_not_only_route_middleware(self):
        sources = (
            inspect.getsource(science_lesson_studio._gemini_text),
            inspect.getsource(science_lesson_studio._mathpix_ocr),
            inspect.getsource(lesson_studio_second_reviewer._openai_review),
            inspect.getsource(research_engine._gemini_exact_pdf_query),
            inspect.getsource(research_engine._gemini_file_search_query),
            inspect.getsource(file_search_store._create_store),
            inspect.getsource(source_indexing._start_resumable_upload),
            inspect.getsource(source_indexing._finish_upload),
            inspect.getsource(source_indexing._operation),
        )
        for source in sources:
            self.assertIn("enforce_ai_budget", source)

    def test_new_gemini_admin_operations_are_metered(self):
        self.assertIn("record_ai_usage", inspect.getsource(file_search_store._create_store))
        self.assertIn("record_ai_usage", inspect.getsource(source_indexing._start_resumable_upload))
        self.assertIn("record_ai_usage", inspect.getsource(source_indexing._finish_upload))
        self.assertIn("record_ai_usage", inspect.getsource(source_indexing._operation))

    def test_reference_review_has_its_own_telemetry_task(self):
        source = inspect.getsource(lesson_studio_reference_review.run_reference_review)
        self.assertIn("task='scientific_reference_review'", source)


if __name__ == "__main__":
    unittest.main()
