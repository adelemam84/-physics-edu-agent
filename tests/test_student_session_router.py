from pathlib import Path
import unittest

from fastapi import APIRouter

from app.student_session_api import router


class StudentSessionRouterTests(unittest.TestCase):
    def test_module_exposes_router_without_main_app_import(self):
        self.assertIsInstance(router, APIRouter)
        source = Path("app/student_session_api.py").read_text(encoding="utf-8")
        self.assertNotIn("from .main import app", source)
        self.assertNotIn("@app.", source)

    def test_session_contract_paths_and_methods_are_preserved(self):
        by_path = {route.path: set(route.methods or set()) for route in router.routes}
        self.assertIn("POST", by_path["/api/student/session"])
        self.assertIn("GET", by_path["/api/student/session"])
        self.assertIn("DELETE", by_path["/api/student/session"])


if __name__ == "__main__":
    unittest.main()
