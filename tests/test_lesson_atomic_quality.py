import unittest
from unittest.mock import patch

from app.lesson_studio_quality import _build_quality_snapshot, _snapshot_contract


class AtomicLessonQualityTests(unittest.TestCase):
    def setUp(self):
        self.openai_patch = patch('app.lesson_studio_quality.OPENAI_REVIEW_CONFIGURED', False)
        self.reference_patch = patch('app.lesson_studio_quality.REFERENCE_REVIEW_REQUIRED', False)
        self.openai_patch.start()
        self.reference_patch.start()
        self.addCleanup(self.reference_patch.stop)
        self.addCleanup(self.openai_patch.stop)

    def _base_row(self):
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
        snap = _build_quality_snapshot('job-1', self._base_row(), [{'id': 1, 'requires_review': False}])
        self.assertTrue(snap['preapproval_ready'])
        self.assertFalse(snap['teacher_approval_fresh'])
        self.assertFalse(snap['final_ready'])
        self.assertTrue(snap['policy']['approval_and_export_recheck_locked_state'])
        self.assertTrue(snap['policy']['quality_cache_written_from_locked_state'])

    def test_teacher_approval_is_fresh_only_for_exact_locked_contract(self):
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
        row = self._base_row()
        clear = _build_quality_snapshot('job-1', row, [{'id': 1, 'requires_review': False}])
        blocked = _build_quality_snapshot('job-1', row, [{'id': 1, 'requires_review': True}])
        self.assertTrue(clear['preapproval_ready'])
        self.assertFalse(blocked['preapproval_ready'])
        check = next(x for x in blocked['checks'] if x['id'] == 'ocr_review_clear')
        self.assertEqual(check['value'], 1)

    def test_diagram_change_changes_export_contract(self):
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


if __name__ == '__main__':
    unittest.main()
