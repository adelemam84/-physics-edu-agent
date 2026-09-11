from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin
from .teacher_intervention_queue import build_intervention_queue


InterventionStatus = Literal["open", "planned", "done", "dismissed"]
InterventionType = Literal[
    "baseline_assessment",
    "reengage_student",
    "adaptive_practice",
    "mistake_review",
    "monitor",
    "custom",
]


class InterventionCreate(BaseModel):
    student_id: int = Field(gt=0)
    intervention_type: InterventionType
    note: str | None = Field(default=None, max_length=3000)
    planned_for: datetime | None = None


class InterventionPatch(BaseModel):
    status: InterventionStatus | None = None
    note: str | None = Field(default=None, max_length=3000)
    outcome_note: str | None = Field(default=None, max_length=3000)
    planned_for: datetime | None = None


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"open", "planned", "done", "dismissed"},
    "planned": {"open", "planned", "done", "dismissed"},
    "done": {"done"},
    "dismissed": {"dismissed"},
}


def validate_transition(current: str, target: str) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            409,
            {
                "message": "لا يمكن تنفيذ هذا الانتقال في حالة التدخل الحالية.",
                "current": current,
                "target": target,
            },
        )


def normalized_patch_values(payload: InterventionPatch) -> dict:
    """Normalize PATCH semantics so explicit null status means no status change."""
    values = payload.model_dump(exclude_unset=True)
    if values.get("status") is None:
        values.pop("status", None)
    return values


def _schema() -> None:
    with connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS teacher_interventions(
              id bigserial PRIMARY KEY,
              student_id bigint NOT NULL REFERENCES students(id) ON DELETE CASCADE,
              intervention_type text NOT NULL,
              status text NOT NULL DEFAULT 'open',
              note text,
              planned_for timestamptz,
              pre_risk_score integer,
              pre_priority text,
              post_risk_score integer,
              post_priority text,
              outcome_note text,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              completed_at timestamptz,
              CONSTRAINT teacher_interventions_status_check
                CHECK(status IN ('open','planned','done','dismissed')),
              CONSTRAINT teacher_interventions_type_check
                CHECK(intervention_type IN (
                  'baseline_assessment','reengage_student','adaptive_practice',
                  'mistake_review','monitor','custom'
                )),
              CONSTRAINT teacher_interventions_pre_risk_check
                CHECK(pre_risk_score IS NULL OR (pre_risk_score>=0 AND pre_risk_score<=100)),
              CONSTRAINT teacher_interventions_post_risk_check
                CHECK(post_risk_score IS NULL OR (post_risk_score>=0 AND post_risk_score<=100))
            )"""
        )
        con.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_teacher_interventions_active_student
               ON teacher_interventions(student_id)
               WHERE status IN ('open','planned')"""
        )
        con.execute(
            """CREATE INDEX IF NOT EXISTS idx_teacher_interventions_status_updated
               ON teacher_interventions(status,updated_at DESC)"""
        )


def _risk_for_student(student_id: int) -> dict | None:
    data = build_intervention_queue(limit=300)
    return next((x for x in data["items"] if int(x["student_id"]) == int(student_id)), None)


def _case_rows(status: str | None = None, limit: int = 100) -> list[dict]:
    _schema()
    limit = min(max(int(limit), 1), 300)
    where = ""
    params: list[object] = []
    if status:
        if status not in {"open", "planned", "done", "dismissed"}:
            raise HTTPException(400, "Invalid status")
        where = "WHERE i.status=%s"
        params.append(status)
    params.append(limit)
    with connect() as con:
        rows = list(
            con.execute(
                f"""SELECT i.id,i.student_id,s.name student_name,i.intervention_type,i.status,
                      i.note,i.planned_for,i.pre_risk_score,i.pre_priority,
                      i.post_risk_score,i.post_priority,i.outcome_note,
                      i.created_at,i.updated_at,i.completed_at
                   FROM teacher_interventions i
                   JOIN students s ON s.id=i.student_id
                   {where}
                   ORDER BY CASE i.status WHEN 'open' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
                            i.updated_at DESC,i.id DESC
                   LIMIT %s""",
                params,
            ).fetchall()
        )
    return [dict(x) for x in rows]


