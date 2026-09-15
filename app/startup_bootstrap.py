from __future__ import annotations

import os
from typing import Mapping

from .db import init_db, startup_migration_lock


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def startup_bootstrap_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Keep schema/provider bootstrap off serverless request cold starts by default."""
    source = env if env is not None else os.environ
    explicit = str(source.get("STARTUP_BOOTSTRAP_ON_RUNTIME") or "").strip().lower()
    if explicit in _TRUE:
        return True
    if explicit in _FALSE:
        return False

    on_vercel = (
        str(source.get("VERCEL") or "").strip() == "1"
        or bool(str(source.get("VERCEL_ENV") or "").strip())
    )
    return not on_vercel


def apply_startup_bootstrap() -> None:
    """Apply idempotent schema work once, then bootstrap external source tooling."""
    from .services.corpus_phase2_runtime import ensure_phase2_schemas

    with startup_migration_lock():
        init_db()
        ensure_phase2_schemas(release_schema_ready=True)

    # Never hold the global schema lock while waiting on an external provider.
    from .file_search_store import bootstrap_store_if_enabled

    bootstrap_store_if_enabled()
