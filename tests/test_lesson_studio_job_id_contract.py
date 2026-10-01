from __future__ import annotations

import unittest
from uuid import UUID

from app.main import app


class LessonStudioJobIdContractTests(unittest.TestCase):
    def _route(self, path: str):
        for route in app.routes:
            if getattr(route, "path", None) == path:
                return route
        self.fail(f"Route not registered: {path}")

    def test_content_review_requires_uuid_job_id(self):
        route = self._route("/api/admin/lesson-studio/jobs/{job_id}/content-review")
        param = next(p for p in route.dependant.path_params if p.name == "job_id")
        self.assertIs(param.field_info.annotation, UUID)

    def test_visual_summary_routes_require_uuid_job_id(self):
        paths = (
            "/api/admin/lesson-studio/jobs/{job_id}/visual-summary",
            "/api/admin/lesson-studio/jobs/{job_id}/visual-summary/mindmap.svg",
            "/api/admin/lesson-studio/jobs/{job_id}/visual-summary/flowchart.svg",
            "/api/admin/lesson-studio/jobs/{job_id}/visual-summary/slides.pptx",
        )
        for path in paths:
            with self.subTest(path=path):
                route = self._route(path)
                param = next(p for p in route.dependant.path_params if p.name == "job_id")
                self.assertIs(param.field_info.annotation, UUID)


if __name__ == "__main__":
    unittest.main()
