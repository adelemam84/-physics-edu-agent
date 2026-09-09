from __future__ import annotations

import ast
from pathlib import Path
import unittest


class LessonVersionBaselineContractTests(unittest.TestCase):
    """Protect the one-baseline-per-job serialization contract for Lesson Studio history."""

    @classmethod
    def setUpClass(cls):
        """Parse version-history source once for deterministic structural assertions."""
        cls.text = Path('app/lesson_studio_version_history.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.text)

    @classmethod
    def _function_source(cls, name: str) -> str:
        """Return source text for one named top-level function."""
        for node in cls.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(cls.text, node) or ''
        raise AssertionError(f'{name} not found')

    def test_initial_snapshot_locks_job_before_existence_check(self):
        """Require the job row lock to serialize the check-and-insert baseline transaction."""
        source = self._function_source('ensure_initial_snapshot')
        lock_at = source.index('FOR UPDATE')
        exists_at = source.index('SELECT 1 FROM science_lesson_versions')
        insert_at = source.index('_insert_job_snapshot')
        self.assertLess(lock_at, exists_at)
        self.assertLess(exists_at, insert_at)

    def test_initial_snapshot_no_longer_delegates_to_second_transaction(self):
        """Keep baseline insertion in the same transaction instead of calling snapshot_job afterward."""
        source = self._function_source('ensure_initial_snapshot')
        self.assertNotIn('snapshot_job(', source)
        self.assertIn("'initial_snapshot'", source)


if __name__ == '__main__':
    unittest.main()
