from __future__ import annotations

from fastapi import Depends

from .main import app
from .operations_readiness import build_operations_readiness
from .security import require_admin
from .technical_observability import technical_observability_snapshot


def _compact_signal(item: dict) -> dict:
    """Keep runtime-health signals actionable without exposing raw evidence payloads."""
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "severity": str(item.get("severity") or "info"),
        "ok": bool(item.get("ok")),
        "detail": str(item.get("detail") or ""),
        "path": str(item.get("path") or "/admin/technical-observability"),
    }


def runtime_health_snapshot() -> dict:
    """Return one admin-only, secret-free runtime health contract."""
    readiness = build_operations_readiness()
    observability = technical_observability_snapshot(
        readiness_snapshot=readiness,
    )
    identity = dict(observability.get("runtime_identity") or {})
    config_state = dict(identity.get("config_state") or {})

    ready = bool(readiness.get("ready_for_technical_handoff"))
    obs_state = str(observability.get("state") or "unhealthy")
    if not ready or obs_state == "unhealthy":
        state = "unhealthy"
    elif obs_state == "degraded":
        state = "degraded"
    else:
        state = "healthy"

    deployment = {
        "provider": identity.get("provider"),
        "environment": identity.get("environment"),
        "target_environment": identity.get("target_environment"),
        "git_ref": identity.get("git_ref"),
        "git_commit_short": identity.get("git_commit_short"),
        "deployment_id": identity.get("deployment_id"),
        "application_version": identity.get("application_version") or app.version,
        "drift_state": identity.get("drift_state"),
        "current_runtime_is_production_main": bool(
            identity.get("current_runtime_is_production_main")
        ),
    }

    return {
        "state": state,
        "healthy": state == "healthy",
        "version": app.version,
        "ready_for_technical_handoff": ready,
        "ready_for_controlled_launch": bool(
            readiness.get("ready_for_controlled_launch")
        ),
        "content_release_ready": bool(readiness.get("content_release_ready")),
        "release_state": readiness.get("release_state"),
        "technical_blocker_count": len(
            readiness.get("technical_blockers") or []
        ),
        "content_gate_count": len(readiness.get("content_gates") or []),
        "content_gates": list(readiness.get("content_gates") or []),
        "observability": {
            "state": obs_state,
            "error_count": int(observability.get("error_count") or 0),
            "warning_count": int(observability.get("warning_count") or 0),
            "signals": [
                _compact_signal(item)
                for item in (observability.get("signals") or [])
                if isinstance(item, dict)
            ],
        },
        "deployment": deployment,
        "configuration": {
            "state": config_state,
            "fingerprint": identity.get("config_fingerprint"),
            "contains_secret_values": False,
        },
        "policy": {
            "admin_only": True,
            "content_gates_do_not_change_technical_state": True,
            "raw_signal_evidence_omitted": True,
            "secret_values_never_returned": True,
        },
    }


@app.get("/api/admin/runtime-health", dependencies=[Depends(require_admin)])
def runtime_health_api():
    return runtime_health_snapshot()
