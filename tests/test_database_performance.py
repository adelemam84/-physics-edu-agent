from __future__ import annotations

import inspect
import unittest

from app import database_performance as perf


class DatabasePerformanceTests(unittest.TestCase):
    def _summary(self, *, connections=2, max_connections=112):
        return {
            "db_bytes": 1024 * 1024,
            "connections": connections,
            "max_connections": max_connections,
        }

    def test_small_table_sequential_scans_are_not_false_alerts(self):
        data = perf.evaluate_database_performance(
            self._summary(),
            [{
                "table_name": "questions",
                "table_bytes": 176 * 1024,
                "seq_scan": 1010,
                "idx_scan": 30,
                "live_tuples": 216,
                "dead_tuples": 38,
            }],
            [],
            query_stats_available=True,
        )
        self.assertEqual(data["state"], "healthy")
        self.assertEqual(data["warning_count"], 0)

    def test_large_scan_heavy_table_is_warning(self):
        data = perf.evaluate_database_performance(
            self._summary(),
            [{
                "table_name": "questions",
                "table_bytes": 12 * 1024 * 1024,
                "seq_scan": 1200,
                "idx_scan": 100,
                "live_tuples": 50000,
                "dead_tuples": 20,
            }],
            [],
            query_stats_available=True,
        )
        self.assertEqual(data["state"], "degraded")
        signal = next(
            x for x in data["signals"]
            if x["id"] == "large_sequential_scans"
        )
        self.assertEqual(signal["severity"], "warning")

    def test_small_high_dead_tuple_ratio_does_not_trigger_maintenance(self):
        data = perf.evaluate_database_performance(
            self._summary(),
            [{
                "table_name": "document_pages",
                "table_bytes": 56 * 1024,
                "seq_scan": 50,
                "idx_scan": 10,
                "live_tuples": 52,
                "dead_tuples": 47,
            }],
            [],
            query_stats_available=True,
        )
        self.assertEqual(data["state"], "healthy")

    def test_large_dead_tuple_pressure_is_warning(self):
        data = perf.evaluate_database_performance(
            self._summary(),
            [{
                "table_name": "attempts",
                "table_bytes": 20 * 1024 * 1024,
                "seq_scan": 10,
                "idx_scan": 1000,
                "live_tuples": 2000,
                "dead_tuples": 1000,
            }],
            [],
            query_stats_available=True,
        )
        self.assertEqual(data["state"], "degraded")
        self.assertTrue(
            any(x["id"] == "vacuum_pressure" for x in data["signals"])
        )

    def test_query_warning_requires_repetition_and_latency(self):
        one_slow_call = perf.evaluate_database_performance(
            self._summary(),
            [],
            [{
                "query": "SELECT * FROM questions",
                "calls": 1,
                "mean_exec_time_ms": 900,
                "total_exec_time_ms": 900,
                "rows": 1,
            }],
            query_stats_available=True,
        )
        self.assertEqual(one_slow_call["state"], "healthy")

        repeated = perf.evaluate_database_performance(
            self._summary(),
            [],
            [{
                "query": "SELECT * FROM questions",
                "calls": 4,
                "mean_exec_time_ms": 700,
                "total_exec_time_ms": 2800,
                "rows": 4,
            }],
            query_stats_available=True,
        )
        self.assertEqual(repeated["state"], "degraded")
        self.assertEqual(
            next(x for x in repeated["signals"] if x["id"] == "slow_queries")[
                "severity"
            ],
            "warning",
        )

    def test_repeated_two_second_query_is_unhealthy(self):
        data = perf.evaluate_database_performance(
            self._summary(),
            [],
            [{
                "query": "SELECT * FROM attempts",
                "calls": 3,
                "mean_exec_time_ms": 2200,
                "total_exec_time_ms": 6600,
                "rows": 30,
            }],
            query_stats_available=True,
        )
        self.assertEqual(data["state"], "unhealthy")
        self.assertEqual(data["error_count"], 1)

    def test_connection_pressure_thresholds(self):
        warning = perf.evaluate_database_performance(
            self._summary(connections=80, max_connections=100),
            [],
            [],
            query_stats_available=False,
        )
        self.assertEqual(warning["state"], "degraded")

        error = perf.evaluate_database_performance(
            self._summary(connections=95, max_connections=100),
            [],
            [],
            query_stats_available=False,
        )
        self.assertEqual(error["state"], "unhealthy")

    def test_admin_api_and_page_are_protected(self):
        source = inspect.getsource(perf)
        self.assertGreaterEqual(
            source.count('dependencies=[Depends(require_admin)]'),
            2,
        )


if __name__ == "__main__":
    unittest.main()
