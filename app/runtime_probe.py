from __future__ import annotations

import os

from fastapi import Response

from .db import connect
from .main import app
from .services.runtime_identity import runtime_identity


def _file_search_store_configured() -> bool:
    env_name = os.getenv("GEMINI_FILE_SEARCH_STORE", "").strip()
    if env_name:
        return True
    try:
        with connect() as con:
            row = con.execute(
                """SELECT value FROM settings
                   WHERE key='gemini_file_search_store'
                     AND btrim(coalesce(value,''))<>''"""
            ).fetchone()
        return bool(row)
    except Exception:
        return False


def lightweight_runtime_readiness() -> dict:
    """Check only low-cost runtime dependencies required for technical service."""
    identity = runtime_identity(application_version=app.version)
    config = dict(identity.get("config_state") or {})

    db_ok = False
    try:
        with connect() as con:
            row = con.execute("SELECT 1 ok").fetchone()
        db_ok = bool(row and int(row["ok"]) == 1)
    except Exception:
        db_ok = False

    critical_config = {
        "database": bool(config.get("database")),
        "admin_access": bool(config.get("admin_access")),
        "student_session": bool(config.get("student_session")),
        "object_storage": bool(config.get("object_storage")),
        "gemini": bool(config.get("gemini")),
        "file_search_store": bool(db_ok and _file_search_store_configured()),
    }

    deployment_ok = True
    if identity.get("provider") == "vercel" and identity.get("production_environment"):
        deployment_ok = bool(identity.get("current_runtime_is_production_main"))

    ready = bool(
        db_ok
        and all(critical_config.values())
        and deployment_ok
    )
    return {
        "ready": ready,
        "database": db_ok,
        "critical_config": critical_config,
        "deployment_ok": deployment_ok,
        "version": app.version,
    }


@app.get("/health/ready")
def health_ready(response: Response):
    """Public minimal readiness probe: status only, no topology/config details."""
    probe = lightweight_runtime_readiness()
    response.headers["Cache-Control"] = "no-store"
    if not probe["ready"]:
        response.status_code = 503
    return {
        "status": "ready" if probe["ready"] else "not_ready",
        "service": "science-education-platform",
        "version": app.version,
    }
