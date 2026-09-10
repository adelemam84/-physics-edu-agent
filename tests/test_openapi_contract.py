from __future__ import annotations

import unittest

from index import app


class OpenApiContractTests(unittest.TestCase):
    """Keep FastAPI OpenAPI generation healthy for the production API surface."""

    def test_openapi_schema_builds_and_contains_critical_routes(self):
        """OpenAPI generation must succeed and include final student/admin workflows."""
        schema = app.openapi()
        paths = schema.get("paths") or {}
        expected = {
            "/health",
            "/api/student/review/mistakes-pdf",
            "/api/student/attempts/{attempt_id}/review-pdf",
            "/api/admin/lesson-studio/jobs/{job_id}/handwriting-pipeline",
            "/api/admin/content-completion",
            "/api/admin/project-closure",
            "/api/admin/ai-operations/summary",
        }
        self.assertTrue(expected.issubset(paths), expected - set(paths))


if __name__ == "__main__":
    unittest.main()
