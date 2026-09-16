from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import HTTPException

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def lesson_pack_ingestion_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Control Lesson Pack uploads independently from official curriculum ingestion.

    This auxiliary workspace is intentionally separate from CONTENT_INGESTION_ENABLED.
    It is enabled by default because it never writes generated questions into the
    official question bank and every final export remains teacher-gated.
    """
    source = env if env is not None else os.environ
    explicit = str(source.get("LESSON_PACK_INGESTION_ENABLED") or "").strip().lower()
    if explicit in _TRUE:
        return True
    if explicit in _FALSE:
        return False
    return True


def require_lesson_pack_ingestion_enabled() -> None:
    if lesson_pack_ingestion_enabled():
        return
    raise HTTPException(
        status_code=423,
        detail={
            "code": "lesson_pack_ingestion_disabled",
            "message": "Lesson Pack Studio uploads are currently disabled.",
            "enable_with": "LESSON_PACK_INGESTION_ENABLED=true",
        },
    )
