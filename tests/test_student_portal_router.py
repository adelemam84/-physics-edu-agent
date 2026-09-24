from pathlib import Path
import unittest
from fastapi import APIRouter
from app.student_portal import router

class StudentPortalRouterTests(unittest.TestCase):
    def test_router_is_decoupled_from_main_app(self):
        self.assertIsInstance(router, APIRouter)
        source=Path("app/student_portal.py").read_text(encoding="utf-8")
        self.assertNotIn("from .main import app",source)
        self.assertNotIn("@app.",source)

    def test_portal_routes_remain_registered(self):
        paths={route.path for route in router.routes}
        self.assertIn("/api/student/portal",paths)
        self.assertIn("/student",paths)

if __name__=="__main__": unittest.main()
