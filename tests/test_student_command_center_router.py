from pathlib import Path
import unittest
from fastapi import APIRouter
from app.student_command_center import router

class StudentCommandCenterRouterTests(unittest.TestCase):
    def test_router_is_decoupled_from_main_app(self):
        self.assertIsInstance(router, APIRouter)
        source=Path("app/student_command_center.py").read_text(encoding="utf-8")
        self.assertNotIn("from .main import app",source)
        self.assertNotIn("@app.",source)

    def test_command_center_contracts_are_preserved(self):
        paths={route.path for route in router.routes}
        self.assertIn("/api/student/command-center",paths)
        self.assertIn("/student/command-center",paths)

if __name__=="__main__": unittest.main()
