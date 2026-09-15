from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

from .main import app
from .startup_bootstrap import apply_startup_bootstrap


def _authorize_release_bootstrap(request: Request) -> None:
    expected = os.getenv("RELEASE_BOOTSTRAP_TOKEN", "").strip()
    supplied = request.headers.get("x-release-bootstrap-token", "").strip()
    if (
        os.getenv("VERCEL_ENV", "").strip().lower() != "production"
        or not expected
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(status_code=404, detail="Not found")

    if os.getenv("RELEASE_GIT_REF", "").strip() != "main":
        raise HTTPException(status_code=404, detail="Not found")


@app.post("/api/internal/release-bootstrap", include_in_schema=False)
def release_bootstrap(request: Request):
    """Apply idempotent release bootstrap inside an authenticated staged deployment."""
    _authorize_release_bootstrap(request)
    apply_startup_bootstrap()
    return {
        "status": "ok",
        "runtime_bootstrap": "applied",
        "release_git_sha": os.getenv("RELEASE_GIT_SHA", "").strip(),
    }
