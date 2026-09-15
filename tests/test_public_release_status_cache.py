from __future__ import annotations

import unittest
from unittest.mock import patch

from app import release_hardening as release


def _full_status(version: str = "1.8.1") -> dict:
    return {
        "version": version,
        "release_state": "runtime_ready_content_gate_open",
        "checks": {"orchestrator_active": True},
        "source_page_coverage": {"coverage_ready": True},
        "exam_blueprint": {"feasible": False, "gaps": {"essay": 16}},
    }


class PublicReleaseStatusCacheTests(unittest.TestCase):
    def setUp(self):
        release._public_status_cache = None

    def tearDown(self):
        release._public_status_cache = None

    def test_public_burst_is_coalesced_within_ttl(self):
        with (
            patch.object(release, "next_release_status", return_value=_full_status()) as status,
            patch.object(release.time, "monotonic", side_effect=[10.0, 10.0, 10.1]),
        ):
            first = release._public_next_release_snapshot()
            second = release._public_next_release_snapshot()

        self.assertEqual(first, second)
        self.assertEqual(status.call_count, 1)
        self.assertEqual(first["release_state"], "runtime_ready_content_gate_open")

    def test_public_cache_refreshes_after_ttl(self):
        ttl = release.PUBLIC_STATUS_TTL_SECONDS
        with (
            patch.object(
                release,
                "next_release_status",
                side_effect=[_full_status("first"), _full_status("second")],
            ) as status,
            patch.object(
                release.time,
                "monotonic",
                side_effect=[20.0, 20.0, 20.0 + ttl + 0.1, 20.0 + ttl + 0.1],
            ),
        ):
            first = release._public_next_release_snapshot()
            second = release._public_next_release_snapshot()

        self.assertEqual(status.call_count, 2)
        self.assertEqual(first["version"], "first")
        self.assertEqual(second["version"], "second")

    def test_admin_status_remains_fresh_and_bypasses_public_cache(self):
        with patch.object(
            release,
            "next_release_status",
            side_effect=[_full_status("public"), _full_status("admin")],
        ) as status:
            with patch.object(release.time, "monotonic", side_effect=[30.0, 30.0]):
                public = release._public_next_release_snapshot()
            admin = release.admin_next_release_status()

        self.assertEqual(status.call_count, 2)
        self.assertEqual(public["version"], "public")
        self.assertEqual(admin["version"], "admin")


if __name__ == "__main__":
    unittest.main()
