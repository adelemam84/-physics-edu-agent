from __future__ import annotations

import inspect
import unittest

from app.acceptance_work_queue import (
    PAGE,
    acceptance_work_queue_page,
    acceptance_work_queue_snapshot,
)


def _content(*, covered: bool = True, qa: int = 0) -> dict:
    """Build a deterministic current-curriculum fixture."""
    return {
        'active': True,
        'academic_year': '2026/2027',
        'content_complete': covered and qa == 0,
        'lessons': [
            {
                'id': 101,
                'title': 'الدرس الأول',
                'term_id': 1,
                'chapter': 'الفصل الأول',
                'covered': covered,
                'approved_explanatory_mapping_count': 1 if covered else 0,
            },
            {
                'id': 102,
                'title': 'الدرس الثاني',
                'term_id': 1,
                'chapter': 'الفصل الأول',
                'covered': True,
                'approved_explanatory_mapping_count': 1,
            },
        ],
        'qa_open_by_reason': (
            [{'reason_code': 'visual_transcription_required', 'total': qa}]
            if qa
            else []
        ),
    }


def _studio(*, failing: str | None = None, owner: str = 'teacher') -> dict:
    """Build a complete Lesson Studio acceptance fixture."""
    ids = (
        'schema',
        'runtime',
        'release_binding_integrity',
        'reference_pdf',
        'curriculum_map',
        'handwritten_job',
        'ocr_review',
        'reference_review',
        'teacher_approval',
        'final_pdf',
    )
    checks = []
    for check_id in ids:
        is_system = check_id in {'schema', 'runtime', 'release_binding_integrity'}
        check_owner = 'system' if is_system else owner
        checks.append({
            'id': check_id,
            'ok': check_id != failing,
            'owner': check_owner,
            'label': check_id,
            'detail': 'blocked' if check_id == failing else 'ready',
        })
    return {
        'checks': checks,
        'platform_ready': failing not in {'schema', 'runtime', 'release_binding_integrity'},
        'acceptance_ready': failing is None,
    }


def _e2e(ready: bool) -> dict:
    """Build the aggregate Phase AA result used only as an independent consistency guard."""
    return {'overall_ready': ready}


