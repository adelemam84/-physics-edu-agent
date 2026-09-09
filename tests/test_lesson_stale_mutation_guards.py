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
        """Build canonical lesson and OCR source fixtures used by revision-guard tests."""
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
        """Require an explicit lesson revision header before any guarded mutation."""
        with self.assertRaises(HTTPException) as ctx:
            lesson_content_precondition(None)
        self.assertEqual(ctx.exception.status_code, 428)

    def test_malformed_content_precondition_is_rejected_without_type_error(self):
        """Reject non-hex and non-ASCII revision headers before hmac.compare_digest is called."""
        for malformed in ('g' * 64, 'é' * 64, 'abc'):
            with self.subTest(malformed=malformed[:8]):
                with self.assertRaises(HTTPException) as ctx:
                    lesson_content_precondition(malformed)
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(ctx.exception.detail['action'], 'reload_workspace')

    def test_uppercase_sha256_precondition_is_normalized(self):
        """Accept hexadecimal SHA-256 revisions regardless of client-side letter casing."""
        expected = content_hash_from_row(self.job)
        self.assertEqual(lesson_content_precondition(expected.upper()), expected)
        self.assertEqual(assert_expected_content_hash(self.job, expected.upper()), expected)

    def test_stale_content_hash_cannot_overwrite_newer_lesson(self):
        """Reject a mutation based on an older teacher-visible lesson revision."""
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
        """Reject OCR approval when review evidence changed after the teacher loaded it."""
        expected = source_review_hash(self.source)
        newer = {**self.source, 'alternate_ocr_text': 'different OCR reading'}
        with self.assertRaises(HTTPException) as ctx:
            assert_expected_source_hash(newer, expected)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_malformed_source_hashes_are_rejected_safely(self):
        """Reject malformed OCR/editor revisions as HTTP conflicts instead of server errors."""
        for assertion in (assert_expected_source_hash, assert_expected_source_editor_hash):
            with self.subTest(assertion=assertion.__name__):
                with self.assertRaises(HTTPException) as ctx:
                    assertion(self.source, 'é' * 64)
                self.assertEqual(ctx.exception.status_code, 409)

    def test_competing_source_adjustments_use_distinct_revisions(self):
        """Ensure a newer adjusted-image derivative invalidates an older source-editor revision."""
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
        """Bind OCR source revisions to confidence and extracted review evidence, not text alone."""
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
        """Load one top-level function AST from a repository Python source file."""
        tree = ast.parse(Path(path).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return node
        raise AssertionError(f'{function_name} not found in {path}')

    @staticmethod
    def _call_names(node: ast.AST) -> set[str]:
        """Collect simple and attribute call names from a function AST."""
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
        """Collect identifier references from a function AST for dependency-contract assertions."""
        return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}

    def test_scientific_mutations_recheck_locked_content_revision(self):
        """Keep every scientific mutation on the locked content-revision guard path."""
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
        """Keep OCR and source-editor writes bound to their exact visible source revisions."""
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
        """Require the public mutation endpoints to expose the shared lesson-content precondition dependency."""
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

    def test_version_history_returns_guard_compatible_hashes(self):
        """Keep current/restored version-history response hashes aligned with X-Lesson-Content-Hash validation."""
        for function_name in ('list_lesson_versions', 'restore_lesson_version'):
            with self.subTest(function=function_name):
                node = self._function('app/lesson_studio_version_history.py', function_name)
                self.assertIn('content_hash_from_row', self._call_names(node))

    def test_workspace_concurrency_patch_fails_loudly_on_marker_drift(self):
        """Ensure startup cannot silently skip the required workspace concurrency patch."""
        tree = ast.parse(Path('app/lesson_studio_workspace_concurrency.py').read_text(encoding='utf-8'))
        raises = [node for node in ast.walk(tree) if isinstance(node, ast.Raise)]
        self.assertGreaterEqual(len(raises), 2)

    def test_source_editor_ui_reloads_revision_when_ids_change(self):
        """Keep cached source-editor revisions keyed to the job/source identifiers currently in the form."""
        text = Path('app/lesson_studio_source_editor_ui.py').read_text(encoding='utf-8')
        self.assertIn('function revisionMatchesIds()', text)
        self.assertIn('async function ensureMatchingRevision()', text)
        self.assertIn('!revisionMatchesIds()', text)


if __name__ == '__main__':
    unittest.main()
