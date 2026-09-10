from __future__ import annotations

import inspect
import unittest

from fastapi import HTTPException

from app import admin_workflow, db, question_assets, question_bank
from app.main import ManualQuestionCreate, create_manual_question
from app.services import question_admin_runtime


class QuestionApprovalContractTests(unittest.TestCase):
    """Question readiness may be automatic; approval itself must be explicit."""

    def test_startup_never_auto_approves_questions(self):
        source = inspect.getsource(db.init_db)
        self.assertNotIn("UPDATE questions q SET approved=TRUE", source)

    def test_asset_save_never_auto_approves_questions(self):
        source = inspect.getsource(question_assets._store_asset_row)
        helper = inspect.getsource(question_assets._question_ready_for_human_approval)
        self.assertNotIn("SET approved=TRUE", source)
        self.assertNotIn("SET approved=TRUE", helper)
        self.assertIn("_question_ready_for_human_approval", source)

    def test_verbatim_text_is_not_a_patchable_admin_field(self):
        self.assertNotIn("text_verbatim", question_admin_runtime.ALLOWED_FIELDS)

    def test_source_less_question_creation_is_blocked(self):
        payload = ManualQuestionCreate(page=1, text_verbatim="سؤال")
        with self.assertRaises(HTTPException) as ctx:
            create_manual_question(payload)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["policy"], "pdf_only_verbatim_questions")

    def test_question_bank_uses_paginated_catalog(self):
        self.assertIn("/api/admin/question-catalog", question_bank.BANK)
        self.assertIn("pageSize=100", question_bank.BANK)
        self.assertNotIn("limit:'1000'", question_bank.BANK)
        self.assertNotIn("/api/questions?limit=1000", question_bank.BANK)

    def test_review_workspace_loads_current_source_page_only(self):
        page = admin_workflow.WORKFLOW
        self.assertIn("/api/admin/question-catalog?document_id=", page)
        self.assertIn("&source_page=", page)
        self.assertNotIn("/api/questions?limit=1000", page)
        self.assertIn("/api/admin/questions/", page)
        self.assertIn("/api/admin/review/documents/", page)


if __name__ == "__main__":
    unittest.main()
