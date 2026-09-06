import unittest
from io import BytesIO

import fitz
from PIL import Image

from app.lesson_studio_source_editor import _render_adjusted
from app.science_reference_library import _normalize_tokens, _score_page
from app.services.diagram_router import route_diagram
from app.services.handwriting_preprocess import preprocess_handwriting
from app.services.lesson_integrity import review_source_hash
from app.services.lesson_pdf_renderer import lesson_html, render_lesson_pdf
from app.services.ocr_consensus import compare_ocr, single_provider_result
from app.services.science_diagram_extensions import render_advanced
from app.services.science_diagrams import DiagramSpec, render, validate_spec
from app.services.science_notation import classify_notation


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

    def test_science_specific_shell_remains_review_required(self):
        result = render(DiagramSpec('atom_shell', 'تركيب الذرة', ('K', 'L'), subject='chemistry'))
        self.assertIsNotNone(result['svg'])
        self.assertTrue(result['review_required'])

    def test_series_parallel_renderer_is_deterministic_but_reviewed(self):
        result = render_advanced('series_parallel_circuit', 'دائرة مركبة', ('R1', 'R2', 'R3'))
        self.assertTrue(result['deterministic'])
        self.assertTrue(result['review_required'])
        self.assertIn('R1', result['svg'])

    def test_solenoid_router_and_renderer(self):
        route = route_diagram('other', 'المجال داخل ملف لولبي', 'اتجاه المجال داخل الملف', 'physics')
        self.assertEqual(route.kind, 'solenoid_field')
        result = render_advanced(route.kind, 'ملف لولبي', ('الملف', 'B'))
        self.assertIn('<svg', result['svg'])
        self.assertTrue(result['review_required'])

    def test_chemistry_lab_setup_stays_review_required(self):
        route = route_diagram('other', 'جهاز تحضير غاز', 'دورق وأنبوب توصيل ووعاء تجميع', 'chemistry')
        self.assertEqual(route.kind, 'chemistry_lab_setup')
        result = render_advanced(route.kind, 'تحضير غاز', ('دورق', 'أنبوب', 'وعاء'))
        self.assertTrue(result['review_required'])
        self.assertIn('دورق', result['svg'])


class ScienceNotationTests(unittest.TestCase):
    def test_physics_equation_is_classified_without_rewrite(self):
        item = classify_notation('V = IR')
        self.assertEqual(item.raw, 'V = IR')
        self.assertEqual(item.kind, 'physics_or_math_equation')

    def test_chemical_reaction_is_detected(self):
        item = classify_notation('2H2 + O2 → 2H2O')
        self.assertEqual(item.raw, '2H2 + O2 → 2H2O')
        self.assertEqual(item.kind, 'chemical_equation')

    def test_unclear_notation_requires_review(self):
        item = classify_notation('V = [غير واضح] R')
        self.assertTrue(item.requires_review)


class ScientificReferenceMatchingTests(unittest.TestCase):
    def test_reference_page_with_lesson_terms_scores_higher(self):
        q = _normalize_tokens('قانون أوم فرق الجهد شدة التيار المقاومة')
        relevant = _score_page(q, 'ينص قانون أوم على العلاقة بين فرق الجهد وشدة التيار والمقاومة')
        unrelated = _score_page(q, 'يتناول هذا الفصل تركيب الذرة ومستويات الطاقة')
        self.assertGreater(relevant, unrelated)
        self.assertGreater(relevant, 0)

    def test_reference_tokens_ignore_common_stop_words(self):
        tokens = _normalize_tokens('هذا هو قانون أوم في الدائرة')
        self.assertIn('قانون', tokens)
        self.assertNotIn('هذا', tokens)
        self.assertNotIn('في', tokens)


class IntegrityTests(unittest.TestCase):
    def test_review_hash_is_stable_for_identical_content(self):
        structured = {'sections': [{'body': 'نفس النص'}]}
        a = review_source_hash('الأصل', structured)
        b = review_source_hash('الأصل', structured)
        self.assertEqual(a, b)

    def test_review_hash_changes_after_any_content_change(self):
        a = review_source_hash('الأصل', {'summary': 'أ'})
        b = review_source_hash('الأصل', {'summary': 'ب'})
        c = review_source_hash('أصل معدل', {'summary': 'أ'})
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)