@app.get("/api/admin/interventions", dependencies=[Depends(require_admin)])
def list_interventions(status: str | None = None, limit: int = 100):
    rows = _case_rows(status=status, limit=limit)
    return {
        "count": len(rows),
        "items": rows,
        "policy": {
            "risk_engine": "deterministic_rules",
            "teacher_decision_final": True,
            "automatic_messaging": False,
            "llm_intervention_decisions": False,
        },
    }


@app.post("/api/admin/interventions", dependencies=[Depends(require_admin)])
def create_intervention(payload: InterventionCreate):
    _schema()
    risk = _risk_for_student(payload.student_id)
    if not risk:
        raise HTTPException(404, "الطالب غير موجود في قائمة المتابعة")
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s", (payload.student_id,)).fetchone():
            raise HTTPException(404, "الطالب غير موجود")
        active = con.execute(
            """SELECT id,status FROM teacher_interventions
               WHERE student_id=%s AND status IN ('open','planned') LIMIT 1""",
            (payload.student_id,),
        ).fetchone()
        if active:
            raise HTTPException(
                409,
                {
                    "message": "يوجد تدخل مفتوح بالفعل لهذا الطالب.",
                    "intervention_id": active["id"],
                    "status": active["status"],
                },
            )
        row = con.execute(
            """INSERT INTO teacher_interventions(
                 student_id,intervention_type,status,note,planned_for,
                 pre_risk_score,pre_priority
               ) VALUES(%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                payload.student_id,
                payload.intervention_type,
                "planned" if payload.planned_for else "open",
                payload.note,
                payload.planned_for,
                int(risk["score"]),
                str(risk["priority"]),
            ),
        ).fetchone()
    return {
        **dict(row),
        "risk_reasons_at_open": risk.get("reasons") or [],
        "automatic_message_sent": False,
    }


@app.patch("/api/admin/interventions/{intervention_id}", dependencies=[Depends(require_admin)])
def update_intervention(intervention_id: int, payload: InterventionPatch):
    _schema()
    values = normalized_patch_values(payload)
    if not values:
        raise HTTPException(400, "No changes")
    with connect() as con:
        current = con.execute(
            "SELECT * FROM teacher_interventions WHERE id=%s", (intervention_id,)
        ).fetchone()
    if not current:
        raise HTTPException(404, "حالة التدخل غير موجودة")

    target = str(values.get("status") or current["status"])
    validate_transition(str(current["status"]), target)
    risk = _risk_for_student(int(current["student_id"])) if target == "done" else None

    setters: list[str] = ["updated_at=now()"]
    params: list[object] = []
    for key in ("status", "note", "outcome_note", "planned_for"):
        if key in values:
            setters.append(f"{key}=%s")
            params.append(values[key])
    if target == "done" and str(current["status"]) != "done":
        setters.extend(["completed_at=now()", "post_risk_score=%s", "post_priority=%s"])
        params.extend([
            int(risk["score"]) if risk else None,
            str(risk["priority"]) if risk else None,
        ])
    params.append(intervention_id)
    with connect() as con:
        row = con.execute(
            f"UPDATE teacher_interventions SET {', '.join(setters)} WHERE id=%s RETURNING *",
            params,
        ).fetchone()
    return dict(row)


@app.get("/api/admin/interventions/summary", dependencies=[Depends(require_admin)])
def intervention_summary():
    _schema()
    with connect() as con:
        row = con.execute(
            """SELECT count(*) total,
              count(*) FILTER(WHERE status='open') open,
              count(*) FILTER(WHERE status='planned') planned,
              count(*) FILTER(WHERE status='done') done,
              count(*) FILTER(WHERE status='dismissed') dismissed,
              count(*) FILTER(
                WHERE status='done' AND pre_risk_score IS NOT NULL AND post_risk_score IS NOT NULL
                  AND post_risk_score < pre_risk_score
              ) improved,
              round(avg(pre_risk_score-post_risk_score) FILTER(
                WHERE status='done' AND pre_risk_score IS NOT NULL AND post_risk_score IS NOT NULL
              ),1) average_risk_reduction
              FROM teacher_interventions"""
        ).fetchone()
    return dict(row or {})
