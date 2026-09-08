import unittest

from app.services.diagram_router import route_diagram
from app.services.science_diagram_extensions import render_advanced
from app.services.science_diagram_parameterized import render_parameterized


class AdvancedDiagramRoutingTests(unittest.TestCase):
    def test_resistor_network_is_detected(self):
        route = route_diagram('other', 'توصيل مقاومات على التوازي', '', 'physics')
        self.assertEqual(route.kind, 'resistor_network')
        rendered = render_advanced(route.kind, 'شبكة مقاومات', ('R1', 'R2', 'R3'))
        self.assertTrue(rendered['deterministic'])
        self.assertTrue(rendered['review_required'])
        self.assertIn('<svg', rendered['svg'])

    def test_magnetic_field_is_detected_and_review_required(self):
        route = route_diagram('', 'المجال المغناطيسي حول سلك', '', 'physics')
        self.assertEqual(route.kind, 'magnetic_field')
        rendered = render_advanced(route.kind, 'المجال', ('تيار I',))
        self.assertTrue(rendered['review_required'])
        self.assertIn('اتجاه المجال', rendered['svg'])

    def test_molecule_bond_is_detected_and_review_required(self):
        route = route_diagram('', 'رابطة كيميائية في تركيب جزيء', '', 'chemistry')
        self.assertEqual(route.kind, 'molecule_bond')
        rendered = render_advanced(route.kind, 'جزيء', ('C', 'H', 'H', 'H'))
        self.assertTrue(rendered['review_required'])
        self.assertIn('<svg', rendered['svg'])

    def test_parameterized_resistor_graph_requires_explicit_nodes(self):
        rendered = render_parameterized('resistor_network', 'شبكة', {'components': []})
        self.assertFalse(rendered['valid'])
        self.assertTrue(rendered['review_required'])

    def test_parameterized_resistor_graph_renders_explicit_topology(self):
        rendered = render_parameterized('resistor_network', 'شبكة', {
            'nodes': [
                {'id': 'A', 'x': 0.1, 'y': 0.5},
                {'id': 'B', 'x': 0.5, 'y': 0.2},
                {'id': 'C', 'x': 0.5, 'y': 0.8},
                {'id': 'D', 'x': 0.9, 'y': 0.5},
            ],
            'components': [
                {'type': 'resistor', 'from': 'A', 'to': 'B', 'label': 'R1'},
                {'type': 'resistor', 'from': 'A', 'to': 'C', 'label': 'R2'},
                {'type': 'wire', 'from': 'B', 'to': 'D'},
                {'type': 'wire', 'from': 'C', 'to': 'D'},
            ],
        })
        self.assertTrue(rendered['valid'])
        self.assertTrue(rendered['parameterized'])
        self.assertIn('R1', rendered['svg'])
        self.assertIn('R2', rendered['svg'])

    def test_parameterized_ray_diagram_only_draws_explicit_paths(self):
        rendered = render_parameterized('ray_diagram', 'عدسة', {
            'optical_element': {'type': 'convex_lens', 'x': 0.5, 'label': 'عدسة محدبة'},
            'focal_points': [0.35, 0.65],
            'rays': [
                {'points': [[0.1, 0.35], [0.5, 0.35], [0.9, 0.7]]},
            ],
        })
        self.assertTrue(rendered['valid'])
        self.assertEqual(rendered['parameter_contract'], 'explicit_ray_paths_v1')

    def test_parameterized_magnetic_field_requires_both_directions(self):
        rendered = render_parameterized('magnetic_field', 'مجال', {'current_direction': 'out_of_page'})
        self.assertFalse(rendered['valid'])

    def test_parameterized_solenoid_requires_direction_and_polarity(self):
        rendered = render_parameterized('solenoid_field', 'ملف لولبي', {
            'current_direction': 'left_to_right',
            'field_direction': 'left_to_right',
            'turns': 8,
        })
        self.assertFalse(rendered['valid'])
        self.assertIn('explicit_solenoid_polarity_required', rendered['issues'])

    def test_parameterized_solenoid_renders_only_explicit_state(self):
        rendered = render_parameterized('solenoid_field', 'ملف لولبي', {
            'current_direction': 'left_to_right',
            'field_direction': 'right_to_left',
            'north_side': 'left',
            'turns': 8,
            'label': 'L1',
        })
        self.assertTrue(rendered['valid'])
        self.assertEqual(rendered['parameter_contract'], 'explicit_solenoid_field_v1')
        self.assertIn('L1', rendered['svg'])
        self.assertIn('>N<', rendered['svg'])

    def test_parameterized_molecule_preserves_bond_order(self):
        rendered = render_parameterized('molecule_bond', 'CO2', {
            'atoms': [
                {'id': 'C', 'element': 'C', 'x': 0.5, 'y': 0.5},
                {'id': 'O1', 'element': 'O', 'x': 0.25, 'y': 0.5},
                {'id': 'O2', 'element': 'O', 'x': 0.75, 'y': 0.5},
            ],
            'bonds': [
                {'from': 'C', 'to': 'O1', 'order': 2},
                {'from': 'C', 'to': 'O2', 'order': 2},
            ],
        })
        self.assertTrue(rendered['valid'])
        self.assertEqual(rendered['parameter_contract'], 'explicit_molecule_graph_v1')

    def test_parameterized_lab_setup_requires_explicit_flow_direction(self):
        rendered = render_parameterized('chemistry_lab_setup', 'تحضير غاز', {
            'vessels': [
                {'id': 'A', 'type': 'flask', 'x': 0.15, 'y': 0.5},
                {'id': 'B', 'type': 'gas_jar', 'x': 0.8, 'y': 0.5},
            ],
            'connections': [{'from': 'A', 'to': 'B'}],
        })
        self.assertFalse(rendered['valid'])
        self.assertIn('explicit_lab_connection_direction_required', rendered['issues'])

    def test_parameterized_lab_setup_preserves_explicit_apparatus_graph(self):
        rendered = render_parameterized('chemistry_lab_setup', 'تحضير غاز', {
            'vessels': [
                {'id': 'A', 'type': 'flask', 'x': 0.15, 'y': 0.5, 'label': 'دورق'},
                {'id': 'B', 'type': 'gas_jar', 'x': 0.8, 'y': 0.5, 'label': 'وعاء تجميع'},
            ],
            'connections': [
                {'from': 'A', 'to': 'B', 'direction': 'from_to', 'label': 'أنبوب توصيل'},
            ],
        })
        self.assertTrue(rendered['valid'])
        self.assertEqual(rendered['parameter_contract'], 'explicit_lab_apparatus_v1')
        self.assertIn('دورق', rendered['svg'])
        self.assertIn('وعاء تجميع', rendered['svg'])

    def test_unknown_intent_remains_unrouted(self):
        route = route_diagram('', 'رسم غير محدد', '', 'science')
        self.assertEqual(route.reason, 'no_safe_route')
        self.assertEqual(route.confidence, 0.0)


if __name__ == '__main__':
    unittest.main()
