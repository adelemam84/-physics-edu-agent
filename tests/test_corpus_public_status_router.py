from pathlib import Path
import unittest

from fastapi import APIRouter

from app.corpus_public_status import router


class CorpusPublicStatusRouterTests(unittest.TestCase):
    def test_module_exposes_router_without_importing_main_app(self):
        self.assertIsInstance(router, APIRouter)
        source = Path("app/corpus_public_status.py").read_text(encoding="utf-8")
        self.assertNotIn("from .main import app", source)
        self.assertNotIn("@app.", source)

    def test_expected_public_status_route_is_preserved(self):
        paths = {route.path for route in router.routes}
        self.assertIn("/api/current-curriculum/phase2-status", paths)


if __name__ == "__main__":
    unittest.main()
