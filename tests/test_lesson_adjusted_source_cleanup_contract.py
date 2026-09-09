from __future__ import annotations

import ast
from pathlib import Path
import unittest


class LessonAdjustedSourceCleanupContractTests(unittest.TestCase):
    """Protect storage cleanup invariants for superseded adjusted Lesson Studio images."""

    @classmethod
    def setUpClass(cls):
        """Parse the source-editor module once for lightweight deterministic contract checks."""
        cls.path = Path('app/lesson_studio_source_editor.py')
        cls.text = cls.path.read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.text)

    @classmethod
    def _function(cls, name: str) -> ast.FunctionDef:
        """Return one named top-level source-editor function from the parsed module."""
        for node in cls.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f'{name} not found')

    @staticmethod
    def _call_names(node: ast.AST) -> list[str]:
        """Collect invoked function names in source order where AST traversal exposes them."""
        names: list[str] = []
        for item in ast.walk(node):
            if not isinstance(item, ast.Call):
                continue
            if isinstance(item.func, ast.Name):
                names.append(item.func.id)
            elif isinstance(item.func, ast.Attribute):
                names.append(item.func.attr)
        return names

    def test_adjustment_promotes_before_cleaning_replaced_derivative(self):
        """Require a successful adjustment to capture and clean the previously promoted object."""
        node = self._function('adjust_lesson_source')
        source = ast.get_source_segment(self.text, node) or ''
        self.assertIn("previous_key = current.get('adjusted_object_key')", source)
        self.assertIn('_delete_unpromoted_adjusted_source(previous_key)', source)
        self.assertLess(source.index('invalidate_release_state'), source.rindex('_delete_unpromoted_adjusted_source(previous_key)'))

    def test_reset_cleans_detached_derivative_after_release_state_update(self):
        """Require reset to detach the DB pointer before best-effort deletion of the obsolete object."""
        node = self._function('reset_source_adjustment')
        source = ast.get_source_segment(self.text, node) or ''
        self.assertIn("previous_key = current.get('adjusted_object_key')", source)
        self.assertIn('_delete_unpromoted_adjusted_source(previous_key)', source)
        self.assertLess(source.index('invalidate_release_state'), source.rindex('_delete_unpromoted_adjusted_source(previous_key)'))


if __name__ == '__main__':
    unittest.main()
