import importlib
import unittest

from app.services.science_diagram_specs import (
    preview_diagram_spec,
    schema_catalog,
    validate_diagram_spec,
)


class ScientificDiagramSpecTests(unittest.TestCase):
    def test_catalog_covers_all_parameterized_kinds(self):
        catalog = schema_catalog()
        expected = {
            'resistor_network',
            'series_parallel_circuit',
            'ray_diagram',
            'magnetic_field',
            'solenoid_field',
            'molecule_bond',
            'chemistry_lab_setup',
        }
        self.assertEqual(set(catalog['kinds']), expected)
        self.assertTrue(catalog['policy']['unknown_fields_rejected'])

    def test_extra_fields_are_rejected_before_renderer(self):
        result = validate_diagram_spec('magnetic_field', {
            'current_direction': 'out_of_page',
            'field_direction': 'counterclockwise',
            'invented_value': 'not allowed',
        })
        self.assertFalse(result['valid'])
        self.assertTrue(any(x['type'] == 'extra_forbidden' for x in result['errors']))

    def test_resistor_graph_unknown_endpoint_is_rejected(self):
        result = validate_diagram_spec('resistor_network', {
            'nodes': [
                {'id': 'A', 'x': 0.1, 'y': 0.5},
                {'id': 'B', 'x': 0.9, 'y': 0.5},
            ],
            'components': [
                {'type': 'resistor', 'from': 'A', 'to': 'C', 'label': 'R1'},
            ],
        })
        self.assertFalse(result['valid'])
        self.assertIn('component_references_unknown_node', result['errors'][0]['message'])

    def test_duplicate_atom_ids_are_rejected(self):
        result = validate_diagram_spec('molecule_bond', {
            'atoms': [
                {'id': 'A', 'element': 'C', 'x': 0.3, 'y': 0.5},
                {'id': 'A', 'element': 'O', 'x': 0.7, 'y': 0.5},
            ],
            'bonds': [{'from': 'A', 'to': 'A', 'order': 2}],
        })
        self.assertFalse(result['valid'])
        self.assertIn('duplicate_atom_id', result['errors'][0]['message'])

    def test_ray_points_must_be_normalized(self):
        result = validate_diagram_spec('ray_diagram', {
            'optical_element': {'type': 'convex_lens', 'x': 0.5},
            'rays': [{'points': [[0.1, 0.3], [1.2, 0.4]]}],
        })
        self.assertFalse(result['valid'])

    def test_valid_lab_spec_previews_after_validation(self):
        result = preview_diagram_spec('chemistry_lab_setup', 'تحضير غاز', {
            'vessels': [
                {'id': 'A', 'type': 'flask', 'x': 0.15, 'y': 0.5, 'label': 'دورق'},
                {'id': 'B', 'type': 'gas_jar', 'x': 0.8, 'y': 0.5, 'label': 'وعاء تجميع'},
            ],
            'connections': [
                {'from': 'A', 'to': 'B', 'direction': 'from_to', 'label': 'أنبوب توصيل'},
            ],
        })
        self.assertTrue(result['valid'])
        self.assertTrue(result['renderer_called'])
        self.assertTrue(result['review_required'])
        self.assertFalse(result['approval_state_changed'])
        self.assertIn('<svg', result['svg'])

    def test_invalid_preview_never_calls_renderer(self):
        result = preview_diagram_spec('solenoid_field', 'ملف', {
            'current_direction': 'left_to_right',
            'field_direction': 'left_to_right',
            'turns': 8,
        })
        self.assertFalse(result['valid'])
        self.assertFalse(result['renderer_called'])
        self.assertIsNone(result['svg'])

    def test_builder_routes_are_registered(self):
        app = importlib.import_module('index').app
        paths = {route.path for route in app.routes}
        required = {
            '/api/admin/lesson-studio/diagram-specs',
            '/api/admin/lesson-studio/diagram-specs/validate',
            '/api/admin/lesson-studio/diagram-specs/preview',
            '/admin/lesson-studio/diagram-specs',
        }
        self.assertTrue(required.issubset(paths), required - paths)


if __name__ == '__main__':
    unittest.main()
