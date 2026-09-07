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
        }
        self.assertTrue(required.issubset(paths), required-paths)


if __name__ == "__main__":
    unittest.main()
