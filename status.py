from __future__ import annotations

import os
import threading
import time

from fastapi import FastAPI, Response

from app.db import STORAGE_BACKEND, connect
from app.services.runtime_identity import runtime_identity

VERSION = "1.8.1"
SERVICE = "science-education-platform"
READINESS_TTL_SECONDS = 2.0

app = FastAPI(
    title="Science Education Platform Status Plane",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_readiness_lock = threading.Lock()
_readiness_cache: tuple[float, dict] | None = None


def _configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _object_storage_configured() -> bool:
    return all(
        _configured(name)
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_ENDPOINT_URL_S3",
            "AWS_REGION",
        )
    )


def _readiness_snapshot() -> dict:
    global _readiness_cache

    now = time.monotonic()
    cached = _readiness_cache
    if cached is not None and now - cached[0] < READINESS_TTL_SECONDS:
        return cached[1]

    with _readiness_lock:
        cached = _readiness_cache
        now = time.monotonic()
        if cached is not None and now - cached[0] < READINESS_TTL_SECONDS:
            return cached[1]

        db_ok = False
        try:
            with connect() as con:
                row = con.execute("SELECT 1 ok").fetchone()
                db_ok = bool(row and int(row["ok"]) == 1)
        except Exception:
            db_ok = False

        identity = runtime_identity(application_version=VERSION)
        critical_config = {
            "database": _configured("DATABASE_URL"),
            "admin_access": _configured("ADMIN_API_KEY"),
            "student_session": _configured("STUDENT_SESSION_SECRET"),
            "object_storage": _object_storage_configured(),
        }
        deployment_ok = True
        if identity.get("provider") == "vercel" and identity.get("production_environment"):
            deployment_ok = bool(identity.get("current_runtime_is_production_main"))

        ready = db_ok and all(critical_config.values()) and deployment_ok
        result = {
            "ready": ready,
            "database": db_ok,
            "critical_config": critical_config,
            "deployment_ok": deployment_ok,
        }
        _readiness_cache = (time.monotonic(), result)
        return result


@app.middleware("http")
async def status_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if os.getenv("VERCEL_ENV", "").strip().lower() == "production":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE,
        "version": VERSION,
        "storage_backend": STORAGE_BACKEND,
    }


@app.get("/health/ready")
def health_ready(response: Response):
    probe = _readiness_snapshot()
    response.headers["Cache-Control"] = "no-store"
    if not probe["ready"]:
        response.status_code = 503
    return {
        "status": "ready" if probe["ready"] else "not_ready",
        "service": SERVICE,
        "version": VERSION,
    }


@app.get("/api/research-engine/status")
def research_engine_status():
    model = os.getenv("GEMINI_RESEARCH_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    return {
        "active_secondary_provider": "gemini_source_engine",
        "configured": _configured("GEMINI_API_KEY"),
        "model": model,
        "orchestrator_active": True,
        "source_only": True,
        "auto_publish": False,
    }
