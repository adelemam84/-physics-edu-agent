from __future__ import annotations

from . import __init__  # noqa: F401
from ..db import connect


ACTIVE_STATUSES = {"open", "acknowledged", "monitoring"}
ALL_STATUSES = ACTIVE_STATUSES | {"resolved"}
ALLOWED_TRANSITIONS = {
    "open": {"acknowledged", "monitoring", "resolved"},
    "acknowledged": {"monitoring", "resolved"},
    "monitoring": {"acknowledged", "resolved"},
    "resolved": set(),
}


def ensure_intervention_case_schema() -> None:
    """Create the human intervention case/audit tables idempotently at startup."""
    with connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS student_intervention_cases(
              id bigserial PRIMARY KEY,
              student_id bigint NOT NULL REFERENCES students(id) ON DELETE CASCADE,
              status text NOT NULL DEFAULT 'open',
              priority_snapshot text NOT NULL,
              risk_score_snapshot integer NOT NULL,
              reasons_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
              recommended_action text NOT NULL,
              owner_note text,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              resolved_at timestamptz,
              CONSTRAINT intervention_case_status_check
                CHECK (status IN ('open','acknowledged','monitoring','resolved')),
              CONSTRAINT intervention_case_priority_check
                CHECK (priority_snapshot IN ('high','baseline','medium','low')),
              CONSTRAINT intervention_case_score_check
                CHECK (risk_score_snapshot>=0 AND risk_score_snapshot<=100)
            )"""
        )
        con.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_intervention_case_student
               ON student_intervention_cases(student_id)
               WHERE status IN ('open','acknowledged','monitoring')"""
        )
        con.execute(
            """CREATE INDEX IF NOT EXISTS idx_intervention_cases_status_updated
               ON student_intervention_cases(status,updated_at DESC)"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS student_intervention_case_events(
              id bigserial PRIMARY KEY,
              case_id bigint NOT NULL REFERENCES student_intervention_cases(id) ON DELETE CASCADE,
              action text NOT NULL,
              from_status text,
              to_status text,
              note text,
              actor text NOT NULL DEFAULT 'admin_session',
              created_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        con.execute(
            """CREATE INDEX IF NOT EXISTS idx_intervention_case_events_case_created
               ON student_intervention_case_events(case_id,created_at DESC)"""
        )


def list_cases(status: str | None = None, limit: int = 100) -> list[dict]:
    limit = min(max(int(limit), 1), 300)
    where = ""
    params: list[object] = []
    if status:
        if status not in ALL_STATUSES:
            raise ValueError("invalid_status")
        where = "WHERE c.status=%s"
        params.append(status)
    params.append(limit)
    with connect() as con:
        return list(
            con.execute(
                f"""SELECT c.*,s.name student_name,
                   (SELECT count(*) FROM student_intervention_case_events e WHERE e.case_id=c.id) event_count
                   FROM student_intervention_cases c
                   JOIN students s ON s.id=c.student_id
                   {where}
                   ORDER BY CASE c.status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1
                            WHEN 'monitoring' THEN 2 ELSE 3 END,
                            c.updated_at DESC,c.id DESC LIMIT %s""",
                params,
            ).fetchall()
        )


def case_detail(case_id: int) -> dict | None:
    with connect() as con:
        case = con.execute(
            """SELECT c.*,s.name student_name FROM student_intervention_cases c
               JOIN students s ON s.id=c.student_id WHERE c.id=%s""",
            (case_id,),
        ).fetchone()
        if not case:
            return None
        events = list(
            con.execute(
                """SELECT id,action,from_status,to_status,note,actor,created_at
                   FROM student_intervention_case_events
                   WHERE case_id=%s ORDER BY created_at,id""",
                (case_id,),
            ).fetchall()
        )
    return {"case": dict(case), "events": events}


def open_case(*, student_id: int, priority: str, risk_score: int,
              reasons: list[str], recommended_action: str, note: str | None = None) -> dict:
    if priority not in {"high", "baseline", "medium", "low"}:
        raise ValueError("invalid_priority")
    risk_score = min(max(int(risk_score), 0), 100)
    clean_note = (note or "").strip() or None
    with connect() as con:
        existing = con.execute(
            """SELECT * FROM student_intervention_cases
               WHERE student_id=%s AND status IN ('open','acknowledged','monitoring')
               ORDER BY id DESC LIMIT 1""",
            (student_id,),
        ).fetchone()
        if existing:
            return {"case": dict(existing), "created": False}
        if not con.execute("SELECT 1 FROM students WHERE id=%s", (student_id,)).fetchone():
            raise LookupError("student_not_found")
        row = con.execute(
            """INSERT INTO student_intervention_cases(
                 student_id,status,priority_snapshot,risk_score_snapshot,
                 reasons_snapshot,recommended_action,owner_note
               ) VALUES(%s,'open',%s,%s,%s::jsonb,%s,%s) RETURNING *""",
            (student_id, priority, risk_score, __import__('json').dumps(reasons, ensure_ascii=False),
             recommended_action, clean_note),
        ).fetchone()
        con.execute(
            """INSERT INTO student_intervention_case_events(case_id,action,to_status,note)
               VALUES(%s,'opened','open',%s)""",
            (row["id"], clean_note),
        )
    return {"case": dict(row), "created": True}


def transition_case(case_id: int, *, status: str, note: str | None = None) -> dict:
    if status not in ALL_STATUSES:
        raise ValueError("invalid_status")
    clean_note = (note or "").strip() or None
    with connect() as con:
        current = con.execute(
            "SELECT * FROM student_intervention_cases WHERE id=%s FOR UPDATE",
            (case_id,),
        ).fetchone()
        if not current:
            raise LookupError("case_not_found")
        old = current["status"]
        if status == old:
            if clean_note:
                row = con.execute(
                    """UPDATE student_intervention_cases SET owner_note=%s,updated_at=now()
                       WHERE id=%s RETURNING *""",
                    (clean_note, case_id),
                ).fetchone()
                con.execute(
                    """INSERT INTO student_intervention_case_events(case_id,action,from_status,to_status,note)
                       VALUES(%s,'note',%s,%s,%s)""",
                    (case_id, old, old, clean_note),
                )
                return dict(row)
            return dict(current)
        if status not in ALLOWED_TRANSITIONS.get(old, set()):
            raise RuntimeError("invalid_transition")
        row = con.execute(
            """UPDATE student_intervention_cases
               SET status=%s,owner_note=coalesce(%s,owner_note),updated_at=now(),
                   resolved_at=CASE WHEN %s='resolved' THEN now() ELSE NULL END
               WHERE id=%s RETURNING *""",
            (status, clean_note, status, case_id),
        ).fetchone()
        con.execute(
            """INSERT INTO student_intervention_case_events(case_id,action,from_status,to_status,note)
               VALUES(%s,'status_changed',%s,%s,%s)""",
            (case_id, old, status, clean_note),
        )
    return dict(row)
