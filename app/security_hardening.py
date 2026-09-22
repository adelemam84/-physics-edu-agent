from __future__ import annotations

import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .main import app
from .security import COOKIE_NAME as ADMIN_COOKIE_NAME, same_origin_request
from .student_security import COOKIE_NAME as STUDENT_COOKIE_NAME, student_session
from .services.rate_limit import enforce_subject_policy


_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_STUDENT_MUTATION_POLICIES: tuple[
    tuple[str, re.Pattern[str], str, int, int], ...
] = (
    ("POST", re.compile(r"^/api/student/quizzes/\d+/start$"), "student_quiz_start", 30, 3600),
    ("PUT", re.compile(r"^/api/student/attempts/\d+/answer$"), "student_answer_save", 600, 600),
    ("POST", re.compile(r"^/api/student/attempts/\d+/integrity-event$"), "student_integrity_event", 180, 600),
    ("POST", re.compile(r"^/api/student/quizzes/\d+/submit$"), "student_quiz_submit", 30, 3600),
    ("POST", re.compile(r"^/api/student/lessons/\d+/diagnostic$"), "student_diagnostic_submit", 30, 3600),
)


def student_mutation_policy(path: str, method: str) -> tuple[str, int, int] | None:
    normalized_method = str(method or "").upper()
    for expected_method, pattern, name, limit, window in _STUDENT_MUTATION_POLICIES:
        if normalized_method == expected_method and pattern.fullmatch(str(path or "")):
            return name, limit, window
    return None


def _rate_limit_response(exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers or {},
    )


@app.middleware("http")
async def enforce_browser_session_mutation_guards(request: Request, call_next):
    method = request.method.upper()
    path = request.url.path

    if method in _UNSAFE_METHODS:
        admin_cookie_present = bool(request.cookies.get(ADMIN_COOKIE_NAME))
        if path.startswith("/api/admin") and admin_cookie_present and not same_origin_request(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin admin mutation blocked"},
            )

        student_cookie_present = bool(request.cookies.get(STUDENT_COOKIE_NAME))
        if path.startswith("/api/student") and student_cookie_present:
            if not same_origin_request(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin student mutation blocked"},
                )

            session = student_session(request)
            policy = student_mutation_policy(path, method)
            if session is not None and policy is not None:
                name, limit, window_seconds = policy
                try:
                    enforce_subject_policy(
                        f"student:{session.student_id}",
                        name=name,
                        default_limit=limit,
                        default_window_seconds=window_seconds,
                    )
                except HTTPException as exc:
                    return _rate_limit_response(exc)

    return await call_next(request)
