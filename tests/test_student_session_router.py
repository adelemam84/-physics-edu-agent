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
        methods = set().union(*(set(route.methods or set()) for route in router.routes if route.path == "/api/student/session"))
        self.assertIn("POST", methods)
        self.assertIn("GET", methods)
        self.assertIn("DELETE", methods)


if __name__ == "__main__":
    unittest.main()
