from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response


COOKIE_NAME = "science_student_session"
SESSION_MAX_AGE = 12 * 60 * 60


@dataclass(frozen=True)
class StudentSession:
    student_id: int
    external_code: str
    issued_at: int


def _production() -> bool:
    return bool(os.getenv("VERCEL")) or os.getenv("VERCEL_ENV") == "production"


def _secret() -> bytes:
    """Return a stable signing key without exposing or storing student codes client-side."""
    seed = (
        os.getenv("STUDENT_SESSION_SECRET", "").strip()
        or os.getenv("ADMIN_SESSION_SECRET", "").strip()
        or os.getenv("ADMIN_API_KEY", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not seed:
        raise HTTPException(
            status_code=503,
            detail="Student session signing is not configured",
        )
    return hashlib.sha256(("science-student:" + seed).encode("utf-8")).digest()


def _encode_code(code: str) -> str:
    return base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_code(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def make_student_session_token(student_id: int, external_code: str) -> str:
    issued = int(time.time())
    nonce = secrets.token_urlsafe(16)
    encoded = _encode_code(external_code)
    body = f"{int(student_id)}.{issued}.{nonce}.{encoded}"
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_student_session_token(token: str) -> StudentSession | None:
    try:
        student_id_s, issued_s, nonce, encoded, sig = token.split(".", 4)
        student_id = int(student_id_s)
        issued = int(issued_s)
        if not nonce or student_id < 1:
            return None
        now = int(time.time())
        if issued > now + 60 or now - issued > SESSION_MAX_AGE:
            return None
        body = f"{student_id}.{issued}.{nonce}.{encoded}"
        expected = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        code = _decode_code(encoded)
        if not code:
            return None
        return StudentSession(
            student_id=student_id,
            external_code=code,
            issued_at=issued,
        )
    except (TypeError, ValueError, UnicodeError, base64.binascii.Error, HTTPException):
        return None


def student_session(request: Request) -> StudentSession | None:
    token = request.cookies.get(COOKIE_NAME, "")
    return parse_student_session_token(token) if token else None


def set_student_session_cookie(
    response: Response,
    *,
    student_id: int,
    external_code: str,
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_student_session_token(student_id, external_code),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_production(),
        samesite="lax",
        path="/",
    )


def clear_student_session_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_production(),
        samesite="lax",
    )


def legacy_student_code_allowed() -> bool:
    raw = os.getenv("ALLOW_LEGACY_STUDENT_CODE_AUTH", "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    return not _production()


def resolve_student_code(
    request: Request,
    supplied_code: str | None = None,
) -> str:
    """Resolve the authenticated student, rejecting cross-student code mixing."""
    session = student_session(request)
    supplied = (supplied_code or "").strip()

    if session:
        if supplied and not hmac.compare_digest(supplied, session.external_code):
            raise HTTPException(
                403,
                "كود الطالب لا يطابق الجلسة الحالية",
            )
        return session.external_code

    if supplied and legacy_student_code_allowed():
        return supplied

    raise HTTPException(
        401,
        "سجّل الدخول بكود الطالب أولًا لإنشاء جلسة آمنة",
    )
