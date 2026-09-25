from __future__ import annotations

import unittest
from unittest.mock import patch

from app import release_hardening as release
from app import source_review


class ReleaseStatusTimingsTests(unittest.TestCase):
    def test_slow_status_logs_only_stage_names_and_durations(self):
        with (
            patch.object(release, "research_engine_status", return_value={
                "configured": False,
                "orchestrator": {"status": "active"},
                "guardrails": {"question_bank_auto_write": False},
            }),
            patch.object(release, "blueprint_readiness", return_value={
                "blueprint": {"objective_questions": 23, "essay_questions": 23},
                "active_shape_feasible": False,
                "gaps": {"objective": 23, "essay": 23},
            }),
            patch.object(source_review, "_source_page_coverage_snapshot", return_value={
                "summary": {"coverage_ready": False},
            }),
            patch.object(release, "active_content_integrity_snapshot", return_value={
                "ready": False,
            }),
            patch.object(release, "_sync_summary", return_value={"total": 0}),
            patch.object(release, "configured_store_name", return_value=""),
            patch.object(release.time, "perf_counter", side_effect=range(0, 12)),
            patch.object(release._log, "warning") as warning,
        ):
            status = release.next_release_status()

        self.assertEqual(status["release_state"], "runtime_ready_content_gate_open")
        warning.assert_called_once()
        _, total, stages = warning.call_args.args
        self.assertEqual(total, 11000)
        self.assertEqual(set(stages), {
            "research", "blueprint", "source_coverage",
            "content_integrity", "source_sync",
        })
        self.assertTrue(all(value == 1000 for value in stages.values()))


if __name__ == "__main__":
    unittest.main()
