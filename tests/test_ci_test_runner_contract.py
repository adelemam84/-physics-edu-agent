from __future__ import annotations

from pathlib import Path
import unittest


CI = Path(".github/workflows/ci.yml")
DEV = Path("requirements-dev.txt")


class CiTestRunnerContractTests(unittest.TestCase):
    def test_ci_runs_unittest_and_pytest_suites(self):
        text = CI.read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests -v", text)
        self.assertIn("python -m pip install --disable-pip-version-check -r requirements-dev.txt", text)
        self.assertIn("python -m pytest -q tests", text)

    def test_pytest_is_pinned_as_development_only_dependency(self):
        runtime = Path("requirements.txt").read_text(encoding="utf-8")
        dev = DEV.read_text(encoding="utf-8")
        self.assertNotIn("pytest", runtime.lower())
        self.assertEqual(dev.strip(), "pytest==9.1.1")


if __name__ == "__main__":
    unittest.main()
