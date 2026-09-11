from __future__ import annotations

import logging
import os

from fastapi import Response

from .db import connect
from .main import app
from .services.runtime_identity import runtime_identity

logger = logging.getLogger(__name__)


def lightweight_runtime_readiness() -> dict:
    """Check low-cost dependencies required for technical service readiness.

    Content indexing and optional AI capabilities are reported separately so
    deferred source ingestion does not incorrectly mark the runtime unavailable.
    """
    identity = runtime_identity(application_version=app.version)
    config = dict(identity.get("config_state") or {})

    db_ok = False
    file_search_store = bool(os.getenv("GEMINI_FILE_SEARCH_STORE", "").strip())
    try:
        with connect() as con:
            row = con.execute("SELECT 1 ok").fetchone()
            db_ok = bool(row and int(row["ok"]) == 1)
            if db_ok and not file_search_store:
                store_row = con.execute(
                    """SELECT 1 ok FROM settings
                       WHERE key='gemini_file_search_store'
                         AND btrim(coalesce(value,''))<>''
                       LIMIT 1"""
                ).fetchone()
                file_search_store = bool(store_row)
    except Exception:
        db_ok = False
        file_search_store = False

    critical_config = {
        "database": bool(config.get("database")),
        "admin_access": bool(config.get("admin_access")),
        "student_session": bool(config.get("student_session")),
        "object_storage": bool(config.get("object_storage")),
    }
    optional_capabilities = {
        "gemini": bool(config.get("gemini")),
        "file_search_store": file_search_store,
    }

    deployment_ok = True
    if identity.get("provider") == "vercel" and identity.get("production_environment"):
        deployment_ok = bool(identity.get("current_runtime_is_production_main"))

    blockers: list[str] = []
    if not db_ok:
        blockers.append("database_runtime")
    blockers.extend(
        f"config:{name}"
        for name, configured in critical_config.items()
        if not configured
    )
    if not deployment_ok:
        blockers.append("deployment_provenance")

    ready = not blockers
    if not ready:
        logger.warning(
            "runtime_readiness_not_ready blockers=%s provenance_source=%s drift_state=%s",
            ",".join(blockers),
            identity.get("provenance_source") or "unknown",
            identity.get("drift_state") or "unknown",
        )

    return {
        "ready": ready,
        "database": db_ok,
        "critical_config": critical_config,
        "optional_capabilities": optional_capabilities,
        "deployment_ok": deployment_ok,
        "blockers": blockers,
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
