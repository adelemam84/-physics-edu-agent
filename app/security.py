import hashlib
import hmac
import os

from fastapi import Header, HTTPException, Request

COOKIE_NAME = "science_admin_session"
SESSION_MAX_AGE = 8 * 60 * 60


def admin_configured() -> bool:
    return bool(os.getenv("ADMIN_API_KEY", "").strip())


def _expected_key() -> str:
    return os.getenv("ADMIN_API_KEY", "").strip()


def _session_secret(expected: str) -> bytes:
    configured = os.getenv("ADMIN_SESSION_SECRET", "").strip()
    seed = configured or ("science-admin:" + expected)
    return hashlib.sha256(seed.encode("utf-8")).digest()


def make_admin_session_token() -> str:
    expected = _expected_key()
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    return hmac.new(_session_secret(expected), b"authenticated", hashlib.sha256).hexdigest()


def validate_admin_key(value: str | None) -> bool:
    expected = _expected_key()
    return bool(expected and value and hmac.compare_digest(value, expected))


def admin_session_valid(request: Request) -> bool:
    expected = _expected_key()
    if not expected:
        return not (os.getenv("VERCEL") or os.getenv("VERCEL_ENV") == "production")
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        return False
    return hmac.compare_digest(token, make_admin_session_token())


def require_admin(request: Request, x_admin_key: str | None = Header(default=None)):
    expected = _expected_key()
    if not expected:
        if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") == "production":
            raise HTTPException(status_code=503, detail="Admin access is disabled until ADMIN_API_KEY is configured")
        return True
    if validate_admin_key(x_admin_key) or admin_session_valid(request):
        return True
    raise HTTPException(status_code=401, detail="Invalid or missing admin credentials")
