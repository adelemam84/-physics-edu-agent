from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from .db import connect


COOKIE_NAME = "science_student_session"
SESSION_MAX_AGE = 12 * 60 * 60


@dataclass(frozen=True)
class StudentSession:
    student_id: int
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


def make_student_session_token(student_id: int) -> str:
    """Create an opaque signed session token that never embeds the login code."""
    issued = int(time.time())
    nonce = secrets.token_urlsafe(24)
    body = f"v2.{int(student_id)}.{issued}.{nonce}"
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_student_session_token(token: str) -> StudentSession | None:
    try:
        version, student_id_s, issued_s, nonce, sig = token.split(".", 4)
        if version != "v2":
            return None
        student_id = int(student_id_s)
        issued = int(issued_s)
        if not nonce or student_id < 1:
            return None
        now = int(time.time())
        if issued > now + 60 or now - issued > SESSION_MAX_AGE:
            return None
        body = f"v2.{student_id}.{issued}.{nonce}"
        expected = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return StudentSession(student_id=student_id, issued_at=issued)
    except (TypeError, ValueError, HTTPException):
        return None

def student_session(request: Request) -> StudentSession | None:
    token = request.cookies.get(COOKIE_NAME, "")
    return parse_student_session_token(token) if token else None


def set_student_session_cookie(
    response: Response,
    *,
    student_id: int,
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_student_session_token(student_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_production(),
        samesite="strict",
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


def resolve_student_id(request: Request) -> int:
    """Resolve the authenticated student id exclusively from the signed session."""
    session = student_session(request)
    if session:
        return session.student_id
    raise HTTPException(
        401,
        "سجّل الدخول بكود الطالب أولًا لإنشاء جلسة آمنة",
    )


def resolve_student_code(request: Request) -> str:
    """Backward-compatible resolver without storing the login code in the cookie."""
    student_id = resolve_student_id(request)
    with connect() as con:
        row = con.execute(
            "SELECT external_code FROM students WHERE id=%s",
            (student_id,),
        ).fetchone()
    if not row or not row.get("external_code"):
        raise HTTPException(401, "جلسة الطالب لم تعد صالحة")
    return str(row["external_code"])
