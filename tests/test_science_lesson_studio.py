import unittest

from app.science_lesson_studio import OUTPUT_MODES, SUBJECTS, _render_pdf, _safe_filename


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
