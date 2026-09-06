import unittest

from app.services.ai_orchestrator import build_orchestration_plan, integrity_envelope


class AIOrchestratorTests(unittest.TestCase):
    def test_visual_review_always_uses_exact_pdf_pages(self):
        plan = build_orchestration_plan(
            'visual_review', provider_configured=True,
            file_search_configured=True, page_count=10,
        )
        self.assertEqual(plan.source_mode, 'exact_pdf_pages')
        self.assertFalse(plan.can_write_question_bank)
        self.assertFalse(plan.can_auto_approve)
        self.assertFalse(plan.can_publish)

    def test_question_review_always_uses_exact_pdf_pages(self):
        plan = build_orchestration_plan(
            'question_review', provider_configured=True,
            file_search_configured=True, page_count=8,
        )
        self.assertEqual(plan.source_mode, 'exact_pdf_pages')

    def test_broad_research_can_use_file_search(self):
        plan = build_orchestration_plan(
            'source_analysis', provider_configured=True,
            file_search_configured=True, page_count=9,
        )
        self.assertEqual(plan.source_mode, 'file_search')

    def test_small_broad_research_prefers_exact_pages(self):
        plan = build_orchestration_plan(
            'lesson_support', provider_configured=True,
            file_search_configured=True, page_count=4,
        )
        self.assertEqual(plan.source_mode, 'exact_pdf_pages')

    def test_unconfigured_provider_is_explicit(self):
        plan = build_orchestration_plan(
            'source_analysis', provider_configured=False,
            file_search_configured=False, page_count=2,
        )
        self.assertEqual(plan.source_mode, 'provider_unavailable')

    def test_integrity_envelope_never_auto_approves(self):
        env = integrity_envelope(
            provider='gemini_source_engine', document_id=7,
            page_start=2, page_end=4,
        )
        self.assertTrue(env['advisory_only'])
        self.assertFalse(env['auto_saved_to_question_bank'])
        self.assertFalse(env['auto_approved'])
        self.assertFalse(env['auto_published'])
        self.assertEqual(env['source_document_id'], 7)


if __name__ == '__main__':
    unittest.main()
