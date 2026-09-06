import unittest

from app.services.diagram_router import route_diagram
from app.services.science_diagram_extensions import render_advanced


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

    def test_unknown_intent_remains_unrouted(self):
        route = route_diagram('', 'رسم غير محدد', '', 'science')
        self.assertEqual(route.reason, 'no_safe_route')
        self.assertEqual(route.confidence, 0.0)


if __name__ == '__main__':
    unittest.main()
