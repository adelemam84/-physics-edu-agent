import unittest

from app.services.ocr_consensus import compare_ocr, single_provider_result
from app.services.science_diagrams import DiagramSpec, render, validate_spec
from app.services.lesson_pdf_renderer import render_lesson_pdf, lesson_html


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


class LessonPDFTests(unittest.TestCase):
    def sample(self, long=False):
        text = ('شرح علمي منظم. ' * 180) if long else 'شرح علمي منظم.'
        diagram = render(DiagramSpec('simple_circuit', 'دائرة', ('مصدر', 'مقاومة')))['svg']
        return {
            'title': 'درس تجريبي',
            'subject': 'physics',
            'grade_label': 'الثالث الثانوي',
            'mode': 'teacher_notes',
            'learning_objectives': ['فهم الفكرة'],
            'sections': [{'heading': 'الفكرة', 'body': text, 'source_only': True, 'source_refs': ['مصدر 1']}],
            'equations_or_rules': [{'label': 'قانون', 'expression': 'V = IR', 'notes': 'من المصدر'}],
            'diagram_specs': [{'title': 'دائرة', 'description': 'رسم', 'scientific_labels': ['مصدر', 'مقاومة'], 'diagram_engine': {'svg': diagram, 'review_required': False}}],
            'teacher_warnings': [],
            'uncertain_items': [],
            'summary': 'ملخص',
        }

    def test_html_preserves_provenance(self):
        out = lesson_html(self.sample())
        self.assertIn('مصدر 1', out)
        self.assertIn('V = IR', out)

    def test_pdf_is_valid(self):
        data = render_lesson_pdf(self.sample())
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 1000)

    def test_long_lesson_renders_without_single_page_compression_failure(self):
        data = render_lesson_pdf(self.sample(long=True))
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 1000)


if __name__ == '__main__':
    unittest.main()
