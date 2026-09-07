import importlib
import unittest


class VercelEntrypointTests(unittest.TestCase):
    def _app(self):
        return importlib.import_module("index").app

    def test_vercel_entrypoint_imports_without_runtime_import_errors(self):
        self.assertEqual(self._app().version, "1.8.0")

    def test_release_health_and_research_routes_are_registered(self):
        paths={route.path for route in self._app().routes}
        required={
            "/health",
            "/api/next-release/status",
            "/api/research-engine/status",
            "/api/current-curriculum/phase2-status",
            "/api/admin/lesson-studio/acceptance",
            "/api/admin/lesson-studio/pdf-presets",
            "/api/admin/lesson-studio/jobs/{job_id}/final-pdf/{preset}",
            "/api/admin/lesson-studio/jobs/{job_id}/diagrams/{diagram_index}/parameters",
            "/api/admin/lesson-studio/jobs/{job_id}/versions",
            "/api/admin/lesson-studio/jobs/{job_id}/versions/{version_no}",
            "/api/admin/lesson-studio/jobs/{job_id}/versions/{version_no}/restore",
            "/api/admin/lesson-studio/jobs/{job_id}/versions/{from_version}/diff",
            "/api/admin/lesson-studio/jobs/{job_id}/versions/{from_version}/impact",
            "/api/admin/lesson-studio/jobs/{job_id}/approval-state",
            "/api/admin/lesson-studio/release-readiness",
            "/api/admin/completion-audit",
            "/api/admin/current-corpus/visual-review/queue",
            "/api/admin/current-corpus/visual-review/{question_id}/suggest",
            "/api/admin/current-corpus/visual-review/{question_id}",
            "/api/admin/current-corpus/visual-review/batch-suggest",
            "/api/admin/project-closure",
        }
        self.assertTrue(required.issubset(paths), required - paths)

    def test_lesson_studio_admin_surfaces_are_registered(self):
        paths={route.path for route in self._app().routes}
        required={
            "/admin/lesson-studio",
            "/admin/lesson-studio/review",
            "/admin/lesson-studio/source-editor",
            "/admin/lesson-studio/workspace",
            "/admin/lesson-studio/tools",
            "/admin/lesson-studio/references",
            "/admin/lesson-studio/reference-workspace",
            "/admin/lesson-studio/acceptance",
            "/admin/lesson-studio/release-readiness",
            "/admin/completion-audit",
            "/admin/project-closure",
        }
        self.assertTrue(required.issubset(paths), required-paths)

    def test_release_state_distinguishes_runtime_from_content_gates(self):
        from app.release_hardening import _classify_release_state
        self.assertEqual(_classify_release_state([], []), 'runtime_ready')
        self.assertEqual(_classify_release_state([], ['essay gap']), 'runtime_ready_content_gate_open')
        self.assertEqual(_classify_release_state(['missing key'], ['essay gap']), 'code_ready_pending_runtime_activation')


if __name__ == "__main__":
    unittest.main()
