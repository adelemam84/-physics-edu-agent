import importlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import lesson_studio_content_review, lesson_studio_workspace
from app.lesson_studio_diagram_spec_history import prepare_diagram_spec


class DiagramSpecHistoryTests(unittest.TestCase):
    def test_prepare_valid_spec_normalizes_and_requires_review(self):
        result = prepare_diagram_spec('solenoid_field', 'ملف لولبي', {
            'current_direction': 'left_to_right',
            'field_direction': 'right_to_left',
            'north_side': 'left',
            'turns': 8,
            'label': 'L1',
        })
        self.assertTrue(result['valid'])
        self.assertTrue(result['renderer_called'])
        self.assertTrue(result['review_required'])
        self.assertTrue(result['render']['schema_validated'])
        self.assertTrue(result['render']['review_required'])
        self.assertFalse(result['render']['teacher_reviewed'])
        self.assertIn('<svg', result['svg'])

    def test_prepare_invalid_spec_never_calls_renderer(self):
        result = prepare_diagram_spec('magnetic_field', 'مجال', {
            'current_direction': 'out_of_page',
            'field_direction': 'counterclockwise',
            'invented_scientific_value': 'forbidden',
        })
        self.assertFalse(result['valid'])
        self.assertFalse(result['renderer_called'])
        self.assertIsNone(result['render'])
        self.assertTrue(any(
            x['type'] == 'extra_forbidden'
            for x in result['validation']['errors']
        ))

    def test_legacy_parameters_endpoint_delegates_to_strict_versioned_save(self):
        payload = '{"current_direction":"out_of_page","field_direction":"counterclockwise"}'
        with patch(
            'app.lesson_studio_content_review.save_diagram_spec',
            return_value={'updated': True, 'valid': True},
        ) as save:
            result = lesson_studio_content_review.update_diagram_parameters('job-1', 2, payload)
        self.assertTrue(result['updated'])
        save.assert_called_once()
        args = save.call_args.args
        self.assertEqual(args[0], 'job-1')
        self.assertEqual(args[1], 2)
        self.assertEqual(args[2]['current_direction'], 'out_of_page')

    def test_legacy_parameters_endpoint_rejects_invalid_json_before_save(self):
        with patch('app.lesson_studio_content_review.save_diagram_spec') as save:
            with self.assertRaises(HTTPException) as ctx:
                lesson_studio_content_review.update_diagram_parameters('job-1', 0, '{bad json')
        self.assertEqual(ctx.exception.status_code, 400)
        save.assert_not_called()

    def test_versioned_diagram_routes_are_registered(self):
        app = importlib.import_module('index').app
        paths = {route.path for route in app.routes}
        required = {
            '/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec-history',
            '/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec/preview',
            '/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec',
            '/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/spec-history/{version_no}/restore',
        }
        self.assertTrue(required.issubset(paths), required - paths)

    def test_workspace_contains_integrated_spec_editor_and_history_controls(self):
        html = lesson_studio_workspace.WORKSPACE
        self.assertIn('function previewDiagramSpec(i)', html)
        self.assertIn('function saveDiagramSpec(i)', html)
        self.assertIn('function loadDiagramHistory(i)', html)
        self.assertIn('function restoreDiagramSpec(i,v)', html)
        self.assertIn('solenoid_field', html)
        self.assertIn('chemistry_lab_setup', html)
        self.assertIn('سجل نسخ الرسم', html)
        self.assertIn('استرجاع هذه النسخة للرسم فقط', html)


if __name__ == '__main__':
    unittest.main()
