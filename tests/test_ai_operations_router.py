from pathlib import Path
import unittest

from fastapi import APIRouter

from app.ai_operations import router


class AIOperationsRouterTests(unittest.TestCase):
    def test_router_is_decoupled_from_main_app(self):
        self.assertIsInstance(router, APIRouter)
        source = Path("app/ai_operations.py").read_text(encoding="utf-8")
        self.assertNotIn("from .main import app", source)
        self.assertNotIn("@app.", source)

    def test_route_contracts_are_preserved(self):
        paths = {route.path for route in router.routes}
        self.assertTrue({
            "/api/admin/ai-operations/summary",
            "/api/admin/ai-operations/usage",
            "/admin/ai-operations",
        }.issubset(paths))


if __name__ == "__main__":
    unittest.main()
