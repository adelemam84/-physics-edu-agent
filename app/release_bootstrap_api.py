from __future__ import annotations

import hmac
import os
import time

from fastapi import HTTPException, Request

from .main import app
from .startup_bootstrap import apply_startup_bootstrap


_LOCK_TIMEOUT_MESSAGE = "Timed out waiting for startup migration lock"


def _release_bootstrap_retry_policy() -> tuple[int, float]:
    try:
        retries = int(os.getenv("RELEASE_BOOTSTRAP_LOCK_RETRIES", "2"))
    except (TypeError, ValueError):
        retries = 2
    retries = max(0, min(retries, 3))
    try:
        delay = float(os.getenv("RELEASE_BOOTSTRAP_LOCK_RETRY_DELAY_SECONDS", "1.0"))
    except (TypeError, ValueError):
        delay = 1.0
    delay = max(0.1, min(delay, 5.0))
    return retries, delay


def _apply_release_bootstrap_with_retry() -> int:
    retries, delay = _release_bootstrap_retry_policy()
    for attempt in range(retries + 1):
        try:
            apply_startup_bootstrap()
            return attempt + 1
        except RuntimeError as exc:
            if str(exc) != _LOCK_TIMEOUT_MESSAGE or attempt >= retries:
                raise
            time.sleep(min(5.0, delay * (attempt + 1)))
    raise RuntimeError("release bootstrap retry policy exhausted")


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
    attempts = _apply_release_bootstrap_with_retry()
    return {
        "status": "ok",
        "runtime_bootstrap": "applied",
        "bootstrap_attempts": attempts,
        "release_git_sha": os.getenv("RELEASE_GIT_SHA", "").strip(),
    }
