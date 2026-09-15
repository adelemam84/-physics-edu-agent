from __future__ import annotations

import inspect
import unittest

from app import lesson_studio_second_reviewer, research_engine, science_lesson_studio, source_indexing
from app.services import provider_http


class AIProviderReliabilityContractTests(unittest.TestCase):
    def test_retries_never_change_provider(self):
        source = inspect.getsource(provider_http.request_with_retries)
        self.assertNotIn("fallback", source.lower())
        self.assertNotIn("openai", source.lower())
        self.assertNotIn("gemini", source.lower())
        self.assertNotIn("mathpix", source.lower())

    def test_stateless_provider_paths_use_bounded_retry_helper(self):
        self.assertIn("request_with_retries", inspect.getsource(research_engine._post_generate_content))
        self.assertIn("request_with_retries", inspect.getsource(research_engine._gemini_file_search_query))
        self.assertIn("request_with_retries", inspect.getsource(science_lesson_studio._gemini_text))
        self.assertIn("request_with_retries", inspect.getsource(science_lesson_studio._mathpix_ocr))
        self.assertIn("request_with_retries", inspect.getsource(lesson_studio_second_reviewer._openai_review))
        self.assertIn("request_with_retries", inspect.getsource(source_indexing._operation))

    def test_openai_scientific_review_disables_response_storage(self):
        source = inspect.getsource(lesson_studio_second_reviewer._openai_review)
        self.assertIn("'store': False", source)
        self.assertIn("X-Client-Request-Id", source)

    def test_stateful_provider_creation_and_upload_are_not_replayed(self):
        from app import file_search_store
        self.assertNotIn("request_with_retries", inspect.getsource(file_search_store._create_store))
        self.assertNotIn("request_with_retries", inspect.getsource(source_indexing._start_resumable_upload))
        self.assertNotIn("request_with_retries", inspect.getsource(source_indexing._finish_upload))


if __name__ == "__main__":
    unittest.main()
