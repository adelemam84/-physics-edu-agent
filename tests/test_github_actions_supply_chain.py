from __future__ import annotations

import re
from pathlib import Path
import unittest


WORKFLOW_DIR = Path(".github/workflows")
USES_RE = re.compile(r"^\s*uses:\s*([^\s#]+)", re.MULTILINE)
FULL_SHA_RE = re.compile(r"^[^@]+@[0-9a-f]{40}$")


class GithubActionsSupplyChainTests(unittest.TestCase):
    def test_third_party_actions_are_pinned_to_full_commit_sha(self):
        offenders: list[str] = []
        for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            for ref in USES_RE.findall(text):
                if ref.startswith("./"):
                    continue
                if not FULL_SHA_RE.fullmatch(ref):
                    offenders.append(f"{workflow}:{ref}")
        self.assertEqual(offenders, [], "Unpinned GitHub Actions: " + ", ".join(offenders))

    def test_core_actions_use_node24_generation(self):
        expected = {
            "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
            "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",
            "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        }
        joined = "\n".join(
            path.read_text(encoding="utf-8") for path in WORKFLOW_DIR.glob("*.yml")
        )
        for action, sha in expected.items():
            if action in joined:
                self.assertIn(f"{action}@{sha}", joined)


if __name__ == "__main__":
    unittest.main()
