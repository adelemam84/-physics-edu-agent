from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import (
    content_completion,
    content_phase_guard,
    main,
    question_assets,
    science_lesson_studio,
    science_reference_library,
)


class ContentPhaseGuardTests(unittest.TestCase):
    def test_production_intake_is_fail_closed_by_default(self):
        self.assertFalse(
            content_phase_guard.content_ingestion_enabled({"VERCEL_ENV": "production"})
        )

    def test_explicit_enable_opens_the_content_phase(self):
        self.assertTrue(
            content_phase_guard.content_ingestion_enabled(
                {
                    "VERCEL_ENV": "production",
                    "CONTENT_INGESTION_ENABLED": "true",
                }
            )
        )

    def test_explicit_disable_can_freeze_nonproduction_too(self):
        self.assertFalse(
            content_phase_guard.content_ingestion_enabled(
                {
                    "VERCEL_ENV": "preview",
                    "CONTENT_INGESTION_ENABLED": "false",
                }
            )
        )

    def test_guard_returns_locked_contract_in_production(self):
        with patch.dict(
            os.environ,
            {
                "VERCEL_ENV": "production",
                "CONTENT_INGESTION_ENABLED": "",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as ctx:
                content_phase_guard.require_content_ingestion_enabled()
        self.assertEqual(ctx.exception.status_code, 423)
        self.assertEqual(ctx.exception.detail["code"], "content_ingestion_deferred")

    def test_all_known_source_upload_surfaces_are_guarded(self):
        functions = (
            main.upload_document,
            content_completion.import_drive_explanatory_source,
            science_reference_library.upload_science_reference,
            question_assets.upload_asset,
            question_assets.bulk_upload_assets,
            science_lesson_studio.create_lesson_job,
        )
        for fn in functions:
            self.assertIn(
                "require_content_ingestion_enabled()",
                inspect.getsource(fn),
                fn.__name__,
            )

    def test_admin_config_exposes_content_phase_state(self):
        source = inspect.getsource(main.admin_config)
        self.assertIn("content_ingestion_enabled", source)


if __name__ == "__main__":
    unittest.main()