class AcceptanceWorkQueueTests(unittest.TestCase):
    """Protect concrete acceptance tasks and preserve all human/scientific gates."""

    def test_uncovered_lesson_becomes_individual_source_task(self):
        """Each uncovered lesson must appear independently rather than as an opaque aggregate count."""
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=_content(covered=False),
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(False),
        )
        items = {item['id']: item for item in snapshot['items']}
        self.assertIn('curriculum-source:101', items)
        self.assertNotIn('curriculum-source:102', items)
        self.assertEqual(items['curriculum-source:101']['owner'], 'teacher')
        self.assertEqual(items['curriculum-source:101']['priority'], 1)

    def test_qa_bucket_preserves_reason_and_count(self):
        """Question QA evidence must keep its exact reason bucket and live count."""
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=_content(qa=7),
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(False),
        )
        item = next(x for x in snapshot['items'] if x['id'] == 'question-qa:visual_transcription_required')
        self.assertEqual(item['evidence']['count'], 7)
        self.assertEqual(item['priority'], 2)
        self.assertEqual(item['owner'], 'teacher')

    def test_system_studio_blocker_is_first(self):
        """System failures must outrank human source and review work."""
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=_content(covered=False, qa=2),
            studio_snapshot=_studio(failing='runtime'),
            e2e_snapshot=_e2e(False),
        )
        self.assertEqual(snapshot['next_action']['id'], 'lesson-studio:runtime')
        self.assertEqual(snapshot['next_action']['owner'], 'system')
        self.assertEqual(snapshot['next_action']['priority'], 0)

    def test_missing_expected_studio_check_fails_closed(self):
        """A missing upstream check becomes a system task instead of disappearing from the queue."""
        studio = _studio()
        studio['checks'] = [item for item in studio['checks'] if item['id'] != 'final_pdf']
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=_content(),
            studio_snapshot=studio,
            e2e_snapshot=_e2e(False),
        )
        item = next(x for x in snapshot['items'] if x['id'] == 'lesson-studio:missing:final_pdf')
        self.assertEqual(item['owner'], 'system')
        self.assertFalse(snapshot['ready'])

    def test_malformed_upstream_lists_fail_closed(self):
        """Malformed lesson or check evidence must create explicit system blockers."""
        content = _content()
        content['lessons'] = ['malformed']
        studio = _studio()
        studio['checks'] = 'malformed'
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=content,
            studio_snapshot=studio,
            e2e_snapshot=_e2e(False),
        )
        ids = {item['id'] for item in snapshot['items']}
        self.assertIn('malformed:content_completion:lessons', ids)
        self.assertIn('malformed:lesson_studio_acceptance:checks', ids)
        self.assertGreater(snapshot['summary']['system_open'], 0)

    def test_malformed_lesson_boolean_fails_closed(self):
        """A truthy string may never impersonate the Boolean lesson coverage flag."""
        content = _content()
        content['lessons'][0]['covered'] = 'false'
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=content,
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(False),
        )
        ids = {item['id'] for item in snapshot['items']}
        self.assertIn('malformed:content_completion:lessons', ids)
        self.assertFalse(snapshot['ready'])

    def test_malformed_qa_total_fails_closed_without_exception(self):
        """Nonnumeric QA totals become diagnostics rather than raising during integer coercion."""
        content = _content()
        content['qa_open_by_reason'] = [
            {'reason_code': 'visual_transcription_required', 'total': 'seven'}
        ]
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=content,
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(False),
        )
        ids = {item['id'] for item in snapshot['items']}
        self.assertIn('malformed:content_completion:qa_open_by_reason', ids)
        self.assertFalse(snapshot['ready'])

    def test_malformed_studio_boolean_owner_and_duplicates_fail_closed(self):
        """Studio checks require Boolean ok flags, known owners, and unique IDs."""
        cases = []

        studio = _studio()
        studio['checks'][0]['ok'] = 'false'
        cases.append(studio)

        studio = _studio()
        studio['checks'][0]['owner'] = 'robot'
        cases.append(studio)

        studio = _studio()
        studio['checks'].append(dict(studio['checks'][0]))
        cases.append(studio)

        for malformed_studio in cases:
            with self.subTest(checks=malformed_studio['checks']):
                snapshot = acceptance_work_queue_snapshot(
                    content_snapshot=_content(),
                    studio_snapshot=malformed_studio,
                    e2e_snapshot=_e2e(False),
                )
                ids = {item['id'] for item in snapshot['items']}
                self.assertIn('malformed:lesson_studio_acceptance:checks', ids)
                self.assertFalse(snapshot['ready'])

    def test_inactive_curriculum_has_explicit_setup_task(self):
        """An inactive curriculum is a setup prerequisite and never counts as an uncovered lesson."""
        content = {
            'active': False,
            'content_complete': False,
            'reason': 'current_curriculum_not_configured',
        }
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=content,
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(False),
        )
        item = next(x for x in snapshot['items'] if x['id'] == 'curriculum:inactive')
        self.assertEqual(item['category'], 'curriculum_setup')
        self.assertEqual(snapshot['summary']['uncovered_lessons'], 0)
        self.assertFalse(snapshot['ready'])

    def test_malformed_active_flag_fails_closed(self):
        """A non-Boolean active flag is diagnostic corruption, not an inactive curriculum assertion."""
        content = _content()
        content['active'] = 'false'
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=content,
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(False),
        )
        ids = {item['id'] for item in snapshot['items']}
        self.assertIn('malformed:content_completion:active', ids)
        self.assertNotIn('curriculum:inactive', ids)
        self.assertFalse(snapshot['ready'])

    def test_e2e_ready_with_open_evidence_is_blocked_as_inconsistent(self):
        """Aggregate readiness may never override concrete open evidence."""
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=_content(covered=False),
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(True),
        )
        ids = {item['id'] for item in snapshot['items']}
        self.assertIn('system:e2e-queue-inconsistency', ids)
        self.assertFalse(snapshot['ready'])

    def test_clean_evidence_queue_can_be_ready(self):
        """A clean queue is ready only when Phase AA independently reports overall readiness."""
        snapshot = acceptance_work_queue_snapshot(
            content_snapshot=_content(),
            studio_snapshot=_studio(),
            e2e_snapshot=_e2e(True),
        )
        self.assertEqual(snapshot['items'], [])
        self.assertTrue(snapshot['ready'])

    def test_snapshot_and_page_are_read_only_and_admin_protected(self):
        """Phase AB exposes no write action and protects the exact HTML route with require_admin."""
        source = inspect.getsource(acceptance_work_queue_snapshot).upper()
        for token in ('UPDATE ', 'INSERT ', 'DELETE ', 'ALTER TABLE', 'CREATE TABLE', 'DROP TABLE'):
            self.assertNotIn(token, source)
        self.assertNotIn("METHOD:'POST'", PAGE.upper())
        route_source = inspect.getsource(acceptance_work_queue_page)
        self.assertIn("'/admin/acceptance-work-queue'", route_source)
        self.assertIn('dependencies=[Depends(require_admin)]', route_source)
        self.assertIn('return PAGE', route_source)


if __name__ == '__main__':
    unittest.main()
