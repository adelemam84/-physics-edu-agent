from pathlib import Path
import unittest

WORKFLOW = Path(".github/workflows/execute-edu001-edu003.yml").read_text(encoding="utf-8")


class EduMaintenanceStagedDeployTests(unittest.TestCase):
    def test_staged_deploy_does_not_wait_forever(self):
        self.assertIn("--no-wait", WORKFLOW)
        self.assertIn('timeout 180s vercel inspect "$URL" --wait', WORKFLOW)
        self.assertIn("for attempt in 1 2; do", WORKFLOW)

    def test_stuck_deployment_is_cleaned_before_retry(self):
        self.assertIn('vercel remove "$URL" --yes', WORKFLOW)
        self.assertIn('URL=""', WORKFLOW)


if __name__ == "__main__":
    unittest.main()
