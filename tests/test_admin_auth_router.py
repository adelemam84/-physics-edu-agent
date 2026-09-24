from pathlib import Path
import unittest
from fastapi import APIRouter
from app.admin_auth import router

class AdminAuthRouterTests(unittest.TestCase):
    def test_router_is_decoupled_from_main_app(self):
        self.assertIsInstance(router, APIRouter)
        source=Path("app/admin_auth.py").read_text(encoding="utf-8")
        self.assertNotIn("from .main import app",source)
        self.assertNotIn("@app.",source)

    def test_auth_contracts_are_preserved(self):
        paths={route.path for route in router.routes}
        self.assertTrue({"/api/admin/session","/api/admin/login","/api/admin/logout","/admin/login"}.issubset(paths))

if __name__=="__main__": unittest.main()
