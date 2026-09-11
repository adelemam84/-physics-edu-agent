from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import psycopg

from app import db


class DatabaseResilienceTests(unittest.TestCase):
    def test_default_policy_is_bounded_and_never_replays_transactions(self):
        policy = db.database_resilience_profile({})
        self.assertEqual(policy["connect_timeout_seconds"], 10)
        self.assertEqual(policy["connect_retries"], 2)
        self.assertEqual(policy["retry_base_delay_ms"], 150)
        self.assertEqual(policy["retry_max_delay_ms"], 1200)
        self.assertEqual(policy["runtime_statement_timeout_ms"], 45000)
        self.assertEqual(policy["runtime_lock_timeout_ms"], 5000)
        self.assertEqual(policy["migration_statement_timeout_ms"], 180000)
        self.assertEqual(policy["migration_lock_timeout_ms"], 30000)
        self.assertEqual(policy["transaction_retries"], 0)
        self.assertFalse(policy["secret_values_returned"])

    def test_invalid_policy_values_fall_back_safely(self):
        policy = db.database_resilience_profile({
            "DATABASE_CONNECT_TIMEOUT_SECONDS": "bad",
            "DATABASE_CONNECT_RETRIES": "-2",
            "DATABASE_RETRY_BASE_DELAY_MS": "0",
            "DATABASE_STATEMENT_TIMEOUT_MS": "-1",
        })
        self.assertEqual(policy["connect_timeout_seconds"], 10)
        self.assertEqual(policy["connect_retries"], 2)
        self.assertEqual(policy["retry_base_delay_ms"], 150)
        self.assertEqual(policy["runtime_statement_timeout_ms"], 45000)

    def test_connection_establishment_retries_operational_error_only(self):
        con = MagicMock()
        with patch.object(
            db,
            "database_resilience_profile",
            return_value={
                "connect_timeout_seconds": 10,
                "connect_retries": 2,
                "retry_base_delay_ms": 100,
                "retry_max_delay_ms": 500,
            },
        ), patch(
            "psycopg.connect",
            side_effect=[
                psycopg.OperationalError("transient"),
                psycopg.OperationalError("transient"),
                con,
            ],
        ) as connect_call, patch.object(db.time, "sleep") as sleep:
            result = db._open_connection("postgresql://example")

        self.assertIs(result, con)
        self.assertEqual(connect_call.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            [0.1, 0.2],
        )

    def test_connection_retry_stops_at_configured_limit(self):
        with patch.object(
            db,
            "database_resilience_profile",
            return_value={
                "connect_timeout_seconds": 10,
                "connect_retries": 1,
                "retry_base_delay_ms": 50,
                "retry_max_delay_ms": 500,
            },
        ), patch(
            "psycopg.connect",
            side_effect=psycopg.OperationalError("down"),
        ) as connect_call, patch.object(db.time, "sleep") as sleep:
            with self.assertRaises(psycopg.OperationalError):
                db._open_connection("postgresql://example")

        self.assertEqual(connect_call.call_count, 2)
        sleep.assert_called_once_with(0.05)

    def test_non_operational_connection_error_is_not_retried(self):
        with patch.object(
            db,
            "database_resilience_profile",
            return_value={
                "connect_timeout_seconds": 10,
                "connect_retries": 5,
                "retry_base_delay_ms": 100,
                "retry_max_delay_ms": 500,
            },
        ), patch(
            "psycopg.connect",
            side_effect=ValueError("bad configuration"),
        ) as connect_call, patch.object(db.time, "sleep") as sleep:
            with self.assertRaises(ValueError):
                db._open_connection("postgresql://example")

        connect_call.assert_called_once()
        sleep.assert_not_called()

    def test_runtime_transaction_uses_local_statement_and_lock_limits(self):
        con = MagicMock()
        with patch.object(
            db,
            "database_resilience_profile",
            return_value={
                "runtime_statement_timeout_ms": 45000,
                "runtime_lock_timeout_ms": 5000,
                "migration_statement_timeout_ms": 180000,
                "migration_lock_timeout_ms": 30000,
            },
        ):
            db._apply_transaction_timeouts(con, migration=False)

        sql, params = con.execute.call_args.args
        self.assertIn("set_config('statement_timeout'", sql)
        self.assertIn("set_config('lock_timeout'", sql)
        self.assertEqual(params, ("45000ms", "5000ms"))

    def test_migration_transaction_gets_longer_local_limits(self):
        con = MagicMock()
        with patch.object(
            db,
            "database_resilience_profile",
            return_value={
                "runtime_statement_timeout_ms": 45000,
                "runtime_lock_timeout_ms": 5000,
                "migration_statement_timeout_ms": 180000,
                "migration_lock_timeout_ms": 30000,
            },
        ):
            db._apply_transaction_timeouts(con, migration=True)

        self.assertEqual(
            con.execute.call_args.args[1],
            ("180000ms", "30000ms"),
        )

    def test_sql_failure_is_never_replayed_by_connect_context(self):
        con = MagicMock()
        failure = psycopg.OperationalError("connection lost after transaction began")
        with patch.object(db, "RUNTIME_DATABASE_URL", "postgresql://runtime"), \
             patch.object(db, "_open_connection", return_value=con) as opener, \
             patch.object(db, "_apply_transaction_timeouts"):
            with self.assertRaises(psycopg.OperationalError):
                with db.connect():
                    raise failure

        opener.assert_called_once()
        con.rollback.assert_called_once_with()
        con.commit.assert_not_called()
        con.close.assert_called_once_with()

    def test_direct_context_selects_migration_timeout_policy(self):
        con = MagicMock()
        with patch.object(db, "RUNTIME_DATABASE_URL", "postgresql://runtime"), \
             patch.object(db, "DIRECT_DATABASE_URL", "postgresql://direct"), \
             patch.object(db, "_open_connection", return_value=con) as opener, \
             patch.object(db, "_apply_transaction_timeouts") as apply_timeouts:
            with db.direct_database_context():
                with db.connect():
                    pass

        self.assertEqual(opener.call_args.args[0], "postgresql://direct")
        self.assertEqual(
            opener.call_args.kwargs["application_name"],
            "physics-edu-migration",
        )
        apply_timeouts.assert_called_once_with(con, migration=True)
        con.commit.assert_called_once_with()
        con.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
