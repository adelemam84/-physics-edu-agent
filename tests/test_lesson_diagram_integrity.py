import unittest

from app.lesson_studio_approval_state import approval_state_from_snapshot
from app.services.lesson_diagram_integrity import diagram_manifest, diagram_spec_hash


class LessonDiagramIntegrityTests(unittest.TestCase):
    def test_spec_hash_is_stable_for_same_kind_and_parameters(self):
        diagram = {
            'normalized_kind': 'magnetic_field',
            'parameters': {
                'current_direction': 'out_of_page',
                'field_direction': 'counterclockwise',
            },
        }
        self.assertEqual(diagram_spec_hash(diagram), diagram_spec_hash(dict(diagram)))

    def test_spec_hash_changes_when_scientific_parameter_changes(self):
        before = {
            'normalized_kind': 'magnetic_field',
            'parameters': {
                'current_direction': 'out_of_page',
                'field_direction': 'counterclockwise',
            },
        }
        after = {
            **before,
            'parameters': {
                'current_direction': 'into_page',
                'field_direction': 'clockwise',
            },
        }
        self.assertNotEqual(diagram_spec_hash(before), diagram_spec_hash(after))

    def test_versioned_diagram_requires_approval_for_exact_spec_hash(self):
        diagram = {
            'normalized_kind': 'solenoid_field',
            'diagram_spec_versioned': True,
            'parameters': {
                'current_direction': 'left_to_right',
                'field_direction': 'right_to_left',
                'north_side': 'left',
                'turns': 8,
            },
            'diagram_engine': {
                'svg': '<svg></svg>',
                'review_required': False,
                'teacher_reviewed': True,
                'approved_spec_hash': 'old-hash',
            },
        }
        manifest = diagram_manifest({'diagram_specs': [diagram]})
        self.assertEqual(manifest['version_bound_total'], 1)
        self.assertEqual(manifest['stale_or_unapproved'], 1)
        self.assertFalse(manifest['items'][0]['approval_fresh'])

        diagram['diagram_engine']['approved_spec_hash'] = diagram_spec_hash(diagram)
        manifest = diagram_manifest({'diagram_specs': [diagram]})
        self.assertEqual(manifest['stale_or_unapproved'], 0)
        self.assertTrue(manifest['items'][0]['approval_fresh'])

    def test_manifest_hash_changes_after_any_diagram_spec_change(self):
        structured = {
            'diagram_specs': [{
                'normalized_kind': 'resistor_network',
                'parameters': {'resistors': [10, 20], 'connection': 'series'},
            }]
        }
        before = diagram_manifest(structured)['hash']
        structured['diagram_specs'][0]['parameters']['resistors'][1] = 30
        after = diagram_manifest(structured)['hash']
        self.assertNotEqual(before, after)

    def test_pdf_gate_requires_matching_diagram_manifest_hash(self):
        snapshot = {
            'checks': [
                {'id': 'ocr_review_clear', 'ok': True, 'value': 0},
                {'id': 'notation_review_clear', 'ok': True, 'value': 0},
                {'id': 'diagram_review_clear', 'ok': True, 'value': 0},
                {'id': 'diagram_version_binding', 'ok': True, 'value': 0},
                {'id': 'scientific_reference_alignment', 'ok': True, 'value': {'required': False, 'present': False}},
                {'id': 'independent_second_review', 'ok': True, 'value': 'optional_not_configured'},
            ],
            'preapproval_ready': True,
            'teacher_approved': True,
            'teacher_approval_fresh': True,
            'final_ready': True,
        }
        stale = approval_state_from_snapshot(
            snapshot,
            pdf_object_key='lesson.pdf',
            pdf_source_hash='content-1',
            current_hash='content-1',
            pdf_diagram_manifest_hash='diagram-old',
            current_diagram_manifest_hash='diagram-new',
        )
        gate = next(x for x in stale['gates'] if x['gate'] == 'final_pdf_export')
        self.assertEqual(gate['state'], 'pending')
        self.assertFalse(gate['details']['fresh_for_current_diagram_manifest'])

        fresh = approval_state_from_snapshot(
            snapshot,
            pdf_object_key='lesson.pdf',
            pdf_source_hash='content-1',
            current_hash='content-1',
            pdf_diagram_manifest_hash='diagram-new',
            current_diagram_manifest_hash='diagram-new',
        )
        gate = next(x for x in fresh['gates'] if x['gate'] == 'final_pdf_export')
        self.assertEqual(gate['state'], 'complete')
        self.assertTrue(gate['details']['fresh_for_current_diagram_manifest'])

    def test_stale_teacher_approval_is_not_counted_complete(self):
        snapshot = {
            'checks': [
                {'id': 'ocr_review_clear', 'ok': True, 'value': 0},
                {'id': 'notation_review_clear', 'ok': True, 'value': 0},
                {'id': 'diagram_review_clear', 'ok': True, 'value': 0},
                {'id': 'diagram_version_binding', 'ok': True, 'value': 0},
                {'id': 'scientific_reference_alignment', 'ok': True, 'value': {'required': False, 'present': False}},
                {'id': 'independent_second_review', 'ok': True, 'value': 'optional_not_configured'},
            ],
            'preapproval_ready': True,
            'teacher_approved': True,
            'teacher_approval_fresh': False,
            'final_ready': False,
        }
        state = approval_state_from_snapshot(
            snapshot,
            pdf_object_key=None,
            pdf_source_hash=None,
            current_hash='content-new',
            current_diagram_manifest_hash='diagram-new',
        )
        teacher = next(x for x in state['gates'] if x['gate'] == 'teacher_approval')
        self.assertEqual(teacher['state'], 'pending')
        self.assertFalse(teacher['details']['fresh_for_current_content_and_diagrams'])


if __name__ == '__main__':
    unittest.main()
