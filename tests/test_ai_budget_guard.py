from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

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
            snap = enforce_ai_budget(provider="gemini", task="source_analysis")
        self.assertFalse(snap["configured"])
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
                enforce_ai_budget(provider="gemini", task="visual_review")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail["reason"], "ai_budget_exhausted")
        self.assertIn("daily_calls", ctx.exception.detail["exceeded"])

    def test_only_external_ai_routes_are_guarded(self):
        self.assertIsNotNone(ai_route_policy("/api/admin/research-engine/query", "POST"))
        self.assertIsNotNone(ai_route_policy("/api/admin/current-corpus/visual-review/7/suggest", "POST"))
        self.assertIsNotNone(ai_route_policy("/api/admin/lesson-studio/jobs/abc/process", "POST"))
        self.assertIsNotNone(ai_route_policy("/api/admin/lesson-studio/jobs/abc/second-review", "POST"))
        self.assertIsNone(ai_route_policy("/api/admin/lesson-studio/jobs/abc/export-pdf", "POST"))
        self.assertIsNone(ai_route_policy("/api/student/quizzes/9/submit", "POST"))
        self.assertIsNone(ai_route_policy("/api/admin/research-engine/query", "GET"))


if __name__ == "__main__":
    unittest.main()
