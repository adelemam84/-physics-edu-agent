from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from app import db, main
from app.services import corpus_phase2_runtime as phase2


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _LockConnection:
    def __init__(self, acquired_sequence):
        self.sequence = list(acquired_sequence)
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            acquired = self.sequence.pop(0)
            return _Cursor({"acquired": acquired})
        if "pg_advisory_unlock" in sql:
            return _Cursor({"pg_advisory_unlock": True})
        raise AssertionError(sql)


class StartupMigrationLockTests(unittest.TestCase):
    def test_lock_retries_until_acquired(self):
        con = _LockConnection([False, True])
        with patch.object(db.time, "monotonic", side_effect=[0.0, 0.1]), \
             patch.object(db.time, "sleep") as sleep:
            attempts = db._acquire_startup_advisory_lock(
                con,
                wait_seconds=1.0,
                poll_seconds=0.05,
            )
        self.assertEqual(attempts, 2)
        sleep.assert_called_once_with(0.05)

    def test_lock_timeout_fails_closed(self):
        con = _LockConnection([False])
        with patch.object(db.time, "monotonic", side_effect=[0.0, 2.0]), \
             patch.object(db.time, "sleep"):
            with self.assertRaises(RuntimeError):
                db._acquire_startup_advisory_lock(
                    con,
                    wait_seconds=1.0,
                    poll_seconds=0.05,
                )

    def test_startup_lock_contract_is_session_scoped_and_released(self):
        source = inspect.getsource(db.startup_migration_lock)
        self.assertIn("autocommit=True", source)
        self.assertIn("pg_advisory_unlock", source)
        self.assertIn("finally:", source)
        self.assertIn("con.close()", source)

    def test_application_lifespan_serializes_schema_but_not_external_provider(self):
        source = inspect.getsource(main.lifespan)
        self.assertIn("with startup_migration_lock():", source)
        self.assertIn("ensure_phase2_schemas(release_schema_ready=True)", source)
        self.assertNotIn("run_phase2_bootstrap(", source)
        lock_start = source.index("with startup_migration_lock():")
        init_pos = source.index("init_db()")
        phase2_pos = source.index("ensure_phase2_schemas(release_schema_ready=True)")
        provider_pos = source.index("bootstrap_store_if_enabled()")
        self.assertLess(lock_start, init_pos)
        self.assertLess(init_pos, phase2_pos)
        self.assertLess(phase2_pos, provider_pos)

    def test_phase2_schema_bootstrap_can_skip_release_schema_when_init_db_applied_it(self):
        with patch(
            "app.services.lesson_release_state.ensure_release_state_schema"
        ) as release_schema, patch(
            "app.science_reference_library._schema"
        ) as reference_schema, patch(
            "app.science_reference_curriculum_map._map_schema"
        ) as map_schema, patch(
            "app.lesson_studio_version_history._history_schema"
        ) as history_schema:
            phase2.ensure_phase2_schemas(release_schema_ready=True)

        release_schema.assert_not_called()
        reference_schema.assert_called_once_with()
        map_schema.assert_called_once_with()
        history_schema.assert_called_once_with()

    def test_direct_phase2_bootstrap_still_ensures_release_schema(self):
        con = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = con
        context.__exit__.return_value = False
        with patch(
            "app.services.lesson_release_state.ensure_release_state_schema"
        ) as release_schema, patch(
            "app.science_reference_library._schema"
        ), patch(
            "app.science_reference_curriculum_map._map_schema"
        ), patch(
            "app.lesson_studio_version_history._history_schema"
        ), patch.object(
            phase2, "connect", return_value=context
        ), patch.object(
            phase2, "_active_context", return_value=None
        ):
            phase2.run_phase2_bootstrap()

        release_schema.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
