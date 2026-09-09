from pathlib import Path
import unittest


MUTATION_FILES = (
    'app/lesson_studio_content_review.py',
    'app/lesson_studio_diagram_spec_history.py',
    'app/lesson_studio_version_history.py',
    'app/lesson_studio_review.py',
    'app/lesson_studio_source_editor.py',
    'app/lesson_studio_enhancements.py',
)


class LessonMutationInvalidationContractTests(unittest.TestCase):
    def test_scientific_mutation_paths_use_central_release_invalidation(self):
        """Scientific mutation modules must delegate stale release cleanup to one complete contract."""
        for filename in MUTATION_FILES:
            with self.subTest(filename=filename):
                source = Path(filename).read_text(encoding='utf-8')
                self.assertIn('invalidate_release_state(', source)
                self.assertNotIn('teacher_approved=FALSE', source)
                self.assertNotIn('pdf_object_key=NULL', source)

    def test_diagram_history_does_not_migrate_release_columns_on_requests(self):
        """Diagram history must rely on startup release migrations rather than repeated ALTER TABLE calls."""
        source = Path('app/lesson_studio_diagram_spec_history.py').read_text(encoding='utf-8')
        self.assertNotIn('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS teacher_approved', source)
        self.assertNotIn('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS quality_snapshot', source)
        self.assertNotIn('ALTER TABLE science_lesson_jobs ADD COLUMN IF NOT EXISTS pdf_source_hash', source)


if __name__ == '__main__':
    unittest.main()
