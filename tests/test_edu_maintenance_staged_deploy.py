from pathlib import Path
import unittest

WORKFLOW = Path(".github/workflows/execute-edu001-edu003.yml").read_text(encoding="utf-8")
SCRIPT = Path("tools/manual_content_maintenance.sh").read_text(encoding="utf-8")


class EduMaintenanceStagedDeployTests(unittest.TestCase):
    def test_staged_deploy_does_not_wait_forever(self):
        self.assertIn("tools/manual_content_maintenance.sh", WORKFLOW)
        self.assertIn("--no-wait", SCRIPT)
        self.assertIn('timeout 180s "${VERCEL[@]}" inspect "$DEPLOYMENT_URL" --wait', SCRIPT)
        self.assertIn("for attempt in 1 2; do", SCRIPT)

    def test_stuck_deployment_is_cleaned_before_retry(self):
        self.assertIn('"${VERCEL[@]}" remove "$DEPLOYMENT_URL" --yes', SCRIPT)
        self.assertIn('DEPLOYMENT_URL=""', SCRIPT)


if __name__ == "__main__":
    unittest.main()
