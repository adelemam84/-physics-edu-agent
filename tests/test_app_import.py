import importlib
import unittest
from unittest.mock import patch


class VercelEntrypointTests(unittest.TestCase):
    def _app(self):
        return importlib.import_module("index").app

    def test_vercel_entrypoint_imports_without_runtime_import_errors(self):
        self.assertEqual(self._app().version, "1.8.14")

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
        }
        self.assertTrue(required.issubset(paths))

    def test_canva_oauth_requests_design_autofill_scopes(self):
        from app import canva_integration
        scopes = set(canva_integration.CANVA_SCOPES.split())
        self.assertIn("design:content:read", scopes)
        self.assertIn("design:content:write", scopes)
        self.assertIn("design:meta:read", scopes)
        self.assertIn("design:permission:read", scopes)
        self.assertIn("asset:read", scopes)
        self.assertIn("asset:write", scopes)

    def test_canva_redirect_is_canonical_production_url(self):
        from app import canva_integration
        self.assertEqual(
            canva_integration.CANVA_REDIRECT_URI,
            "https://physics-edu-agent.vercel.app/api/integrations/canva/callback",
        )

    def test_canva_master_contract_is_complete_and_source_grounded(self):
        from app import canva_integration
        contract=canva_integration.canva_master_contract()
        self.assertEqual(contract["source_grounding"], "approved_lesson_only")
        self.assertEqual(contract["teacher_review"], "required")
        self.assertFalse(contract["auto_publish"])
        self.assertEqual(contract["delivery"]["mode"], "manual_export")
        self.assertEqual(contract["template_strategy"], "master_design_autofill")

    def test_canva_diagnostics_uses_master_design_without_brand_template(self):
        from app import canva_integration
        with patch.dict("os.environ", {"CANVA_MASTER_DESIGN_ID": "design-1"}, clear=False):
            snapshot=canva_integration.canva_diagnostics()
        self.assertEqual(snapshot["template_strategy"], "master_design_autofill")
        self.assertEqual(snapshot["master_design_configured"], True)
        self.assertNotIn("brand_template_id", snapshot)

    def test_external_artifact_identity_is_provider_specific_and_secret_free(self):
        from app import external_artifacts
        source = __import__("inspect").getsource(external_artifacts)
        self.assertNotIn("access_token", source)
        self.assertNotIn("refresh_token", source)
        self.assertIn("provider", source)
        self.assertIn("external_id", source)

    def test_content_gap_does_not_masquerade_as_runtime_blocker(self):
        from app import release_hardening
        snapshot={
            "runtime_ready": True,
            "content_ready": False,
            "blockers": ["content_gate"],
        }
        result=release_hardening.release_state_from_snapshot(snapshot)
        self.assertTrue(result["runtime_ready"])
        self.assertFalse(result["content_ready"])
        self.assertFalse(result["runtime_blocked"])

    def test_release_state_distinguishes_runtime_from_content_gates(self):
        from app import release_hardening
        snapshot={
            "runtime_ready": False,
            "content_ready": False,
            "blockers": ["database_runtime", "content_gate"],
        }
        result=release_hardening.release_state_from_snapshot(snapshot)
        self.assertTrue(result["runtime_blocked"])
        self.assertFalse(result["content_ready"])

    def test_lesson_studio_admin_surfaces_are_registered(self):
        paths={route.path for route in self._app().routes}
        required={
            "/admin/lesson-studio",
            "/admin/lesson-studio/acceptance",
            "/admin/lesson-studio/reference-review",
            "/admin/lesson-studio/source-editor",
            "/admin/lesson-studio/diagram-builder",
            "/admin/lesson-studio/version-history",
        }
        self.assertTrue(required.issubset(paths))


if __name__ == "__main__":
    unittest.main()
