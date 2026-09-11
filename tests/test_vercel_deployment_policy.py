from __future__ import annotations

import json
from pathlib import Path
import unittest


class VercelDeploymentPolicyTests(unittest.TestCase):
    def test_git_deployments_are_main_only(self):
        config=json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        enabled=config["git"]["deploymentEnabled"]
        self.assertIs(enabled["*"], False)
        self.assertIs(enabled["main"], True)

    def test_python_entrypoint_and_routes_remain_unchanged(self):
        config=json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(config["builds"], [{"src": "index.py", "use": "@vercel/python"}])
        self.assertEqual(config["routes"], [{"src": "/(.*)", "dest": "index.py"}])


if __name__ == "__main__":
    unittest.main()
