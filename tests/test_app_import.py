import importlib
import unittest
from unittest.mock import patch


class VercelEntrypointTests(unittest.TestCase):
    def _app(self):
        return importlib.import_module("index").app

    def test_vercel_entrypoint_imports_without_runtime_import_errors(self):
        self.assertEqual(self._app().version, "1.8.9")

    def test_status_plane_uses_the_same_canonical_version(self):
        import status
        from app.version import APPLICATION_VERSION
        self.assertEqual(self._app().version, APPLICATION_VERSION)
        self.assertEqual(status.VERSION, APPLICATION_VERSION)
        self.assertEqual(status.app.version, APPLICATION_VERSION)

    def test_release_status_uses_canonical_application_version(self):
        from app import release_hardening
        self.assertEqual(release_hardening.NEXT_RELEASE, self._app().version)
        self.assertNotIn("app.version =", __import__("inspect").getsource(release_hardening))

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
            "/api/admin/lesson-studio/jobs/{job_id}/handwriting-pipeline",
            "/api/admin/external-creative-integrations",
            "/api/admin/integrations/canva/oauth/start",
            "/api/integrations/canva/oauth/callback",
            "/api/admin/integrations/canva/oauth/status",
            "/api/admin/integrations/canva/master-contract",
            "/api/admin/integrations/canva/diagnostics",
            "/api/admin/lesson-studio/integrations/summary",
            "/api/admin/lesson-studio/jobs/{job_id}/external-artifacts",
            "/api/admin/lesson-studio/jobs/{job_id}/external-artifacts/{provider}",
            "/api/admin/lesson-pack-studio/status",
            "/api/admin/lesson-pack-studio/jobs",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/process-next",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/generate",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/scientific-review",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/approve",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/suggest",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/{visual_id}/preview",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/{visual_id}/review",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-pdf",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/cover",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-manifest",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-page/{page_number}",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/export-pdf",
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
            "/admin/lesson-studio/integrations",
            "/admin/lesson-pack-studio",
            "/admin/lesson-pack-studio/jobs/{job_id}/preview",
            "/admin/completion-audit",
            "/admin/project-closure",
        }
        self.assertTrue(required.issubset(paths), required-paths)

    def test_canva_master_contract_is_complete_and_source_grounded(self):
        from app.services.canva_master_contract import CANVA_MASTER_TEXT_FIELDS, canva_master_values
        summary={
            "title":"قانون أوم",
            "subject":"فيزياء",
            "grade_label":"الثالث الثانوي",
            "summary":"العلاقة بين الجهد والتيار والمقاومة.",
            "sections":[
                {"title":"الجهد","summary":"فرق الجهد الكهربائي."},
                {"title":"التيار","summary":"معدل سريان الشحنة."},
            ],
            "equations":[{"label":"قانون أوم","expression":"V = I × R","notes":"الوحدات القياسية"}],
            "diagrams":[{"title":"دائرة كهربائية","description":"مقاومة ومصدر جهد","labels":["V","I","R"]}],
        }
        values=canva_master_values(summary)
        self.assertEqual(set(values), set(CANVA_MASTER_TEXT_FIELDS))
        self.assertEqual(values["LESSON_TITLE"], "قانون أوم")
        self.assertIn("V = I × R", values["EQUATIONS_BODY"])
        self.assertEqual(values["EXAMPLE_PROBLEM"], "")
        self.assertEqual(values["COMMON_MISTAKE"], "")

    def test_canva_oauth_requests_design_autofill_scopes(self):
        from app.canva_oauth import CANVA_SCOPES, _requested_scopes
        scopes=set(CANVA_SCOPES.split())
        self.assertEqual(_requested_scopes(), scopes)
        self.assertIn("design:content:read", scopes)
        self.assertIn("design:content:write", scopes)
        self.assertEqual(len(scopes), len(CANVA_SCOPES.split()))

    def test_canva_diagnostics_uses_master_design_without_brand_template(self):
        from app import canva_diagnostics
        from app.services.canva_master_contract import CANVA_MASTER_DESIGN_ID
        source_type, source_id, dataset_url=canva_diagnostics._source_contract()
        self.assertIn(source_type, {"design", "brand_template"})
        if source_type == "design":
            self.assertEqual(source_id, CANVA_MASTER_DESIGN_ID)
            self.assertIn(f"/designs/{CANVA_MASTER_DESIGN_ID}/dataset", dataset_url)

    def test_external_artifact_identity_is_provider_specific_and_secret_free(self):
        from app.lesson_studio_external_artifacts import _external_identity
        external_id, external_url, metadata = _external_identity("canva", {
            "source_grounded": True,
            "status": "success",
            "job_id": "autofill-job-1",
            "design": {"id": "D123", "urls": {"edit_url": "https://www.canva.com/design/D123"}},
            "fields_used": ["LESSON_TITLE"],
            "source_id": "DAHUkN3i5p4",
            "autofill_type": "create_from_design",
        })
        self.assertEqual(external_id, "D123")
        self.assertTrue(external_url.startswith("https://"))
        self.assertEqual(metadata["fields_used"], ["LESSON_TITLE"])
        self.assertNotIn("access_token", metadata)
        self.assertNotIn("refresh_token", metadata)

    def test_canva_redirect_is_canonical_production_url(self):
        from app.canva_oauth import CANVA_PRODUCTION_REDIRECT
        self.assertEqual(
            CANVA_PRODUCTION_REDIRECT,
            "https://physics-edu-agent.vercel.app/api/integrations/canva/oauth/callback",
        )

    def test_release_state_distinguishes_runtime_from_content_gates(self):
        from app.release_hardening import _classify_release_state
        self.assertEqual(_classify_release_state([], []), 'runtime_ready')
        self.assertEqual(_classify_release_state([], ['essay gap']), 'runtime_ready_content_gate_open')
        self.assertEqual(_classify_release_state(['missing key'], ['essay gap']), 'code_ready_pending_runtime_activation')

    def test_content_gap_does_not_masquerade_as_runtime_blocker(self):
        from app import release_hardening, source_review
        with patch.object(release_hardening, "research_engine_status", return_value={
            "configured": True,
            "orchestrator": {"status": "active"},
            "guardrails": {"question_bank_auto_write": False},
        }), patch.object(release_hardening, "configured_store_name", return_value="fileSearchStores/test"), \
             patch.object(release_hardening, "active_content_integrity_snapshot", return_value={
                 "active": True,
                 "ready": True,
                 "invalid_approved_questions": 0,
                 "question_lesson_mismatches": 0,
                 "quiz_question_mismatches": 0,
                 "critical_open_qa": 0,
             }), \
             patch.object(release_hardening, "_sync_summary", return_value={"total": 0, "active": 0, "processing": 0, "failed": 0}), \
             patch.object(source_review, "_source_page_coverage_snapshot", return_value={
                 "summary": {
                     "physical_pages": 42,
                     "question_pages": 28,
                     "zero_question_pages": 14,
                     "reviewed_nonquestion_pages": 14,
                     "open_zero_question_pages": 0,
                     "count_mismatch_pages": 0,
                     "coverage_ready": True,
                 },
                 "items": [],
             }), \
             patch.object(release_hardening, "blueprint_readiness", return_value={
                 "active_shape_feasible": False,
                 "blueprint": {"objective_questions": 23, "essay_questions": 23},
                 "gaps": {"objective": 0, "essay": 5},
             }):
            data = release_hardening.next_release_status()
        self.assertEqual(data["release_state"], "runtime_ready_content_gate_open")
        self.assertEqual(data["runtime_blockers"], [])
        self.assertTrue(data["content_gates"])
        self.assertTrue(data["source_page_coverage"]["coverage_ready"])
        self.assertNotIn("source page coverage gap", " ".join(data["content_gates"]))
        self.assertNotIn("active curriculum integrity gap", " ".join(data["content_gates"]))



if __name__ == "__main__":
    unittest.main()
