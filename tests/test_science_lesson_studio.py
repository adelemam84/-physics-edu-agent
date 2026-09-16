import unittest
import re

from app.science_lesson_studio import OUTPUT_MODES, SUBJECTS, _render_pdf, _safe_filename
from app.services.lesson_pdf_renderer import PDF_THEMES, render_lesson_pdf
from app.services.visual_summary import build_visual_summary, render_flowchart_svg, render_mindmap_svg, render_slides_pptx
import fitz


class ScienceLessonStudioTests(unittest.TestCase):
    def test_supported_subjects_are_general_science(self):
        self.assertEqual(SUBJECTS, {'physics', 'chemistry', 'science'})

    def test_output_modes_cover_teacher_student_revision(self):
        self.assertEqual(OUTPUT_MODES, {'student_simple', 'teacher_notes', 'quick_revision'})

    def test_safe_filename_removes_unsafe_characters(self):
        name = _safe_filename('../../شرح علوم (1).png')
        self.assertNotIn('/', name)
        self.assertNotIn(' ', name)
        self.assertTrue(name.endswith('.png'))

    def test_pdf_themes_are_available(self):
        self.assertEqual(set(PDF_THEMES), {'classic_academic', 'modern_classroom', 'exam_revision', 'student_handout'})

    def test_all_pdf_themes_render_valid_pdf(self):
        structured = {
            'title': 'درس تجريبي',
            'subject': 'physics',
            'grade_label': 'الثالث الثانوي',
            'mode': 'teacher_notes',
            'sections': [{'heading': 'قانون', 'body': 'شرح مبسط للمحتوى.', 'source_refs': ['مصدر 1']}],
            'summary': 'ملخص الدرس',
        }
        for theme in PDF_THEMES:
            with self.subTest(theme=theme):
                data = render_lesson_pdf(structured, theme=theme)
                self.assertTrue(data.startswith(b'%PDF'))
                self.assertGreater(len(data), 500)

    def test_toc_contains_real_page_numbers_after_stabilized_layout(self):
        structured = {
            'title': 'درس طويل',
            'subject': 'physics',
            'grade_label': 'الثالث الثانوي',
            'mode': 'teacher_notes',
            'sections': [
                {'heading': f'القسم {i}', 'body': ('شرح عربي طويل. ' * 180), 'source_refs': [f'مصدر {i}']}
                for i in range(1, 6)
            ],
            'equations_or_rules': [{'label': 'قانون', 'expression': 'V = I R', 'notes': 'علاقة تجريبية'}],
            'summary': 'ملخص نهائي',
        }
        data = render_lesson_pdf(structured)
        doc = fitz.open(stream=data, filetype='pdf')
        self.assertGreater(doc.page_count, 2)
        first_page = doc[0].get_text()
        numeric_tokens = set(re.findall(r'(?<!\d)(\d+)(?!\d)', first_page))
        self.assertTrue({'1', '2', '3', '4', '5'}.issubset(numeric_tokens), numeric_tokens)
        doc.close()

    def test_arabic_and_equation_text_survive_pdf_extraction(self):
        structured = {
            'title': 'قانون أوم',
            'subject': 'physics',
            'grade_label': 'الثالث الثانوي',
            'mode': 'teacher_notes',
            'sections': [
                {'heading': 'العلاقة بين الجهد والتيار', 'body': 'يزداد فرق الجهد بزيادة شدة التيار.', 'source_refs': ['ص 1']},
                {'heading': 'تعريف', 'body': 'نص عربي واضح.', 'source_refs': ['ص 2']},
                {'heading': 'مثال', 'body': 'مثال تطبيقي.', 'source_refs': ['ص 3']},
                {'heading': 'ملاحظة', 'body': 'ملاحظة مهمة.', 'source_refs': ['ص 4']},
            ],
            'equations_or_rules': [{'label': 'قانون أوم', 'expression': 'V = I × R', 'notes': 'V بالفولت'}],
            'summary': 'ملخص عربي',
        }
        data = render_lesson_pdf(structured)
        doc = fitz.open(stream=data, filetype='pdf')
        text = '\n'.join(page.get_text() for page in doc)
        self.assertIn('V = I', text)
        self.assertGreater(len(text.strip()), 100)
        doc.close()

    def test_diagram_attachment_has_visual_provenance_contract(self):
        from app.science_lesson_studio import _attach_diagram_engine
        structured={'diagram_specs':[{'kind':'circuit','title':'دائرة','scientific_labels':['بطارية','مقاومة']}]}
        out=_attach_diagram_engine(structured,'physics')
        p=out['diagram_specs'][0]['visual_provenance']
        self.assertEqual(p['origin'],'source_derived_spec')
        self.assertFalse(p['ai_generated_image'])
        self.assertTrue(p['source_labels_preserved'])

    def test_visual_summary_preserves_source_refs(self):
        structured={'title':'قانون أوم','subject':'physics','sections':[{'heading':'القانون','body':'V = IR','source_refs':['مصدر 1']}],'summary':'ملخص'}
        out=build_visual_summary(structured)
        self.assertEqual(out['sections'][0]['source_refs'],['مصدر 1'])
        self.assertTrue(out['policy']['source_grounded_only'])

    def test_visual_summary_svg_outputs_are_valid(self):
        summary=build_visual_summary({'title':'درس','sections':[{'heading':'أ','body':'ب','source_refs':['ص1']}],'summary':'س'})
        self.assertIn('<svg',render_mindmap_svg(summary))
        self.assertIn('<svg',render_flowchart_svg(summary))
        self.assertIn('ص1',render_mindmap_svg(summary))

    def test_visual_summary_pptx_is_valid_zip(self):
        summary=build_visual_summary({'title':'درس','subject':'physics','sections':[{'heading':'أ','body':'ب','source_refs':['ص1']}],'summary':'س'})
        data=render_slides_pptx(summary)
        self.assertTrue(data.startswith(b'PK'))
        self.assertGreater(len(data),1000)

    def test_pdf_renderer_returns_pdf_bytes(self):
        data = _render_pdf({
            'title': 'درس تجريبي',
            'sections': [{'heading': 'مقدمة', 'body': 'شرح مبسط للمحتوى.'}],
            'diagram_specs': [{'title': 'رسم', 'description': 'مخطط توضيحي', 'scientific_labels': ['أ', 'ب']}],
            'summary': 'ملخص الدرس',
        })
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertGreater(len(data), 500)


if __name__ == '__main__':
    unittest.main()
