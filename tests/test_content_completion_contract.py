from __future__ import annotations

import inspect
import unittest

from fastapi import HTTPException

from app.completion_audit import completion_audit_snapshot
from app.content_completion import (
    PAGE,
    _drive_file_id,
    _gate_state,
    _read_content_rows,
    content_completion_snapshot,
    import_drive_explanatory_source,
)


class ContentCompletionContractTests(unittest.TestCase):
    """Protect full-curriculum source coverage and human-only scientific review gates."""

    def test_partial_lesson_source_coverage_never_counts_as_complete(self):
        """One or several mappings must not impersonate coverage of every current lesson."""
        self.assertFalse(_gate_state(10, 0, 0, 0, 0)['content_complete'])
        self.assertFalse(_gate_state(10, 1, 0, 0, 0)['content_complete'])
        self.assertFalse(_gate_state(10, 9, 0, 0, 0)['content_complete'])
        complete = _gate_state(10, 10, 0, 0, 0)
        self.assertTrue(complete['explanatory_coverage_complete'])
        self.assertTrue(complete['content_complete'])

    def test_open_visual_or_mismatch_review_blocks_content_completion(self):
        """Human source-review work remains a hard completion gate even with full lesson coverage."""
        self.assertFalse(_gate_state(10, 10, 50, 50, 0)['content_complete'])
        self.assertFalse(_gate_state(10, 10, 1, 0, 1)['content_complete'])
        self.assertFalse(_gate_state(10, 10, 2, 0, 0)['content_complete'])

    def test_zero_lessons_never_reports_source_completion(self):
        """An unconfigured curriculum cannot become vacuously complete."""
        state = _gate_state(0, 0, 0, 0, 0)
        self.assertFalse(state['explanatory_coverage_complete'])
        self.assertFalse(state['content_complete'])

    def test_content_snapshot_reader_contains_no_mutating_sql(self):
        """The completion snapshot must remain durable-state read-only."""
        source = inspect.getsource(_read_content_rows).upper()
        forbidden = (
            'UPDATE ', 'INSERT ', 'DELETE ', 'TRUNCATE',
            'ALTER TABLE', 'CREATE TABLE', 'DROP TABLE', 'CREATE INDEX', 'GRANT ',
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_completion_audit_uses_whole_curriculum_coverage(self):
        """Project closure must delegate theory-source completion to the strict coverage contract."""
        source = inspect.getsource(completion_audit_snapshot)
        self.assertIn('content_completion_snapshot', source)
        self.assertIn("explanatory_coverage_complete", source)
        self.assertIn("uncovered_lessons", source)
        self.assertNotIn("approved_mappings') or 0) == 0", source)

    def test_drive_import_is_explicit_and_never_auto_approves(self):
        """Drive ingestion is an admin action and its contract cannot claim scientific approval."""
        source = inspect.getsource(import_drive_explanatory_source)
        snapshot_source = inspect.getsource(content_completion_snapshot)
        self.assertIn('_download_drive_pdf', source)
        self.assertIn('no_source_or_question_is_auto_approved_by_this_phase', snapshot_source)
        self.assertIn('اعتماد يدوي', PAGE)
        self.assertIn('لا تعتمد أي درس ولا سؤال تلقائيًا', PAGE)

    def test_drive_url_parser_rejects_non_drive_hosts(self):
        """Server-side source import must not become an arbitrary-URL fetch primitive."""
        self.assertEqual(
            _drive_file_id('https://drive.google.com/file/d/abc_DEF-123/view'),
            'abc_DEF-123',
        )
        with self.assertRaises(HTTPException):
            _drive_file_id('https://example.com/file/d/abc/view')
        with self.assertRaises(HTTPException):
            _drive_file_id('https://drive.google.com/open?id=abc')

    def test_ui_exposes_draft_mapping_then_manual_approval(self):
        """The cockpit must preserve the two-step draft-map then human-approve workflow."""
        self.assertIn('/lesson-source', PAGE)
        self.assertIn('/approve', PAGE)
        self.assertIn('إنشاء ربط للمراجعة', PAGE)
        self.assertIn('هل راجعت نطاق الصفحات', PAGE)


if __name__ == '__main__':
    unittest.main()
