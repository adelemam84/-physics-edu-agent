from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.security import admin_key_configuration_state


class AdminKeyConfigurationStateTests(unittest.TestCase):
    def test_clean_key_reports_no_secret_material(self):
        with patch.dict(
            os.environ,
            {
                "ADMIN_API_KEY": "high-entropy-admin-key",
                "RELEASE_ADMIN_KEY_REVISION": "rev-123",
            },
            clear=False,
        ):
            data = admin_key_configuration_state()
        self.assertTrue(data["configured"])
        self.assertEqual(data["format"], "clean")
        self.assertEqual(data["revision"], "rev-123")
        self.assertFalse(data["contains_secret_value"])
        self.assertNotIn("high-entropy-admin-key", repr(data))

    def test_common_copy_paste_format_issues_are_reported_without_normalizing_secret(self):
        marker = "private-value-9917"
        cases = {
            f"  {marker}  ": "surrounding_whitespace",
            f"ADMIN_API_KEY={marker}": "assignment_prefix",
            f'"{marker}"': "wrapped_quotes",
            f"'{marker}'": "wrapped_quotes",
        }
        for raw, expected_issue in cases.items():
            with self.subTest(raw=raw), patch.dict(
                os.environ,
                {"ADMIN_API_KEY": raw, "RELEASE_ADMIN_KEY_REVISION": ""},
                clear=False,
            ):
                data = admin_key_configuration_state()
                self.assertTrue(data["configured"])
                self.assertIn(expected_issue, data["format"])
                self.assertIsNone(data["revision"])
                self.assertNotIn(marker, repr(data))

    def test_missing_key_is_reported_without_value(self):
        with patch.dict(
            os.environ,
            {"ADMIN_API_KEY": "", "RELEASE_ADMIN_KEY_REVISION": ""},
            clear=False,
        ):
            data = admin_key_configuration_state()
        self.assertFalse(data["configured"])
        self.assertEqual(data["format"], "missing")
        self.assertIsNone(data["revision"])


if __name__ == "__main__":
    unittest.main()
