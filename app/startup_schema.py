from __future__ import annotations

import os

from .db import connect, init_db, startup_migration_lock

SCHEMA_RELEASE_SETTING = "startup_schema_release"


def runtime_release_marker() -> str:
    return (
        os.getenv("RELEASE_GIT_SHA", "").strip()
        or os.getenv("VERCEL_GIT_COMMIT_SHA", "").strip()
    )


def schema_release_matches(marker: str) -> bool:
    marker = str(marker or "").strip()
    if not marker:
        return False
    try:
        with connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=%s",
                (SCHEMA_RELEASE_SETTING,),
            ).fetchone()
        return bool(row and str(row.get("value") or "").strip() == marker)
    except Exception:
        return False


def mark_schema_release(marker: str) -> None:
    marker = str(marker or "").strip()
    if not marker:
        return
    with connect() as con:
        con.execute(
            """INSERT INTO settings(key,value) VALUES(%s,%s)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (SCHEMA_RELEASE_SETTING, marker),
        )


def ensure_runtime_schema(*, marker: str | None = None) -> dict:
    """Run startup DDL once per release and let follower cold starts skip the lock."""
    release_marker = str(marker if marker is not None else runtime_release_marker()).strip()

    if release_marker and schema_release_matches(release_marker):
        return {
            "migrated": False,
            "release_marker": release_marker,
            "reason": "release_already_applied",
        }

    from .services.corpus_phase2_runtime import ensure_phase2_schemas

    with startup_migration_lock():
        # A follower may have observed a stale sentinel just before the leader
        # acquired the lock, so always re-check after lock acquisition.
        if release_marker and schema_release_matches(release_marker):
            return {
                "migrated": False,
                "release_marker": release_marker,
                "reason": "release_applied_by_leader",
            }

        init_db()
        ensure_phase2_schemas(release_schema_ready=True)
        if release_marker:
            mark_schema_release(release_marker)

    return {
        "migrated": True,
        "release_marker": release_marker or None,
        "reason": "schema_initialized",
    }
