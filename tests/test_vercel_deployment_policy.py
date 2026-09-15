from __future__ import annotations

import json
from pathlib import Path
import unittest


class VercelDeploymentPolicyTests(unittest.TestCase):
    def test_git_auto_deployments_are_disabled_for_controlled_releases(self):
        config=json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        self.assertIs(config["git"]["deploymentEnabled"], False)
        self.assertNotIn("ignoreCommand", config)

    def test_lightweight_status_plane_precedes_main_catchall(self):
        config=json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(
            config["builds"],
            [
                {"src": "status.py", "use": "@vercel/python"},
                {"src": "index.py", "use": "@vercel/python"},
            ],
        )
        self.assertEqual(
            config["routes"],
            [
                {"src": "/health", "dest": "status.py"},
                {"src": "/health/ready", "dest": "status.py"},
                {"src": "/api/research-engine/status", "dest": "status.py"},
                {"src": "/(.*)", "dest": "index.py"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
