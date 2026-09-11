from __future__ import annotations

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .student_security import (
    SESSION_MAX_AGE,
    clear_student_session_cookie,
    set_student_session_cookie,
    student_session,
)


class StudentSessionLogin(BaseModel):
    student_code: str = Field(min_length=1, max_length=128)


@app.post("/api/student/session")
def create_student_session(payload: StudentSessionLogin, response: Response):
    code = payload.student_code.strip()
    if not code:
        raise HTTPException(400, "أدخل كود الطالب")
    with connect() as con:
        student = con.execute(
            "SELECT id,name,external_code FROM students WHERE external_code=%s",
            (code,),
        ).fetchone()
    if not student:
        raise HTTPException(404, "كود الطالب غير صحيح")
    set_student_session_cookie(
        response,
        student_id=student["id"],
        external_code=student["external_code"],
    )
    return {
        "authenticated": True,
        "student": {
            "id": student["id"],
            "name": student["name"],
        },
        "expires_in": SESSION_MAX_AGE,
    }


@app.get("/api/student/session")
def read_student_session(request: Request):
    session = student_session(request)
    if not session:
        return {"authenticated": False}
    with connect() as con:
        student = con.execute(
            "SELECT id,name FROM students WHERE id=%s AND external_code=%s",
            (session.student_id, session.external_code),
        ).fetchone()
    if not student:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "student": dict(student),
        "expires_in": max(0, SESSION_MAX_AGE),
    }


@app.delete("/api/student/session")
def delete_student_session(response: Response):
    clear_student_session_cookie(response)
    return {"authenticated": False}
