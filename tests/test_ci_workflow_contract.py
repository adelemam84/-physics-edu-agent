from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")


class CIWorkflowContractTests(unittest.TestCase):
    def test_self_hosted_quality_job_is_bounded(self):
        self.assertIn("runs-on: self-hosted", WORKFLOW)
        self.assertIn("timeout-minutes: 20", WORKFLOW)

    def test_quality_job_keeps_deterministic_test_gate(self):
        self.assertIn("python -m compileall -q app index.py", WORKFLOW)
        self.assertIn("python -m unittest discover -s tests -v", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
