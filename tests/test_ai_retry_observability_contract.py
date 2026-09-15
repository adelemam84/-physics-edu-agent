from __future__ import annotations

import inspect
import unittest

from app import (
    ai_operations,
    lesson_studio_second_reviewer,
    operations_readiness,
    research_engine,
    science_lesson_studio,
    source_indexing,
    technical_observability,
)
from app.services import ai_telemetry, provider_http


class AIRetryObservabilityContractTests(unittest.TestCase):
    def test_provider_helper_exposes_success_and_error_attempt_counts(self):
        self.assertTrue(callable(provider_http.provider_attempts))
        self.assertTrue(callable(provider_http.provider_error_attempts))

    def test_provider_paths_emit_attempt_metadata(self):
        for fn in (
            research_engine._execute_orchestrated,
            science_lesson_studio._gemini_text,
            science_lesson_studio._mathpix_ocr,
            lesson_studio_second_reviewer._openai_review,
            source_indexing._operation,
        ):
            self.assertIn("provider_attempts", inspect.getsource(fn), fn.__name__)

    def test_usage_snapshot_aggregates_retry_pressure_without_content(self):
        source = inspect.getsource(ai_telemetry.usage_snapshot)
        self.assertIn("retried_calls", source)
        self.assertIn("retry_attempts", source)
        self.assertIn("retry_pct", source)
        self.assertIn("metadata_json->>'provider_attempts'", source)
        self.assertNotIn("prompt", source.lower())

    def test_retry_pressure_is_visible_in_admin_and_handoff_surfaces(self):
        self.assertIn("Retry / 24س", ai_operations.PAGE)
        self.assertIn("ai_retry_pressure", inspect.getsource(technical_observability.technical_observability_snapshot))
        self.assertIn("ai_retry_pct_24h", inspect.getsource(operations_readiness.build_operations_readiness))


if __name__ == "__main__":
    unittest.main()
