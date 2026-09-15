from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import HTTPException


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def content_ingestion_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Keep curriculum/source intake frozen on production unless explicitly enabled."""
    source = env if env is not None else os.environ
    explicit = str(source.get("CONTENT_INGESTION_ENABLED") or "").strip().lower()
    if explicit in _TRUE:
        return True
    if explicit in _FALSE:
        return False

    # Local/test/preview environments stay usable for deterministic technical tests.
    # Production is fail-closed until the content phase is deliberately opened.
    return str(source.get("VERCEL_ENV") or "").strip().lower() != "production"


def require_content_ingestion_enabled() -> None:
    if content_ingestion_enabled():
        return
    raise HTTPException(
        status_code=423,
        detail={
            "code": "content_ingestion_deferred",
            "message": "Curriculum/source intake is intentionally locked during the pre-content technical phase.",
            "enable_with": "CONTENT_INGESTION_ENABLED=true",
        },
    )
