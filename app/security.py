import os
from fastapi import Header, HTTPException


def admin_configured() -> bool:
    return bool(os.getenv("ADMIN_API_KEY", "").strip())


def require_admin(x_admin_key: str | None = Header(default=None)):
    expected = os.getenv("ADMIN_API_KEY", "").strip()
    if not expected:
        if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") == "production":
            raise HTTPException(status_code=503, detail="Admin writes are disabled until ADMIN_API_KEY is configured")
        return True
    if not x_admin_key or x_admin_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin key")
    return True
