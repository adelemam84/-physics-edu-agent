from __future__ import annotations

import inspect
import unittest

from app.lesson_studio_acceptance import (
    _counts,
    _job_binding_summary,
    _schema_snapshot,
)
from app.services.corpus_phase2_runtime import ensure_phase2_schemas, run_phase2_bootstrap
from app.services.lesson_diagram_integrity import diagram_manifest
from app.services.lesson_integrity import review_source_hash


class LessonProductionAcceptanceTests(unittest.TestCase):
    """Protect Phase X production acceptance from stale bindings or diagnostic writes."""

    @staticmethod
    def _row() -> dict:
        """Build one internally consistent release row for pure acceptance tests."""
        structured = {
            'title': 'Current lesson',
            'sections': [{'heading': 'A', 'body': 'B', 'source_refs': ['source-1']}],
            'diagram_specs': [],
        }
        transcript = '[مصدر 1: source.png]\nverified source text'
        content_hash = review_source_hash(transcript, structured)
        diagram_hash = diagram_manifest(structured)['hash']
        return {
            'id': 'job-1',
            'source_count': 1,
            'raw_transcript': transcript,
            'structured_json': structured,
            'reference_review': {'verdict': 'aligned', 'findings': []},
            'reference_review_hash': content_hash,
            'teacher_approved': True,
            'teacher_approval_source_hash': content_hash,
            'teacher_approval_diagram_hash': diagram_hash,
            'status': 'final_pdf_ready',
            'pdf_object_key': 'lesson-studio/job-1/final.pdf',
            'pdf_source_hash': content_hash,
            'pdf_diagram_manifest_hash': diagram_hash,
        }

    def test_complete_release_requires_one_fully_fresh_job(self):
        """A single job with matching content/diagram contracts can satisfy the strict release path."""
        state = _job_binding_summary(self._row(), pending_sources=0, total_sources=1)
        self.assertTrue(state['reference_fresh'])
        self.assertTrue(state['teacher_fresh'])
        self.assertTrue(state['pdf_fresh'])
        self.assertTrue(state['complete_release'])

    def test_diagram_change_invalidates_teacher_and_pdf_freshness(self):
        """Changing the diagram manifest must make both teacher approval and the final PDF stale."""
        row = self._row()
        row['structured_json'] = {
            **row['structured_json'],
            'diagram_specs': [{'kind': 'graph', 'title': 'new diagram'}],
        }
        state = _job_binding_summary(row, pending_sources=0, total_sources=1)
        self.assertFalse(state['teacher_fresh'])
        self.assertFalse(state['pdf_hash_fresh'])
        self.assertFalse(state['pdf_fresh'])
        self.assertFalse(state['complete_release'])

    def test_content_change_invalidates_reference_teacher_and_pdf(self):
        """Changing reviewed source content must invalidate every downstream release binding."""
        row = self._row()
        row['raw_transcript'] += '\nchanged source line'
        state = _job_binding_summary(row, pending_sources=0, total_sources=1)
        self.assertFalse(state['reference_fresh'])
        self.assertFalse(state['teacher_fresh'])
        self.assertFalse(state['pdf_hash_fresh'])
        self.assertFalse(state['pdf_fresh'])
        self.assertFalse(state['complete_release'])

    def test_blocking_reference_finding_prevents_complete_release(self):
        """A hash-current reference review still fails acceptance when it contains a blocking finding."""
        row = self._row()
        row['reference_review'] = {
            'verdict': 'aligned',
            'findings': [{'severity': 'review', 'message': 'teacher must inspect'}],
        }
        state = _job_binding_summary(row, pending_sources=0, total_sources=1)
        self.assertFalse(state['reference_fresh'])
        self.assertFalse(state['complete_release'])

    def test_malformed_reference_findings_fail_closed(self):
        """Malformed findings payloads or entries must never be interpreted as a clean scientific review."""
        malformed_values = (
            {'severity': 'critical'},
            'unparsed findings',
            7,
            [{'severity': 'note'}, 'malformed entry'],
        )
        for malformed in malformed_values:
            row = self._row()
            row['reference_review'] = {'verdict': 'aligned', 'findings': malformed}
            state = _job_binding_summary(row, pending_sources=0, total_sources=1)
            self.assertFalse(state['reference_fresh'])
            self.assertFalse(state['complete_release'])

    def test_pdf_hash_freshness_is_distinct_from_release_status(self):
        """A status transition can make a PDF non-final without falsely labeling its immutable hashes stale."""
        row = self._row()
        row['status'] = 'review_required'
        state = _job_binding_summary(row, pending_sources=0, total_sources=1)
        self.assertTrue(state['pdf_recorded'])
        self.assertTrue(state['pdf_hash_fresh'])
        self.assertFalse(state['pdf_fresh'])
        self.assertFalse(state['complete_release'])

    def test_pending_or_missing_sources_block_end_to_end_acceptance(self):
        """A release cannot count as complete when OCR source review is pending or the source set is missing."""
        row = self._row()
        self.assertFalse(_job_binding_summary(row, pending_sources=1, total_sources=1)['complete_release'])
        self.assertFalse(_job_binding_summary(row, pending_sources=0, total_sources=0)['complete_release'])

    def test_acceptance_readers_contain_no_mutating_sql(self):
        """Production acceptance diagnostics and delegated helpers must remain durable-state read-only."""
        readers = (_counts, _schema_snapshot, _job_binding_summary)
        tokens = (
            'UPDATE ',
            'INSERT ',
            'DELETE ',
            'TRUNCATE',
            'ALTER TABLE',
            'CREATE TABLE',
            'DROP TABLE',
            'CREATE INDEX',
            'GRANT ',
        )
        for reader in readers:
            source = inspect.getsource(reader).upper()
            for token in tokens:
                self.assertNotIn(token, source, f'{reader.__name__} must stay read-only')

    def test_acceptance_content_heavy_scans_are_release_bounded(self):
        """Reference page text and lesson bodies must be limited to rows relevant to release diagnostics."""
        source = inspect.getsource(_counts)
        self.assertIn('d.curriculum_map IS NOT NULL', source)
        self.assertIn('_RELEASE_CANDIDATE_PREDICATE', source)
        self.assertIn("'bounded': True", source)

    def test_acceptance_schemas_are_initialized_before_phase2_data_work(self):
        """Schema DDL must be complete and unlocked before Phase 2 business-data queries."""
        schema_source = inspect.getsource(ensure_phase2_schemas)
        required = (
            'ensure_release_state_schema()',
            'reference_schema()',
            '_map_schema()',
            '_history_schema()',
        )
        for marker in required:
            self.assertIn(marker, schema_source)

        run_source = inspect.getsource(run_phase2_bootstrap)
        lock_pos = run_source.index('with startup_migration_lock():')
        schema_pos = run_source.index('ensure_phase2_schemas(')
        first_data_read = run_source.index('with connect() as con:')
        self.assertLess(lock_pos, schema_pos)
        self.assertLess(schema_pos, first_data_read)


if __name__ == '__main__':
    unittest.main()
