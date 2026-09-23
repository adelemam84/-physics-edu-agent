from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = (ROOT / "tools" / "performance_probe.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "performance-readiness.yml").read_text(
    encoding="utf-8"
)


class PerformanceProbeContractTests(unittest.TestCase):
    def test_probe_is_bounded_and_read_only(self):
        self.assertIn('method="GET"', PROBE)
        self.assertIn('min(int(os.getenv("PERF_REQUESTS", "100")), 200)', PROBE)
        self.assertIn('min(int(os.getenv("PERF_CONCURRENCY", "10")), 16)', PROBE)
        self.assertNotIn('method="POST"', PROBE)
        self.assertNotIn('method="PUT"', PROBE)
        self.assertNotIn('method="DELETE"', PROBE)

    def test_probe_only_targets_public_safe_endpoints(self):
        for path in (
            "/health",
            "/health/ready",
            "/api/research-engine/status",
            "/api/next-release/status",
        ):
            self.assertIn(f'"{path}"', PROBE)
        self.assertNotIn("/api/admin/", PROBE)
        self.assertNotIn("/api/student/session", PROBE)

    def test_workflow_has_conservative_defaults_and_artifact(self):
        self.assertIn('PERF_REQUESTS: "100"', WORKFLOW)
        self.assertIn('PERF_CONCURRENCY: "10"', WORKFLOW)
        self.assertIn('PERF_MAX_ERROR_RATE: "0.01"', WORKFLOW)
        self.assertIn('PERF_P95_LIMIT_MS: "2500"', WORKFLOW)
        self.assertIn("production-performance-readiness", WORKFLOW)
        self.assertIn("cancel-in-progress: false", WORKFLOW)



    def test_workflow_runs_after_successful_controlled_production_release(self):
        self.assertIn("workflow_run:", WORKFLOW)
        self.assertIn('workflows: ["Controlled Production Release"]', WORKFLOW)
        self.assertIn("types: [completed]", WORKFLOW)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", WORKFLOW)
        self.assertIn("github.event.workflow_run.head_sha", WORKFLOW)

if __name__ == "__main__":
    unittest.main()
