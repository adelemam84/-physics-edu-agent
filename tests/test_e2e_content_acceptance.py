from __future__ import annotations

import inspect
import unittest

from app.e2e_content_acceptance import (
    PAGE,
    e2e_content_acceptance_page,
    e2e_content_acceptance_snapshot,
)


def _content(*, ready: bool = True) -> dict:
    """Build a deterministic curriculum completion fixture."""
    return {
        'active': True,
        'academic_year': '2026/2027',
        'content_complete': ready,
        'documents': [{'id': 1}],
        'source_coverage': {
            'total_lessons': 10,
            'covered_lessons': 10 if ready else 9,
            'open_qa_total': 0 if ready else 1,
            'explanatory_coverage_complete': ready,
            'question_review_complete': ready,
        },
    }


def _studio(*, ready: bool = True, platform_ready: bool = True) -> dict:
    """Build a complete Lesson Studio acceptance fixture including mandatory system checks."""
    system_ids = ('schema', 'runtime', 'release_binding_integrity')
    teacher_ids = (
        'reference_pdf',
        'curriculum_map',
        'handwritten_job',
        'ocr_review',
        'reference_review',
        'teacher_approval',
        'final_pdf',
    )
    system_ok = bool(platform_ready)
    return {
        'acceptance_ready': ready and system_ok,
        'platform_ready': system_ok,
        'checks': [
            {
                'id': check_id,
                'ok': system_ok,
                'owner': 'system',
                'label': check_id,
                'detail': 'ready' if system_ok else 'system gate open',
            }
            for check_id in system_ids
        ] + [
            {
                'id': check_id,
                'ok': ready,
                'owner': 'teacher',
                'label': check_id,
                'detail': 'ready' if ready else 'human gate open',
            }
            for check_id in teacher_ids
        ],
    }


class E2EContentAcceptanceTests(unittest.TestCase):
    """Protect the final combined acceptance contract without satisfying human gates in tests."""

    def test_both_curriculum_and_lesson_studio_are_required(self):
        """Neither subsystem may impersonate final readiness by passing alone."""
        ready = e2e_content_acceptance_snapshot(
            content_snapshot=_content(ready=True),
            studio_snapshot=_studio(ready=True),
        )
        self.assertTrue(ready['overall_ready'])

        content_blocked = e2e_content_acceptance_snapshot(
            content_snapshot=_content(ready=False),
            studio_snapshot=_studio(ready=True),
        )
        self.assertFalse(content_blocked['overall_ready'])

        studio_blocked = e2e_content_acceptance_snapshot(
            content_snapshot=_content(ready=True),
            studio_snapshot=_studio(ready=False),
        )
        self.assertFalse(studio_blocked['overall_ready'])

    def test_system_blocker_is_prioritized_before_human_work(self):
        """A platform problem must become the next action before remaining teacher-owned gates."""
        studio = _studio(ready=False, platform_ready=False)
        snapshot = e2e_content_acceptance_snapshot(
            content_snapshot=_content(ready=False),
            studio_snapshot=studio,
        )
        self.assertEqual(snapshot['next_action']['id'], 'lesson_studio_platform')
        self.assertEqual(snapshot['next_action']['owner'], 'system')
        self.assertGreater(snapshot['summary']['human_blockers'], 0)

    def test_missing_teacher_studio_check_fails_closed(self):
        """A missing teacher-owned upstream acceptance check must never be interpreted as a pass."""
        studio = _studio(ready=True)
        studio['checks'] = [item for item in studio['checks'] if item['id'] != 'final_pdf']
        snapshot = e2e_content_acceptance_snapshot(
            content_snapshot=_content(ready=True),
            studio_snapshot=studio,
        )
        final_pdf = next(item for item in snapshot['matrix'] if item['id'] == 'final_pdf')
        self.assertFalse(final_pdf['ok'])
        self.assertEqual(final_pdf['owner'], 'system')
        self.assertFalse(snapshot['overall_ready'])

    def test_missing_system_studio_check_fails_closed_even_if_platform_flag_is_true(self):
        """The aggregate platform flag cannot hide a missing schema/runtime/integrity check."""
        studio = _studio(ready=True)
        studio['platform_ready'] = True
        studio['acceptance_ready'] = True
        studio['checks'] = [item for item in studio['checks'] if item['id'] != 'runtime']
        snapshot = e2e_content_acceptance_snapshot(
            content_snapshot=_content(ready=True),
            studio_snapshot=studio,
        )
        platform = next(item for item in snapshot['matrix'] if item['id'] == 'lesson_studio_platform')
        self.assertFalse(platform['ok'])
        self.assertFalse(snapshot['platform_ready'])
        self.assertFalse(snapshot['overall_ready'])
        self.assertEqual(snapshot['next_action']['id'], 'lesson_studio_platform')

    def test_inactive_curriculum_is_never_vacuously_ready(self):
        """No active curriculum means the combined acceptance remains blocked."""
        content = {
            'active': False,
            'content_complete': False,
            'reason': 'current_curriculum_not_configured',
        }
        snapshot = e2e_content_acceptance_snapshot(
            content_snapshot=content,
            studio_snapshot=_studio(ready=True),
        )
        self.assertFalse(snapshot['overall_ready'])
        self.assertEqual(snapshot['matrix'][0]['id'], 'curriculum_active')
        self.assertFalse(snapshot['matrix'][0]['ok'])

    def test_snapshot_is_read_only_and_ui_has_no_mutation_actions(self):
        """Phase AA remains diagnostic and exposes no approval or write request from its dashboard."""
        source = inspect.getsource(e2e_content_acceptance_snapshot).upper()
        for token in ('UPDATE ', 'INSERT ', 'DELETE ', 'ALTER TABLE', 'CREATE TABLE', 'DROP TABLE'):
            self.assertNotIn(token, source)
        self.assertNotIn("METHOD:'POST'", PAGE.upper())
        self.assertIn('لا تعتمد مصدرًا أو سؤالًا أو مدرسًا', PAGE)

    def test_html_route_uses_admin_dependency(self):
        """The exact administrative HTML route must enforce require_admin before returning its shell."""
        route_source = inspect.getsource(e2e_content_acceptance_page)
        self.assertIn("'/admin/e2e-content-acceptance'", route_source)
        self.assertIn('response_class=HTMLResponse', route_source)
        self.assertIn('dependencies=[Depends(require_admin)]', route_source)
        self.assertIn('return PAGE', route_source)


if __name__ == '__main__':
    unittest.main()
