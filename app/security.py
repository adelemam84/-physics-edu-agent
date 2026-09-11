import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request

COOKIE_NAME = "science_admin_session"
SESSION_MAX_AGE = 8 * 60 * 60


def admin_configured() -> bool:
    return bool(os.getenv("ADMIN_API_KEY", "").strip())


def admin_session_secret_configured() -> bool:
    """Whether browser admin sessions use a dedicated signing secret."""
    return bool(os.getenv("ADMIN_SESSION_SECRET", "").strip())


def admin_session_secret_source() -> str:
    if admin_session_secret_configured():
        return "dedicated"
    if admin_configured():
        return "admin_api_key_fallback"
    return "missing"


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
    issued = int(time.time())
    nonce = secrets.token_urlsafe(18)
    body = f"{issued}.{nonce}"
    sig = hmac.new(_session_secret(expected), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


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
    try:
        issued_s, nonce, sig = token.split(".", 2)
        issued = int(issued_s)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if issued > now + 60 or now - issued > SESSION_MAX_AGE:
        return False
    body = f"{issued}.{nonce}"
    expected_sig = hmac.new(_session_secret(expected), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected_sig)


def same_origin_request(request: Request) -> bool:
    origin=(request.headers.get("origin") or "").strip()
    referer=(request.headers.get("referer") or "").strip()
    source=origin or referer
    if not source:
        return False
    try:
        parsed=urlparse(source)
    except ValueError:
        return False
    host=(request.headers.get("host") or request.url.netloc or "").lower()
    source_host=(parsed.netloc or "").lower()
    return bool(source_host and host and source_host==host)

def require_admin(request: Request, x_admin_key: str | None = Header(default=None)):
    expected = _expected_key()
    if not expected:
        if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") == "production":
            raise HTTPException(status_code=503, detail="Admin access is disabled until ADMIN_API_KEY is configured")
        return True
    if validate_admin_key(x_admin_key):
        return True
    if admin_session_valid(request):
        if request.method.upper() in {"GET","HEAD","OPTIONS"}:
            return True
        if same_origin_request(request):
            return True
        raise HTTPException(status_code=403, detail="Cross-origin admin mutation blocked")
    raise HTTPException(status_code=401, detail="Invalid or missing admin credentials")
