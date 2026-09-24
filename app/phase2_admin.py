from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .security import require_admin
from .services.corpus_phase2_runtime import run_phase2_bootstrap
from .services.rate_limit import enforce_request_policy

router = APIRouter()


@router.post("/api/admin/phase2/bootstrap", dependencies=[Depends(require_admin)])
def admin_phase2_bootstrap(request: Request):
    """Explicit, rate-limited Phase 2 business bootstrap; never runs on cold start."""
    enforce_request_policy(
        request,
        name="admin_phase2_bootstrap",
        default_limit=2,
        default_window_seconds=3600,
    )
    result = run_phase2_bootstrap()
    return {
        **result,
        "explicit_admin_action": True,
        "automatic_cold_start_mutation": False,
    }
