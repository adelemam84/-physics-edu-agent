from pathlib import Path
import unittest

API = Path("app/content_maintenance_api.py").read_text(encoding="utf-8")
WF = Path(".github/workflows/execute-edu001-edu003.yml").read_text(encoding="utf-8")

class Edu003ResumableMaintenanceTests(unittest.TestCase):
    def test_per_question_endpoint_exists(self):
        self.assertIn('/api/internal/content-maintenance/visual/{question_id}', API)
        self.assertIn('/api/internal/content-maintenance/visual-pending', API)

    def test_workflow_processes_question_ids_individually(self):
        self.assertIn('while read -r qid; do', WF)
        self.assertIn('/api/internal/content-maintenance/visual/$qid', WF)
        self.assertIn('--max-time 270', WF)
        self.assertNotIn('visual-batch?limit=5', WF)

if __name__ == "__main__":
    unittest.main()
