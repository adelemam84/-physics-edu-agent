from pathlib import Path
import unittest

from fastapi import APIRouter

from app.progress_dashboard import router as progress_router
from app.runtime_health import router as runtime_health_router


class AdminRouterPhase2Tests(unittest.TestCase):
    def test_routers_are_decoupled_from_main_app(self):
        for path, router in [
            ("app/progress_dashboard.py", progress_router),
            ("app/runtime_health.py", runtime_health_router),
        ]:
            self.assertIsInstance(router, APIRouter)
            source = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("from .main import app", source)
            self.assertNotIn("@app.", source)

    def test_progress_routes_are_preserved(self):
        paths = {route.path for route in progress_router.routes}
        self.assertTrue({"/api/admin/progress", "/admin/progress"}.issubset(paths))

    def test_runtime_health_route_is_preserved(self):
        paths = {route.path for route in runtime_health_router.routes}
        self.assertIn("/api/admin/runtime-health", paths)


if __name__ == "__main__":
    unittest.main()
