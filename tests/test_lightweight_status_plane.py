from __future__ import annotations

import json
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import status


class _RowConnection:
    def execute(self, query, params=None):
        return self

    def fetchone(self):
        return {"ok": 1}


class LightweightStatusPlaneTests(unittest.TestCase):
    def setUp(self):
        status._readiness_cache = None

    def test_vercel_routes_public_status_endpoints_before_main_app(self):
        config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        builds = {item["src"] for item in config["builds"]}
        self.assertIn("status.py", builds)
        self.assertIn("index.py", builds)

        routes = config["routes"]
        self.assertEqual(routes[0], {"src": "/health", "dest": "status.py"})
        self.assertEqual(routes[1], {"src": "/health/ready", "dest": "status.py"})
        self.assertEqual(
            routes[2],
            {"src": "/api/research-engine/status", "dest": "status.py"},
        )
        self.assertEqual(routes[-1]["dest"], "index.py")

    def test_status_plane_does_not_import_heavy_application_modules(self):
        source = Path("status.py").read_text(encoding="utf-8")
        forbidden = (
            "from app.main",
            "import app.main",
            "import fitz",
            "import httpx",
            "app.research_engine",
            "app.release_candidate",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, source)

    def test_readiness_cache_reuses_database_probe_for_burst(self):
        calls = {"count": 0}

        @contextmanager
        def fake_connect():
            calls["count"] += 1
            yield _RowConnection()

        identity = {
            "provider": "vercel",
            "production_environment": True,
            "current_runtime_is_production_main": True,
        }
        env = {
            "DATABASE_URL": "postgresql://configured",
            "ADMIN_API_KEY": "configured",
            "STUDENT_SESSION_SECRET": "configured",
            "AWS_ACCESS_KEY_ID": "configured",
            "AWS_SECRET_ACCESS_KEY": "configured",
            "AWS_ENDPOINT_URL_S3": "https://storage.example",
            "AWS_REGION": "us-east-1",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            status, "connect", fake_connect
        ), patch.object(status, "runtime_identity", return_value=identity):
            first = status._readiness_snapshot()
            second = status._readiness_snapshot()

        self.assertTrue(first["ready"])
        self.assertTrue(second["ready"])
        self.assertEqual(calls["count"], 1)


if __name__ == "__main__":
    unittest.main()
