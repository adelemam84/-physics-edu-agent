from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping


def _truthy(value: object) -> bool:
    return bool(str(value or "").strip())


def runtime_identity(
    env: Mapping[str, str] | None = None,
    *,
    application_version: str | None = None,
) -> dict:
    """Return secret-free runtime/deployment identity and critical-config presence.

    The configuration fingerprint is derived only from boolean presence flags;
    secret values are never returned or hashed.

    Controlled CLI releases inject RELEASE_GIT_REF/RELEASE_GIT_SHA because
    Vercel Git system variables are not guaranteed to be available to a
    prebuilt CLI deployment at runtime. Native Vercel Git metadata remains the
    preferred provenance source when it is present.
    """
    source = env if env is not None else os.environ
    vercel_env = str(source.get("VERCEL_ENV") or "").strip()
    target_env = str(source.get("VERCEL_TARGET_ENV") or "").strip()
    system_commit_ref = str(source.get("VERCEL_GIT_COMMIT_REF") or "").strip()
    system_commit_sha = str(source.get("VERCEL_GIT_COMMIT_SHA") or "").strip()
    release_commit_ref = str(source.get("RELEASE_GIT_REF") or "").strip()
    release_commit_sha = str(source.get("RELEASE_GIT_SHA") or "").strip()
    commit_ref = system_commit_ref or release_commit_ref
    commit_sha = system_commit_sha or release_commit_sha
    deployment_id = str(source.get("VERCEL_DEPLOYMENT_ID") or "").strip()
    production_url = str(source.get("VERCEL_PROJECT_PRODUCTION_URL") or "").strip()
    on_vercel = str(source.get("VERCEL") or "") == "1"

    if system_commit_ref or system_commit_sha:
        provenance_source = "vercel_git"
    elif release_commit_ref or release_commit_sha:
        provenance_source = "controlled_release"
    else:
        provenance_source = "unavailable"

    config_state = {
        "database": _truthy(source.get("DATABASE_URL")),
        "admin_access": _truthy(source.get("ADMIN_API_KEY")),
        "student_session": _truthy(source.get("STUDENT_SESSION_SECRET")),
        "object_storage": all(
            _truthy(source.get(name))
            for name in (
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_ENDPOINT_URL_S3",
                "AWS_REGION",
            )
        ),
        "gemini": _truthy(source.get("GEMINI_API_KEY")),
        "openai_reviewer": _truthy(source.get("OPENAI_API_KEY")),
        "mathpix": bool(
            _truthy(source.get("MATHPIX_APP_ID"))
            and _truthy(source.get("MATHPIX_APP_KEY"))
        ),
    }
    config_fingerprint = hashlib.sha256(
        json.dumps(config_state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    production_environment = vercel_env == "production"
    deployed_from_main = commit_ref == "main" if commit_ref else None
    provenance_available = bool(
        vercel_env
        or target_env
        or commit_ref
        or commit_sha
        or deployment_id
    )
    current_runtime_is_production_main = bool(
        on_vercel
        and production_environment
        and commit_ref == "main"
        and commit_sha
    )

    if on_vercel and production_environment:
        drift_state = (
            "production_main"
            if current_runtime_is_production_main
            else "production_metadata_invalid"
        )
    elif on_vercel and vercel_env == "preview":
        drift_state = "preview"
    elif on_vercel:
        drift_state = "vercel_nonproduction"
    else:
        drift_state = "local_or_unknown"

    return {
        "provider": "vercel" if on_vercel else "unknown",
        "environment": vercel_env or None,
        "target_environment": target_env or None,
        "git_ref": commit_ref or None,
        "git_commit_sha": commit_sha or None,
        "git_commit_short": commit_sha[:12] if commit_sha else None,
        "provenance_source": provenance_source,
        "deployment_id": deployment_id or None,
        "production_url": production_url or None,
        "application_version": application_version,
        "provenance_available": provenance_available,
        "production_environment": production_environment,
        "deployed_from_main": deployed_from_main,
        "current_runtime_is_production_main": current_runtime_is_production_main,
        "drift_state": drift_state,
        "config_state": config_state,
        "config_fingerprint": config_fingerprint,
        "config_fingerprint_contains_secret_values": False,
        "latest_main_match": None,
        "latest_main_verification": "external_required",
    }
