from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app import startup_schema


class StartupSchemaSentinelTests(unittest.TestCase):
    def test_matching_release_skips_migration_lock(self):
        with patch.object(startup_schema, "schema_release_matches", return_value=True),              patch.object(startup_schema, "startup_migration_lock") as lock,              patch.object(startup_schema, "init_db") as init_db:
            result = startup_schema.ensure_runtime_schema(marker="sha-1")

        lock.assert_not_called()
        init_db.assert_not_called()
        self.assertFalse(result["migrated"])
        self.assertEqual(result["reason"], "release_already_applied")

    def test_follower_rechecks_after_lock_and_skips_duplicate_migration(self):
        context = MagicMock()
        context.__enter__.return_value = None
        context.__exit__.return_value = False

        with patch.object(
            startup_schema,
            "schema_release_matches",
            side_effect=[False, True],
        ) as matches, patch.object(
            startup_schema,
            "startup_migration_lock",
            return_value=context,
        ) as lock, patch.object(
            startup_schema,
            "init_db",
        ) as init_db:
            result = startup_schema.ensure_runtime_schema(marker="sha-2")

        self.assertEqual(matches.call_count, 2)
        lock.assert_called_once_with()
        init_db.assert_not_called()
        self.assertEqual(result["reason"], "release_applied_by_leader")

    def test_new_release_runs_schema_once_and_marks_release(self):
        context = MagicMock()
        context.__enter__.return_value = None
        context.__exit__.return_value = False

        with patch.object(
            startup_schema,
            "schema_release_matches",
            side_effect=[False, False],
        ), patch.object(
            startup_schema,
            "startup_migration_lock",
            return_value=context,
        ), patch.object(
            startup_schema,
            "init_db",
        ) as init_db, patch(
            "app.services.corpus_phase2_runtime.ensure_phase2_schemas"
        ) as phase2, patch.object(
            startup_schema,
            "mark_schema_release",
        ) as mark:
            result = startup_schema.ensure_runtime_schema(marker="sha-3")

        init_db.assert_called_once_with()
        phase2.assert_called_once_with(release_schema_ready=True)
        mark.assert_called_once_with("sha-3")
        self.assertTrue(result["migrated"])
        self.assertEqual(result["reason"], "schema_initialized")

    def test_release_marker_prefers_explicit_release_sha(self):
        with patch.dict(
            "os.environ",
            {
                "RELEASE_GIT_SHA": "release-sha",
                "VERCEL_GIT_COMMIT_SHA": "vercel-sha",
            },
            clear=False,
        ):
            self.assertEqual(startup_schema.runtime_release_marker(), "release-sha")


if __name__ == "__main__":
    unittest.main()
