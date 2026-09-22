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


def admin_key_configuration_state() -> dict:
    """Return secret-free diagnostics for the configured admin key.

    This deliberately reports only presence/format and a release metadata
    revision supplied by the controlled release path. It never hashes or
    returns the secret itself.
    """
    raw = os.getenv("ADMIN_API_KEY", "")
    trimmed = raw.strip()
    issues: list[str] = []
    if raw != trimmed:
        issues.append("surrounding_whitespace")
    if trimmed.startswith("ADMIN_API_KEY="):
        issues.append("assignment_prefix")
    if (
        len(trimmed) >= 2
        and trimmed[0] == trimmed[-1]
        and trimmed[0] in {'"', "'"}
    ):
        issues.append("wrapped_quotes")

    revision = os.getenv("RELEASE_ADMIN_KEY_REVISION", "").strip() or None
    return {
        "configured": bool(trimmed),
        "format": "missing" if not trimmed else ("clean" if not issues else ",".join(issues)),
        "revision": revision,
        "contains_secret_value": False,
    }


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


def _canonical_origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(value)
        if parsed.username is not None or parsed.password is not None:
            return None
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").rstrip(".").lower()
        if scheme not in {"http", "https"} or not host:
            return None
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, int(port)


def same_origin_request(request: Request) -> bool:
    # Fetch Metadata is browser-controlled and gives an early, explicit denial for
    # cross-site mutations. Older clients may omit it, so Origin/Referer remains
    # the authoritative compatibility check.
    fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site == "cross-site":
        return False

    origin = (request.headers.get("origin") or "").strip()
    referer = (request.headers.get("referer") or "").strip()
    source = origin or referer
    if not source:
        return False

    host = (request.headers.get("host") or request.url.netloc or "").strip()
    if not host:
        return False

    scheme = str(getattr(request.url, "scheme", "") or "").strip().lower()
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        forwarded_proto = (
            request.headers.get("x-forwarded-proto") or ""
        ).split(",", 1)[0].strip().lower()
        if forwarded_proto in {"http", "https"}:
            scheme = forwarded_proto
    if scheme not in {"http", "https"}:
        return False

    source_origin = _canonical_origin(source)
    target_origin = _canonical_origin(f"{scheme}://{host}")
    return bool(source_origin and target_origin and source_origin == target_origin)

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
