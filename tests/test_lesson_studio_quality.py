import unittest

from app.services.ocr_consensus import compare_ocr, single_provider_result
from app.services.science_diagrams import DiagramSpec, render, validate_spec


class OCRConsensusTests(unittest.TestCase):
    def test_identical_scientific_text_is_green(self):
        r = compare_ocr('قانون أوم\nV = IR', 'قانون أوم\nV = IR')
        self.assertEqual(r.confidence_band, 'green')
        self.assertFalse(r.requires_review)
        self.assertEqual(r.score, 1.0)

    def test_equation_conflict_is_critical(self):
        r = compare_ocr('V = IR', 'V = I/R')
        self.assertTrue(r.requires_review)
        self.assertEqual(r.confidence_band, 'red')
        self.assertTrue(any(x.kind == 'scientific_notation_conflict' for x in r.conflicts))
        self.assertEqual(r.text, 'V = IR')

    def test_unclear_marker_never_passes_silently(self):
        r = compare_ocr('القيمة [غير واضح] أمبير', 'القيمة 2 أمبير')
        self.assertTrue(r.requires_review)
        self.assertTrue(any(x.kind == 'unclear_source' for x in r.conflicts))

    def test_single_provider_is_not_claimed_as_dual_verified(self):
        r = single_provider_result('نص واضح')
        self.assertTrue(r.requires_review)
        self.assertIn(r.confidence_band, {'yellow', 'red'})


class ScienceDiagramTests(unittest.TestCase):
    def test_simple_circuit_renderer_is_deterministic(self):
        spec = DiagramSpec('simple_circuit', 'دائرة بسيطة', ('بطارية', 'مقاومة'), subject='physics')
        result = render(spec)
        self.assertTrue(result['deterministic'])
        self.assertIsNotNone(result['svg'])
        self.assertIn('<svg', result['svg'])
        self.assertIn('بطارية', result['svg'])

    def test_unknown_diagram_is_blocked_for_review(self):
        spec = DiagramSpec('freeform_unknown', 'شكل مجهول')
        check = validate_spec(spec)
        self.assertFalse(check['valid'])
        self.assertTrue(check['review_required'])
        self.assertIsNone(render(spec)['svg'])

    def test_process_renderer_escapes_labels(self):
        spec = DiagramSpec('process', 'تجربة', ('A < B', 'C & D'))
        svg = render(spec)['svg']
        self.assertIn('A &lt; B', svg)
        self.assertIn('C &amp; D', svg)


if __name__ == '__main__':
    unittest.main()
