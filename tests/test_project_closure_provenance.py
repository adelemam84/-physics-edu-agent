from __future__ import annotations

import unittest
from unittest.mock import patch

import app.project_closure as closure
from app.completion_audit import PAGE as COMPLETION_AUDIT_PAGE


class ProjectClosureProvenanceTests(unittest.TestCase):
    """Keep final closure truthful across code, deployment and human content gates."""

    @staticmethod
    def _base_inputs() -> dict:
        """Return a fully healthy closure dependency set for focused policy tests."""
        return {
            'completion': {
                'code_complete': True,
                'programmatic_remaining': [],
                'external_or_human_remaining': [],
            },
            'release': {
                'release_state': 'runtime_ready',
                'exam_blueprint': {'ready': True},
            },
            'research': {
                'configured': True,
                'orchestrator': {'status': 'active'},
                'guardrails': {
                    'source_only': True,
                    'question_bank_auto_write': False,
                },
            },
            'corpus': {
                'academic_year': '2026/2027',
                'questions': {'total_questions': 100, 'approved_questions': 70},
                'quizzes': {'published': 2},
            },
            'lesson': {
                'decision': 'ready',
                'reason': 'all_release_requirements_complete',
                'acceptance_ready': True,
                'platform': {
                    'checks': [],
                    'blockers': [],
                    'system_blockers': 0,
                    'teacher_blockers': 0,
                },
            },
            'deployment': {
                'provider': 'vercel',
                'environment': 'production',
                'target_environment': 'production',
                'git_ref': 'main',
                'git_commit_sha': 'a' * 40,
                'git_commit_short': 'a' * 12,
                'deployment_id': 'dpl_test',
                'production_url': 'physics-edu-agent.vercel.app',
                'provenance_available': True,
                'production_environment': True,
                'deployed_from_main': True,
                'current_runtime_is_production_main': True,
                'latest_main_match': None,
                'latest_main_verification': 'external_required',
            },
        }

    def _snapshot(self, inputs: dict) -> dict:
        """Execute closure with deterministic dependency snapshots and no live service calls."""
        with (
            patch.object(closure, 'completion_audit_snapshot', return_value=inputs['completion']),
            patch.object(closure, 'next_release_status', return_value=inputs['release']),
            patch.object(closure, 'research_engine_status', return_value=inputs['research']),
            patch.object(closure, 'current_curriculum_phase2_status', return_value=inputs['corpus']),
            patch.object(closure, 'release_readiness_snapshot', return_value=inputs['lesson']),
            patch.object(closure, '_deployment_provenance', return_value=inputs['deployment']),
        ):
            return closure.project_closure_snapshot()

    def test_vercel_provenance_reports_current_commit_without_claiming_latest_main(self):
        """Runtime self-reporting may identify its commit but must leave latest-main comparison external."""
        result = closure._deployment_provenance({
            'VERCEL': '1',
            'VERCEL_ENV': 'production',
            'VERCEL_TARGET_ENV': 'production',
            'VERCEL_GIT_COMMIT_REF': 'main',
            'VERCEL_GIT_COMMIT_SHA': '1234567890abcdef1234567890abcdef12345678',
            'VERCEL_DEPLOYMENT_ID': 'dpl_example',
            'VERCEL_PROJECT_PRODUCTION_URL': 'physics-edu-agent.vercel.app',
        })
        self.assertTrue(result['current_runtime_is_production_main'])
        self.assertEqual(result['git_commit_short'], '1234567890ab')
        self.assertIsNone(result['latest_main_match'])
        self.assertEqual(result['latest_main_verification'], 'external_required')

    def test_preview_never_impersonates_production_main(self):
        """A preview built from main-like metadata must not satisfy production deployment verification."""
        result = closure._deployment_provenance({
            'VERCEL': '1',
            'VERCEL_ENV': 'preview',
            'VERCEL_GIT_COMMIT_REF': 'main',
            'VERCEL_GIT_COMMIT_SHA': 'b' * 40,
        })
        self.assertFalse(result['production_environment'])
        self.assertFalse(result['current_runtime_is_production_main'])

    def test_fully_healthy_inputs_close_code_deployment_and_content(self):
        """Full closure requires Phase X acceptance plus a production runtime self-report from main."""
        result = self._snapshot(self._base_inputs())
        self.assertTrue(result['code_complete'])
        self.assertTrue(result['content_complete'])
        self.assertTrue(result['production_runtime_verified'])
        self.assertEqual(result['closure_state'], 'production_and_content_complete')
        signoff = {item['id']: item['status'] for item in result['signoff']}
        self.assertEqual(signoff['phase_x_acceptance'], 'complete')
        self.assertEqual(signoff['production_release'], 'complete')

    def test_phase_x_system_blocker_prevents_code_complete(self):
        """A Phase X system blocker must remain a software/runtime blocker in the final closure manifest."""
        inputs = self._base_inputs()
        inputs['lesson'] = {
            **inputs['lesson'],
            'acceptance_ready': False,
            'platform': {
                'checks': [],
                'blockers': [{'id': 'schema', 'owner': 'system'}],
                'system_blockers': 1,
                'teacher_blockers': 0,
            },
        }
        result = self._snapshot(inputs)
        self.assertFalse(result['code_complete'])
        self.assertEqual(result['closure_state'], 'programmatic_attention_required')
        self.assertFalse(result['lesson_studio']['platform_ready'])

    def test_teacher_acceptance_gate_does_not_become_code_defect(self):
        """Teacher-owned Phase X blockers keep content open while code can remain complete."""
        inputs = self._base_inputs()
        inputs['lesson'] = {
            **inputs['lesson'],
            'decision': 'action_required',
            'acceptance_ready': False,
            'platform': {
                'checks': [],
                'blockers': [{'id': 'teacher_approval', 'owner': 'teacher'}],
                'system_blockers': 0,
                'teacher_blockers': 1,
            },
        }
        result = self._snapshot(inputs)
        self.assertTrue(result['code_complete'])
        self.assertFalse(result['content_complete'])
        self.assertEqual(result['closure_state'], 'production_code_complete_external_gates_open')
        self.assertEqual(
            {item['id']: item['status'] for item in result['signoff']}['phase_x_acceptance'],
            'human_gate',
        )

    def test_unverified_deployment_is_separate_from_code_completeness(self):
        """Missing production provenance must request deployment verification without rewriting code status."""
        inputs = self._base_inputs()
        inputs['deployment'] = {
            **inputs['deployment'],
            'environment': 'preview',
            'production_environment': False,
            'current_runtime_is_production_main': False,
        }
        result = self._snapshot(inputs)
        self.assertTrue(result['code_complete'])
        self.assertTrue(result['content_complete'])
        self.assertFalse(result['production_runtime_verified'])
        self.assertEqual(result['closure_state'], 'production_deployment_verification_required')
        self.assertEqual(
            {item['id']: item['status'] for item in result['signoff']}['production_release'],
            'deployment_attention',
        )

    def test_external_source_gate_remains_open_without_affecting_code(self):
        """Missing approved explanatory material remains an external content gate and is never auto-closed."""
        inputs = self._base_inputs()
        inputs['completion'] = {
            **inputs['completion'],
            'external_or_human_remaining': [{
                'id': 'approved_explanatory_source',
                'type': 'external_source',
                'title': 'approved source required',
                'count': 0,
                'path': '/admin/document-recovery',
            }],
        }
        result = self._snapshot(inputs)
        self.assertTrue(result['code_complete'])
        self.assertFalse(result['content_complete'])
        self.assertEqual(result['closure_state'], 'production_code_complete_external_gates_open')
        self.assertTrue(result['final_policy']['no_external_gate_is_auto_closed'])

    def test_completion_audit_ui_handles_rejected_fetch(self):
        """The completion audit page must render an operator-visible error when fetch rejects."""
        self.assertIn("try{r=await fetch('/api/admin/completion-audit')}", COMPLETION_AUDIT_PAGE)
        self.assertIn(
            "catch(err){out.innerHTML='<div class=bad>تعذر تشغيل تدقيق الاكتمال</div>';return}",
            COMPLETION_AUDIT_PAGE,
        )


if __name__ == '__main__':
    unittest.main()
