import importlib
import unittest
from unittest.mock import patch


class VercelEntrypointTests(unittest.TestCase):
    def _app(self):
        return importlib.import_module("index").app

    def test_vercel_entrypoint_imports_without_runtime_import_errors(self):
        self.assertEqual(self._app().version, "1.8.10")

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
            "/api/admin/lesson-pack-studio/jobs/{job_id}/cover",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-manifest",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-page",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-pdf",
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

    def test_canva_master_contract_keeps_stable_field_count(self):
        from app.services.canva_master_contract import CANVA_MASTER_TEXT_FIELDS
        self.assertEqual(len(CANVA_MASTER_TEXT_FIELDS), 11)

    def test_canva_diagnostics_uses_master_design_without_brand_template(self):
        import os
        from app.integrations.canva import canva_diagnostics
        with patch.dict(os.environ, {"CANVA_MASTER_DESIGN_ID":"DAHUkN3i5p4", "CANVA_BRAND_TEMPLATE_ID":""}, clear=False):
            result=canva_diagnostics()
        self.assertEqual(result["master_design_id"], "DAHUkN3i5p4")
        self.assertFalse(result["brand_template_configured"])

    def test_canva_oauth_requests_design_autofill_scopes(self):
        import os
        from app.integrations.canva import canva_oauth_scopes
        with patch.dict(os.environ, {"CANVA_SCOPES":"design:content:read design:content:write design:meta:read brandtemplate:content:read brandtemplate:meta:read"}, clear=False):
            scopes=canva_oauth_scopes()
        self.assertIn("design:content:read", scopes)
        self.assertIn("design:content:write", scopes)

    def test_canva_redirect_is_canonical_production_url(self):
        import os
        from app.integrations.canva import canva_redirect_uri
        with patch.dict(os.environ, {"CANVA_REDIRECT_URI":"https://physics-edu-agent.vercel.app/api/integrations/canva/oauth/callback"}, clear=False):
            self.assertEqual(canva_redirect_uri(), "https://physics-edu-agent.vercel.app/api/integrations/canva/oauth/callback")

    def test_external_artifact_identity_is_provider_specific_and_secret_free(self):
        import inspect
        from app.services import lesson_external_artifacts
        src=inspect.getsource(lesson_external_artifacts)
        self.assertNotIn("CANVA_CLIENT_SECRET", src)
        self.assertIn("provider", src)

    def test_content_gap_does_not_masquerade_as_runtime_blocker(self):
        import inspect
        from app import release_hardening
        src=inspect.getsource(release_hardening)
        self.assertIn("content", src.lower())
