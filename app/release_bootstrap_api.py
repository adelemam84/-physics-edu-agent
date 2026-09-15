from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

from .main import app
from .startup_bootstrap import apply_startup_bootstrap


def _release_token() -> str:
    return os.getenv("RELEASE_BOOTSTRAP_TOKEN", "").strip()


def _authorize_release_bootstrap(request: Request) -> None:
    expected = _release_token()
    if not expected:
        # This route is inert on deployments that were not staged by the
        # controlled release workflow.
        raise HTTPException(404, "Not found")

    supplied = request.headers.get("x-release-bootstrap-token", "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(403, "Invalid release bootstrap credential")

    if os.getenv("VERCEL_ENV", "").strip().lower() != "production":
        raise HTTPException(409, "Release bootstrap is production-only")

    if os.getenv("RELEASE_GIT_REF", "").strip() != "main":
        raise HTTPException(409, "Release bootstrap requires main provenance")


@app.post("/api/internal/release-bootstrap", include_in_schema=False)
def release_bootstrap(request: Request):
    """Apply idempotent schema/provider bootstrap inside the staged Vercel runtime."""
    _authorize_release_bootstrap(request)
    apply_startup_bootstrap()
    release_sha = os.getenv("RELEASE_GIT_SHA", "").strip()
    return {
        "status": "ok",
        "runtime_bootstrap": "applied",
        "release_sha": release_sha[:12] if release_sha else None,
    }
