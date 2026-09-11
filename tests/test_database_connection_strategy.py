from __future__ import annotations

import unittest
from unittest.mock import patch

from app import db


DIRECT = (
    "postgresql://user:secret@"
    "ep-shiny-tree-a5rntytr.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require"
)
POOLED = (
    "postgresql://user:secret@"
    "ep-shiny-tree-a5rntytr-pooler.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require"
)


class DatabaseConnectionStrategyTests(unittest.TestCase):
    def test_neon_pooler_hostname_is_derived_in_correct_position(self):
        self.assertEqual(db._to_neon_pooled_url(DIRECT), POOLED)
        self.assertEqual(db._to_neon_direct_url(POOLED), DIRECT)

    def test_auto_pooling_uses_pooler_on_vercel_and_direct_for_migrations(self):
        urls = db.resolve_database_urls({
            "DATABASE_URL": DIRECT,
            "DATABASE_RUNTIME_POOLING": "auto",
            "VERCEL": "1",
            "VERCEL_ENV": "production",
        })
        self.assertEqual(urls["runtime_url"], POOLED)
        self.assertEqual(urls["direct_url"], DIRECT)
        self.assertEqual(urls["pooling_policy"], "auto")

    def test_auto_pooling_stays_direct_off_vercel(self):
        urls = db.resolve_database_urls({
            "DATABASE_URL": DIRECT,
            "DATABASE_RUNTIME_POOLING": "auto",
        })
        self.assertEqual(urls["runtime_url"], DIRECT)
        self.assertEqual(urls["direct_url"], DIRECT)

    def test_pooled_database_url_derives_safe_direct_migration_url(self):
        urls = db.resolve_database_urls({
            "DATABASE_URL": POOLED,
            "DATABASE_RUNTIME_POOLING": "auto",
            "VERCEL": "1",
        })
        self.assertEqual(urls["runtime_url"], POOLED)
        self.assertEqual(urls["direct_url"], DIRECT)

    def test_explicit_direct_override_wins_for_migrations(self):
        alternate_direct = DIRECT.replace("ep-shiny-tree", "ep-explicit")
        urls = db.resolve_database_urls({
            "DATABASE_URL": POOLED,
            "DATABASE_DIRECT_URL": alternate_direct,
            "DATABASE_RUNTIME_POOLING": "pooled",
            "VERCEL": "1",
        })
        self.assertEqual(urls["runtime_url"], POOLED)
        self.assertEqual(urls["direct_url"], alternate_direct)
        self.assertTrue(urls["direct_override"])

    def test_non_neon_database_is_never_rewritten(self):
        url = "postgresql://user:secret@db.example.com/app"
        urls = db.resolve_database_urls({
            "DATABASE_URL": url,
            "DATABASE_RUNTIME_POOLING": "pooled",
            "VERCEL": "1",
        })
        self.assertEqual(urls["runtime_url"], url)
        self.assertEqual(urls["direct_url"], url)

    def test_connection_profile_never_returns_database_secrets(self):
        profile = db.database_connection_profile({
            "DATABASE_URL": DIRECT,
            "DATABASE_RUNTIME_POOLING": "auto",
            "VERCEL": "1",
        })
        self.assertEqual(profile["runtime_mode"], "pooled")
        self.assertEqual(profile["migration_mode"], "direct")
        self.assertTrue(profile["migration_safe"])
        self.assertTrue(profile["automatic_pooler_derivation"])
        self.assertFalse(profile["secret_values_returned"])
        rendered = repr(profile)
        self.assertNotIn("user", rendered)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("ep-shiny-tree", rendered)

    def test_direct_context_switches_selected_connection_and_restores_it(self):
        with patch.object(db, "RUNTIME_DATABASE_URL", POOLED), \
             patch.object(db, "DIRECT_DATABASE_URL", DIRECT):
            self.assertEqual(db._selected_database_url(), POOLED)
            with db.direct_database_context():
                self.assertEqual(db._selected_database_url(), DIRECT)
            self.assertEqual(db._selected_database_url(), POOLED)


if __name__ == "__main__":
    unittest.main()
