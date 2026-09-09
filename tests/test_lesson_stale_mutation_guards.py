from __future__ import annotations

import ast
from pathlib import Path
import unittest

from fastapi import HTTPException

from app.services.lesson_mutation_guard import (
    assert_expected_content_hash,
    assert_expected_source_editor_hash,
    assert_expected_source_hash,
    content_hash_from_row,
    lesson_content_precondition,
    source_editor_hash,
    source_review_hash,
)


class LessonStaleMutationGuardTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            'raw_transcript': 'source text',
            'structured_json': {'sections': [{'heading': 'A', 'body': 'B'}]},
        }
        self.source = {
            'id': 7,
            'extracted_text': 'measured value',
            'alternate_ocr_text': 'measured value',
            'confidence': 0.91,
            'ocr_confidence_band': 'yellow',
            'ocr_conflicts': [],
            'requires_review': True,
        }

    def test_missing_content_precondition_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            lesson_content_precondition(None)
        self.assertEqual(ctx.exception.status_code, 428)

    def test_stale_content_hash_cannot_overwrite_newer_lesson(self):
        expected = content_hash_from_row(self.job)
        newer = {
            **self.job,
            'structured_json': {'sections': [{'heading': 'A', 'body': 'newer teacher edit'}]},
        }
        with self.assertRaises(HTTPException) as ctx:
            assert_expected_content_hash(newer, expected)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail['action'], 'reload_workspace')

    def test_stale_ocr_source_hash_cannot_approve_newer_ocr_state(self):
        expected = source_review_hash(self.source)
        newer = {**self.source, 'alternate_ocr_text': 'different OCR reading'}
        with self.assertRaises(HTTPException) as ctx:
            assert_expected_source_hash(newer, expected)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_competing_source_adjustments_use_distinct_revisions(self):
        first_visible = {
            **self.source,
            'adjusted_object_key': 'lesson-studio/job/adjusted-a.png',
            'adjustment_meta': {'rotation': 0},
        }
        expected = source_editor_hash(first_visible)
        winner = {
            **first_visible,
            'adjusted_object_key': 'lesson-studio/job/adjusted-b.png',
            'adjustment_meta': {'rotation': 90},
        }
        self.assertNotEqual(expected, source_editor_hash(winner))
        with self.assertRaises(HTTPException) as ctx:
            assert_expected_source_editor_hash(winner, expected)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail['action'], 'reload_source_editor')

    def test_source_review_hash_changes_when_review_evidence_changes(self):
        original = source_review_hash(self.source)
        rerun = {
            **self.source,
            'extracted_text': 'rerun OCR text',
            'confidence': 0.97,
            'ocr_confidence_band': 'green',
        }
        self.assertNotEqual(original, source_review_hash(rerun))


class LessonMutationEndpointContractTests(unittest.TestCase):
    @staticmethod
    def _function(path: str, function_name: str) -> ast.FunctionDef:
        tree = ast.parse(Path(path).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return node
        raise AssertionError(f'{function_name} not found in {path}')

    @staticmethod
    def _call_names(node: ast.AST) -> set[str]:
        names: set[str] = set()
        for item in ast.walk(node):
            if not isinstance(item, ast.Call):
                continue
            if isinstance(item.func, ast.Name):
                names.add(item.func.id)
            elif isinstance(item.func, ast.Attribute):
                names.add(item.func.attr)
        return names

    @staticmethod
    def _identifier_names(node: ast.AST) -> set[str]:
        return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}

    def test_scientific_mutations_recheck_locked_content_revision(self):
        cases = (
            ('app/lesson_studio_content_review.py', '_save_structured', 'assert_expected_content_hash'),
            ('app/lesson_studio_quality.py', 'approve_lesson_content', 'assert_expected_content_hash'),
            ('app/lesson_studio_quality.py', 'revoke_lesson_content_approval', 'assert_expected_content_hash'),
            ('app/lesson_studio_quality.py', 'export_final_lesson_pdf', 'assert_expected_content_hash'),
            ('app/lesson_studio_version_history.py', 'restore_lesson_version', 'assert_expected_content_hash'),
            ('app/lesson_studio_diagram_spec_history.py', '_persist_diagram_spec', 'assert_expected_content_hash'),
            ('app/lesson_studio_review.py', 'approve_lesson_source', 'assert_expected_content_hash'),
            ('app/lesson_studio_review.py', 'reopen_lesson_source', 'assert_expected_content_hash'),
            ('app/lesson_studio_source_editor.py', 'adjust_lesson_source', 'lock_job_for_mutation'),
            ('app/lesson_studio_source_editor.py', 'rerun_adjusted_source_ocr', 'lock_job_for_mutation'),
            ('app/lesson_studio_source_editor.py', 'reset_source_adjustment', 'lock_job_for_mutation'),
        )
        for path, function_name, required_call in cases:
            with self.subTest(path=path, function=function_name):
                node = self._function(path, function_name)
                self.assertIn(required_call, self._call_names(node))

    def test_source_specific_mutations_recheck_source_revision(self):
        cases = (
            ('app/lesson_studio_review.py', 'approve_lesson_source', 'assert_expected_source_hash'),
            ('app/lesson_studio_review.py', 'reopen_lesson_source', 'assert_expected_source_hash'),
            ('app/lesson_studio_source_editor.py', 'adjust_lesson_source', 'assert_expected_source_editor_hash'),
            ('app/lesson_studio_source_editor.py', 'rerun_adjusted_source_ocr', 'assert_expected_source_editor_hash'),
            ('app/lesson_studio_source_editor.py', 'reset_source_adjustment', 'assert_expected_source_editor_hash'),
        )
        for path, function_name, required_call in cases:
            with self.subTest(path=path, function=function_name):
                node = self._function(path, function_name)
                self.assertIn(required_call, self._call_names(node))

    def test_external_mutation_endpoints_accept_explicit_content_revision(self):
        cases = (
            ('app/lesson_studio_quality.py', 'approve_lesson_content'),
            ('app/lesson_studio_quality.py', 'revoke_lesson_content_approval'),
            ('app/lesson_studio_quality.py', 'export_final_lesson_pdf'),
            ('app/lesson_studio_version_history.py', 'restore_lesson_version'),
            ('app/lesson_studio_diagram_spec_history.py', 'save_job_diagram_spec'),
            ('app/lesson_studio_diagram_spec_history.py', 'restore_diagram_spec_version'),
            ('app/lesson_studio_review.py', 'approve_lesson_source'),
            ('app/lesson_studio_review.py', 'reopen_lesson_source'),
            ('app/lesson_studio_source_editor.py', 'adjust_lesson_source'),
            ('app/lesson_studio_source_editor.py', 'rerun_adjusted_source_ocr'),
            ('app/lesson_studio_source_editor.py', 'reset_source_adjustment'),
        )
        for path, function_name in cases:
            with self.subTest(path=path, function=function_name):
                node = self._function(path, function_name)
                args = {arg.arg for arg in node.args.args}
                self.assertIn('expected_content_hash', args)
                self.assertIn('lesson_content_precondition', self._identifier_names(node))


if __name__ == '__main__':
    unittest.main()
