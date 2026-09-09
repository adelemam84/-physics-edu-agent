import unittest
from unittest.mock import MagicMock, patch

from app.services.lesson_release_state import (
    _RELEASE_COLUMNS,
    _RELEASE_OBJECTS,
    ensure_release_state_schema,
)


class LessonReleaseStateSchemaTests(unittest.TestCase):
    def test_startup_migration_applies_release_schema_once_in_order(self):
        """Release-state DDL belongs to the startup migration, not individual request handlers."""
        con = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = con
        context.__exit__.return_value = False

        with patch('app.science_lesson_studio._schema') as base_schema, \
             patch('app.services.lesson_release_state.connect', return_value=context):
            ensure_release_state_schema()

        base_schema.assert_called_once_with()
        statements = [call.args[0] for call in con.execute.call_args_list]
        self.assertEqual(statements, list(_RELEASE_COLUMNS) + list(_RELEASE_OBJECTS))
        self.assertEqual(len(_RELEASE_COLUMNS), len(set(_RELEASE_COLUMNS)))
        self.assertEqual(len(_RELEASE_OBJECTS), len(set(_RELEASE_OBJECTS)))

    def test_release_migration_contains_all_atomic_binding_columns(self):
        """Startup migration must retain every hash/review field used by atomic approval and export."""
        ddl = '\n'.join(_RELEASE_COLUMNS)
        required = {
            'teacher_approval_source_hash',
            'teacher_approval_diagram_hash',
            'quality_snapshot',
            'second_review_source_hash',
            'reference_review_hash',
            'pdf_source_hash',
            'pdf_diagram_manifest_hash',
        }
        for column in required:
            with self.subTest(column=column):
                self.assertIn(column, ddl)


if __name__ == '__main__':
    unittest.main()
