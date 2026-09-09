import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.lesson_studio_enhancements import _normalize_suggestion_payload
from app.lesson_studio_quality import (
    _build_quality_snapshot,
    _delete_unpromoted_pdf,
    _final_pdf_object_key,
    _snapshot_contract,
)


@patch('app.lesson_studio_quality.OPENAI_REVIEW_CONFIGURED', False)
@patch('app.lesson_studio_quality.REFERENCE_REVIEW_REQUIRED', False)
class AtomicLessonQualityTests(unittest.TestCase):
    def _base_row(self):
        """Build a deterministic clean lesson row independent of deployment environment."""
        return {
            'raw_transcript': 'قانون أوم كما ورد في المصدر',
            'structured_json': {
                'title': 'قانون أوم',
                'sections': [],
                'uncertain_items': [],
                'equations_or_rules': [],
                'notation_quality': {'review_required': 0},
                'diagram_specs': [],
            },
            'source_count': 1,
            'teacher_approved': False,
            'teacher_approval_source_hash': None,
            'teacher_approval_diagram_hash': None,
            'second_review': None,
            'second_review_provider': None,
            'second_review_source_hash': None,
            'reference_review': None,
            'reference_review_hash': None,
        }

    def test_locked_state_builder_is_preapproval_ready_for_clean_state(self):
        """A clean locked state should pass preapproval but not final approval."""
        snap = _build_quality_snapshot('job-1', self._base_row(), [{'id': 1, 'requires_review': False}])
        self.assertTrue(snap['preapproval_ready'])
        self.assertFalse(snap['teacher_approval_fresh'])
        self.assertFalse(snap['final_ready'])
        self.assertTrue(snap['policy']['approval_and_export_recheck_locked_state'])
        self.assertTrue(snap['policy']['quality_cache_written_from_locked_state'])

    def test_teacher_approval_is_fresh_only_for_exact_locked_contract(self):
        """Teacher approval must become stale after any bound content contract change."""
        row = self._base_row()
        first = _build_quality_snapshot('job-1', row, [{'id': 1, 'requires_review': False}])
        content_hash, diagram_hash = _snapshot_contract(first)
        approved = dict(row)
        approved.update({
            'teacher_approved': True,
            'teacher_approval_source_hash': content_hash,
            'teacher_approval_diagram_hash': diagram_hash,
        })
        fresh = _build_quality_snapshot('job-1', approved, [{'id': 1, 'requires_review': False}])
        self.assertTrue(fresh['teacher_approval_fresh'])
        self.assertTrue(fresh['final_ready'])

        changed = dict(approved)
        changed['structured_json'] = {
            **approved['structured_json'],
            'title': 'قانون أوم - نسخة معدلة',
        }
        stale = _build_quality_snapshot('job-1', changed, [{'id': 1, 'requires_review': False}])
        self.assertFalse(stale['teacher_approval_fresh'])
        self.assertFalse(stale['final_ready'])
        self.assertNotEqual(_snapshot_contract(fresh), _snapshot_contract(stale))

    def test_source_review_change_invalidates_locked_gate_state(self):
        """A pending source review must block the quality gate immediately."""
        row = self._base_row()
        clear = _build_quality_snapshot('job-1', row, [{'id': 1, 'requires_review': False}])
        blocked = _build_quality_snapshot('job-1', row, [{'id': 1, 'requires_review': True}])
        self.assertTrue(clear['preapproval_ready'])
        self.assertFalse(blocked['preapproval_ready'])
        check = next(x for x in blocked['checks'] if x['id'] == 'ocr_review_clear')
        self.assertEqual(check['value'], 1)

    def test_locked_source_text_must_match_raw_transcript(self):
        """A source-row edit must block approval until the canonical transcript is rebuilt."""
        row = self._base_row()
        row['raw_transcript'] = '[مصدر 1: page.png]\nقانون أوم كما ورد في المصدر'
        source = {
            'id': 1,
            'position': 1,
            'filename': 'page.png',
            'extracted_text': 'قانون أوم كما ورد في المصدر',
            'requires_review': False,
        }
        bound = _build_quality_snapshot('job-1', row, [source])
        self.assertTrue(bound['preapproval_ready'])
        changed_source = {**source, 'extracted_text': 'نص مصدر تغيّر بعد بناء النسخة'}
        stale = _build_quality_snapshot('job-1', row, [changed_source])
        self.assertFalse(stale['preapproval_ready'])
        check = next(x for x in stale['checks'] if x['id'] == 'source_transcript_binding')
        self.assertFalse(check['ok'])

    def test_diagram_change_changes_export_contract(self):
        """Diagram parameter edits must alter the manifest hash used by export approval."""
        row = self._base_row()
        row['structured_json'] = {
            **row['structured_json'],
            'diagram_specs': [{
                'normalized_kind': 'magnetic_field',
                'parameters': {
                    'current_direction': 'out_of_page',
                    'field_direction': 'counterclockwise',
                },
                'diagram_engine': {
                    'svg': '<svg></svg>',
                    'review_required': True,
                },
                'visual_provenance': {'origin': 'source_derived_spec'},
            }],
        }
        before = _build_quality_snapshot('job-1', row, [{'id': 1, 'requires_review': False}])
        changed = dict(row)
        changed_structured = dict(row['structured_json'])
        changed_diagrams = [dict(row['structured_json']['diagram_specs'][0])]
        changed_diagrams[0]['parameters'] = {
            'current_direction': 'into_page',
            'field_direction': 'clockwise',
        }
        changed_structured['diagram_specs'] = changed_diagrams
        changed['structured_json'] = changed_structured
        after = _build_quality_snapshot('job-1', changed, [{'id': 1, 'requires_review': False}])
        self.assertNotEqual(
            before['diagram_manifest']['hash'],
            after['diagram_manifest']['hash'],
        )
        self.assertNotEqual(_snapshot_contract(before), _snapshot_contract(after))

    def test_concurrent_exports_never_share_staging_object_key(self):
        """Competing exports for the same contract must own distinct immutable storage objects."""
        content_hash = 'a' * 64
        diagram_hash = 'b' * 64
        with ThreadPoolExecutor(max_workers=8) as pool:
            keys = list(pool.map(
                lambda _: _final_pdf_object_key('job-1', content_hash, diagram_hash),
                range(24),
            ))
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            self.assertIn(content_hash[:16], key)
            self.assertIn(diagram_hash[:16], key)
            self.assertTrue(key.endswith('.pdf'))

    def test_cleanup_preserves_a_committed_pdf_object(self):
        """Failed export cleanup must never delete an object already referenced by the committed row."""
        con = MagicMock()
        con.execute.return_value.fetchone.return_value = {'pdf_object_key': 'promoted.pdf'}
        context = MagicMock()
        context.__enter__.return_value = con
        context.__exit__.return_value = False
        with patch('app.lesson_studio_quality.connect', return_value=context), \
             patch('app.lesson_studio_quality.delete_object') as delete_object:
            _delete_unpromoted_pdf('job-1', 'promoted.pdf')
        delete_object.assert_not_called()


class SuggestionPayloadTests(unittest.TestCase):
    def test_suggestion_payload_is_normalized_before_persistence(self):
        """Only an object containing a list of object suggestions is accepted."""
        payload = {'suggestions': [{'proposal': 'اقتراح للمراجعة'}], 'meta': {'source': 'model'}}
        normalized = _normalize_suggestion_payload(payload)
        self.assertEqual(normalized['suggestions'][0]['proposal'], 'اقتراح للمراجعة')
        self.assertIsNot(normalized, payload)
        self.assertIsNot(normalized['suggestions'][0], payload['suggestions'][0])

    def test_invalid_suggestion_shapes_are_rejected(self):
        """Scalars, arrays, and non-object suggestion entries never reach persistence."""
        invalid = [
            [],
            'text',
            {'suggestions': {}},
            {'suggestions': ['not-an-object']},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(HTTPException):
                _normalize_suggestion_payload(payload)


if __name__ == '__main__':
    unittest.main()