class HandwritingPreprocessTests(unittest.TestCase):
    def test_preprocess_creates_derivative_without_mutating_original_bytes(self):
        img = Image.new('RGB', (320, 180), 'white')
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=85)
        original = buf.getvalue()
        snapshot = bytes(original)
        processed, ctype, report = preprocess_handwriting(original, 'image/jpeg')
        self.assertEqual(original, snapshot)
        self.assertEqual(ctype, 'image/png')
        self.assertTrue(processed.startswith(b'\x89PNG'))
        self.assertTrue(report.applied)
        self.assertTrue(report.grayscale)
        self.assertFalse(report.perspective_corrected)

    def test_pdf_is_not_modified_by_image_preprocessor(self):
        data = b'%PDF-test'
        processed, ctype, report = preprocess_handwriting(data, 'application/pdf')
        self.assertEqual(processed, data)
        self.assertEqual(ctype, 'application/pdf')
        self.assertFalse(report.applied)


class ManualSourceAdjustmentTests(unittest.TestCase):
    def image_bytes(self):
        img = Image.new('RGB', (400, 300), 'white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_crop_rotation_creates_derivative_and_preserves_input(self):
        original = self.image_bytes()
        snapshot = bytes(original)
        adjusted, meta = _render_adjusted(
            original, left=0.1, top=0.1, right=0.9, bottom=0.9,
            rotation=90, perspective_json='',
        )
        self.assertEqual(original, snapshot)
        self.assertTrue(adjusted.startswith(b'\x89PNG'))
        self.assertTrue(meta['original_preserved'])
        self.assertEqual(meta['rotation'], 90)
        self.assertNotEqual(meta['original_size'], meta['output_size'])

    def test_perspective_quad_is_applied_only_to_derivative(self):
        original = self.image_bytes()
        adjusted, meta = _render_adjusted(
            original, left=0, top=0, right=1, bottom=1, rotation=0,
            perspective_json='[0.05,0.05,0.95,0.08,0.9,0.92,0.08,0.95]',
        )
        self.assertTrue(adjusted.startswith(b'\x89PNG'))
        self.assertEqual(len(meta['perspective_points']), 8)
        self.assertTrue(meta['original_preserved'])


class LessonPDFTests(unittest.TestCase):
    def sample(self, long=False, sections=1, mode='teacher_notes'):
        text = ('شرح علمي منظم. ' * 180) if long else 'شرح علمي منظم.'
        diagram = render(DiagramSpec('simple_circuit', 'دائرة', ('مصدر', 'مقاومة')))['svg']
        headings = ['تعريف المقاومة', 'قانون أوم', 'مثال تطبيقي', 'تنبيه مهم', 'تجربة عملية']
        return {
            'title': 'درس تجريبي',
            'subject': 'physics',
            'grade_label': 'الثالث الثانوي',
            'mode': mode,
            'learning_objectives': ['فهم الفكرة'],
            'sections': [
                {'heading': headings[(i-1) % len(headings)] if sections > 1 else f'الفكرة {i}', 'body': text, 'source_only': True, 'source_refs': ['مصدر 1']}
                for i in range(1, sections + 1)
            ],
            'equations_or_rules': [{'label': 'قانون', 'expression': 'V = IR', 'notes': 'من المصدر'}],
            'diagram_specs': [{'title': 'دائرة', 'description': 'رسم', 'scientific_labels': ['مصدر', 'مقاومة'], 'diagram_engine': {'svg': diagram, 'review_required': False}}],
            'teacher_warnings': ['راجع اتجاهات الرسم'],
            'uncertain_items': [],
            'summary': 'ملخص',
        }

    def test_html_preserves_provenance(self):
        out = lesson_html(self.sample())
        self.assertIn('مصدر 1', out)
        self.assertIn('V = IR', out)

    def test_long_lesson_has_generated_toc(self):
        out = lesson_html(self.sample(sections=5))
        self.assertIn('المحتويات', out)
        self.assertIn('تجربة عملية', out)

    def test_teaching_sections_receive_visual_roles(self):
        out = lesson_html(self.sample(sections=5))
        self.assertIn('callout-definition', out)
        self.assertIn('callout-law', out)
        self.assertIn('callout-example', out)
        self.assertIn('callout-warning', out)
        self.assertIn('callout-experiment', out)

    def test_student_mode_hides_provenance_visually(self):
        out = lesson_html(self.sample(mode='student_simple'))
        self.assertIn('mode-student_simple', out)
        self.assertIn('مصدر 1', out)

    def test_pdf_is_valid_and_stamped(self):
        data = render_lesson_pdf(self.sample())
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 1000)
        doc = fitz.open(stream=data, filetype='pdf')
        self.assertGreaterEqual(doc.page_count, 1)
        text = '\n'.join(page.get_text() for page in doc)
        doc.close()
        self.assertIn('درس تجريبي', text)
        self.assertIn('1 /', text)

    def test_mobile_pdf_is_valid(self):
        data = render_lesson_pdf(self.sample(sections=5), preset='mobile')
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 1000)

    def test_long_lesson_renders_without_single_page_compression_failure(self):
        data = render_lesson_pdf(self.sample(long=True))
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 1000)


if __name__ == '__main__':
    unittest.main()
