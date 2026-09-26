from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest.mock import patch

from app import release_hardening as release
from app import exam_blueprint, source_review
from app.services import active_content_integrity


class ReleaseStatusTimingsTests(unittest.TestCase):
    def test_status_helpers_borrow_connection_without_opening_another(self):
        class EmptyRows:
            def __init__(self, sql):
                self.sql = sql

            def fetchone(self):
                return {"name": None} if "to_regclass" in self.sql else None

            def fetchall(self):
                return []

        class EmptyConnection:
            def execute(self, sql, *_args):
                return EmptyRows(sql)

        shared = EmptyConnection()
        with (
            patch.object(exam_blueprint, "connect") as blueprint_connect,
            patch.object(source_review, "connect") as coverage_connect,
            patch.object(active_content_integrity, "connect") as integrity_connect,
            patch.object(release, "connect") as sync_connect,
        ):
            self.assertFalse(exam_blueprint.blueprint_readiness(shared)["active"])
            self.assertEqual(
                source_review._source_page_coverage_snapshot(con=shared)["summary"]["physical_pages"],
                0,
            )
            self.assertFalse(active_content_integrity.active_content_integrity_snapshot(shared)["ready"])
            self.assertEqual(release._sync_summary(shared)["total"], 0)

        for opener in (blueprint_connect, coverage_connect, integrity_connect, sync_connect):
            opener.assert_not_called()

    def test_slow_status_logs_only_stage_names_and_durations(self):
        connection = object()
        with (
            patch.object(release, "connect", return_value=nullcontext(connection)) as opened,
            patch.object(release, "research_engine_status", return_value={
                "configured": False,
                "orchestrator": {"status": "active"},
                "guardrails": {"question_bank_auto_write": False},
            }),
            patch.object(release, "blueprint_readiness", return_value={
                "blueprint": {"objective_questions": 23, "essay_questions": 23},
                "active_shape_feasible": False,
                "gaps": {"objective": 23, "essay": 23},
            }) as blueprint,
            patch.object(source_review, "_source_page_coverage_snapshot", return_value={
                "summary": {"coverage_ready": False},
            }) as coverage,
            patch.object(release, "active_content_integrity_snapshot", return_value={
                "ready": False,
            }) as integrity,
            patch.object(release, "_sync_summary", return_value={"total": 0}) as sync,
            patch.object(release, "configured_store_name", return_value=""),
            patch.object(release.time, "perf_counter", side_effect=range(0, 14)),
            patch.object(release._log, "warning") as warning,
        ):
            status = release.next_release_status()

        self.assertEqual(status["release_state"], "runtime_ready_content_gate_open")
        warning.assert_called_once()
        _, total, stages = warning.call_args.args
        self.assertEqual(total, 13000)
        self.assertEqual(set(stages), {
            "research", "connection", "blueprint", "source_coverage",
            "content_integrity", "source_sync",
        })
        self.assertTrue(all(value == 1000 for value in stages.values()))
        opened.assert_called_once_with()
        blueprint.assert_called_once_with(connection)
        coverage.assert_called_once_with(con=connection)
        integrity.assert_called_once_with(connection)
        sync.assert_called_once_with(connection)


if __name__ == "__main__":
    unittest.main()
