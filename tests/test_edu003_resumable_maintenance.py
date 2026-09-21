from pathlib import Path
import unittest

API = Path("app/content_maintenance_api.py").read_text(encoding="utf-8")
WF = Path(".github/workflows/execute-edu001-edu003.yml").read_text(encoding="utf-8")
SCRIPT = Path("tools/manual_content_maintenance.sh").read_text(encoding="utf-8")

class Edu003ResumableMaintenanceTests(unittest.TestCase):
    def test_per_question_endpoint_exists(self):
        self.assertIn('/api/internal/content-maintenance/visual/{question_id}', API)
        self.assertIn('/api/internal/content-maintenance/visual-pending', API)

    def test_maintenance_processes_question_ids_individually(self):
        self.assertIn("tools/manual_content_maintenance.sh", WF)
        self.assertIn('while read -r qid; do', SCRIPT)
        self.assertIn('/api/internal/content-maintenance/visual/$qid', SCRIPT)
        self.assertIn('--max-time 270', SCRIPT)
        self.assertNotIn('visual-batch?limit=5', SCRIPT)

if __name__ == "__main__":
    unittest.main()
