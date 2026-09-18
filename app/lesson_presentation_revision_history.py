from __future__ import annotations

import json

from fastapi import Body, Depends, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from . import lesson_presentation_studio

_MAX_REVISIONS = 30
_MAX_LABEL = 120


def _clean_label(value: object) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text[:_MAX_LABEL] or None


def _validated_editor_payload(job_id: str, payload: dict) -> tuple[dict, dict, str, str]:
    edited = payload.get("edited_blueprint")
    if not isinstance(edited, dict):
        raise HTTPException(422, "edited_blueprint is required")
    base, _ = lesson_presentation_studio._presentation_editor_base(job_id, payload)
    supplied_base_hash = str(payload.get("editor_base_hash") or "") or None
    report = lesson_presentation_studio.validate_presentation_edits(
        base,
        edited,
        supplied_base_hash=supplied_base_hash,
    )
    if not report.get("ready"):
        raise HTTPException(
            409,
            {"message": "Presentation draft validation failed", "preflight": report},
        )
    current_slide = payload.get("current_slide", 0)
    try:
        current_slide = int(current_slide)
    except (TypeError, ValueError):
        current_slide = 0
    slide_count = len(edited.get("slides") or [])
    current_slide = max(0, min(current_slide, max(0, slide_count - 1)))
    return (
        edited,
        report,
        str(report.get("base_hash") or ""),
        str(report.get("edit_digest") or ""),
    )


def _prune_revisions(con, job_id: str) -> None:
    con.execute(
        """DELETE FROM lesson_presentation_revisions
           WHERE job_id=%s
             AND id NOT IN (
               SELECT id FROM lesson_presentation_revisions
               WHERE job_id=%s
               ORDER BY created_at DESC,id DESC
               LIMIT %s
             )""",
        (job_id, job_id, _MAX_REVISIONS),
    )


def _revision_row(job_id: str, revision_id: int) -> dict:
    with connect() as con:
        row = con.execute(
            """SELECT id,job_id,base_hash,edit_digest,blueprint_json,current_slide,
                      action,label,created_at
               FROM lesson_presentation_revisions
               WHERE job_id=%s AND id=%s""",
            (job_id, revision_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Presentation revision not found")
    return dict(row)


def _current_base_hash_for_blueprint(job_id: str, blueprint: dict) -> str:
    request = blueprint.get("request")
    if not isinstance(request, dict):
        raise HTTPException(409, "Stored presentation revision has no valid request")
    base, _ = lesson_presentation_studio._presentation_base(job_id, request)
    return lesson_presentation_studio.presentation_editor_base_hash(base)


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/draft",
    dependencies=[Depends(require_admin)],
)
def get_lesson_presentation_draft(job_id: str):
    with connect() as con:
        row = con.execute(
            """SELECT job_id,base_hash,edit_digest,blueprint_json,current_slide,updated_at
               FROM lesson_presentation_drafts WHERE job_id=%s""",
            (job_id,),
        ).fetchone()
    if not row:
        return {
            "exists": False,
            "official_question_bank_write": False,
            "content_ingestion_unchanged": True,
        }
    item = dict(row)
    blueprint = dict(item.get("blueprint_json") or {})
    current_hash = _current_base_hash_for_blueprint(job_id, blueprint)
    stale = current_hash != str(item.get("base_hash") or "")
    return {
        "exists": True,
        "stale": stale,
        "base_hash": item.get("base_hash"),
        "edit_digest": item.get("edit_digest"),
        "current_slide": item.get("current_slide"),
        "updated_at": item.get("updated_at"),
        "blueprint": None if stale else blueprint,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.put(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/draft",
    dependencies=[Depends(require_admin)],
)
def save_lesson_presentation_draft(job_id: str, payload: dict = Body(...)):
    edited, report, base_hash, edit_digest = _validated_editor_payload(job_id, payload)
    current_slide = max(
        0,
        min(
            int(payload.get("current_slide") or 0),
            max(0, len(edited.get("slides") or []) - 1),
        ),
    )
    with connect() as con:
        con.execute(
            """INSERT INTO lesson_presentation_drafts(
                 job_id,base_hash,edit_digest,blueprint_json,current_slide,updated_at
               ) VALUES (%s,%s,%s,%s::jsonb,%s,now())
               ON CONFLICT (job_id) DO UPDATE SET
                 base_hash=excluded.base_hash,
                 edit_digest=excluded.edit_digest,
                 blueprint_json=excluded.blueprint_json,
                 current_slide=excluded.current_slide,
                 updated_at=now()""",
            (
                job_id,
                base_hash,
                edit_digest,
                json.dumps(edited, ensure_ascii=False),
                current_slide,
            ),
        )
    return {
        "saved": True,
        "base_hash": base_hash,
        "edit_digest": edit_digest,
        "current_slide": current_slide,
        "changed": bool(report.get("changed")),
        "teacher_reapproval_required": bool(report.get("teacher_reapproval_required")),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.delete(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/draft",
    dependencies=[Depends(require_admin)],
)
def delete_lesson_presentation_draft(job_id: str):
    with connect() as con:
        row = con.execute(
            "DELETE FROM lesson_presentation_drafts WHERE job_id=%s RETURNING job_id",
            (job_id,),
        ).fetchone()
    return {
        "deleted": bool(row),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions",
    dependencies=[Depends(require_admin)],
)
def list_lesson_presentation_revisions(job_id: str):
    with connect() as con:
        rows = list(
            con.execute(
                """SELECT id,base_hash,edit_digest,current_slide,action,label,created_at
                   FROM lesson_presentation_revisions
                   WHERE job_id=%s
                   ORDER BY created_at DESC,id DESC
                   LIMIT %s""",
                (job_id, _MAX_REVISIONS),
            ).fetchall()
        )
    return {
        "revisions": [dict(row) for row in rows],
        "max_revisions": _MAX_REVISIONS,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions",
    dependencies=[Depends(require_admin)],
)
def create_lesson_presentation_revision(job_id: str, payload: dict = Body(...)):
    edited, report, base_hash, edit_digest = _validated_editor_payload(job_id, payload)
    current_slide = max(
        0,
        min(
            int(payload.get("current_slide") or 0),
            max(0, len(edited.get("slides") or []) - 1),
        ),
    )
    label = _clean_label(payload.get("label"))
    with connect() as con:
        existing = con.execute(
            """SELECT id FROM lesson_presentation_revisions
               WHERE job_id=%s AND edit_digest=%s
               ORDER BY created_at DESC,id DESC LIMIT 1""",
            (job_id, edit_digest),
        ).fetchone()
        if existing:
            revision_id = int(existing["id"])
            created = False
        else:
            row = con.execute(
                """INSERT INTO lesson_presentation_revisions(
                     job_id,base_hash,edit_digest,blueprint_json,current_slide,action,label
                   ) VALUES (%s,%s,%s,%s::jsonb,%s,'checkpoint',%s)
                   RETURNING id""",
                (
                    job_id,
                    base_hash,
                    edit_digest,
                    json.dumps(edited, ensure_ascii=False),
                    current_slide,
                    label,
                ),
            ).fetchone()
            revision_id = int(row["id"])
            created = True
            _prune_revisions(con, job_id)
    return {
        "created": created,
        "revision_id": revision_id,
        "edit_digest": edit_digest,
        "changed": bool(report.get("changed")),
        "teacher_reapproval_required": bool(report.get("teacher_reapproval_required")),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions/{revision_id}",
    dependencies=[Depends(require_admin)],
)
def get_lesson_presentation_revision(job_id: str, revision_id: int):
    item = _revision_row(job_id, revision_id)
    blueprint = dict(item.get("blueprint_json") or {})
    current_hash = _current_base_hash_for_blueprint(job_id, blueprint)
    stale = current_hash != str(item.get("base_hash") or "")
    return {
        "revision_id": item["id"],
        "base_hash": item["base_hash"],
        "edit_digest": item["edit_digest"],
        "current_slide": item["current_slide"],
        "action": item["action"],
        "label": item["label"],
        "created_at": item["created_at"],
        "stale": stale,
        "blueprint": None if stale else blueprint,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions/{revision_id}/restore",
    dependencies=[Depends(require_admin)],
)
def restore_lesson_presentation_revision(job_id: str, revision_id: int):
    item = _revision_row(job_id, revision_id)
    blueprint = dict(item.get("blueprint_json") or {})
    request = blueprint.get("request")
    if not isinstance(request, dict):
        raise HTTPException(409, "Stored presentation revision has no valid request")
    base, _ = lesson_presentation_studio._presentation_base(job_id, request)
    current_base_hash = lesson_presentation_studio.presentation_editor_base_hash(base)
    if current_base_hash != str(item.get("base_hash") or ""):
        raise HTTPException(
            409,
            {
                "message": "Presentation revision belongs to a stale source blueprint",
                "code": "stale_revision_base",
            },
        )
    report = lesson_presentation_studio.validate_presentation_edits(
        base,
        blueprint,
        supplied_base_hash=current_base_hash,
    )
    if not report.get("ready"):
        raise HTTPException(
            409,
            {"message": "Presentation revision no longer passes validation", "preflight": report},
        )
    with connect() as con:
        con.execute(
            """INSERT INTO lesson_presentation_drafts(
                 job_id,base_hash,edit_digest,blueprint_json,current_slide,updated_at
               ) VALUES (%s,%s,%s,%s::jsonb,%s,now())
               ON CONFLICT (job_id) DO UPDATE SET
                 base_hash=excluded.base_hash,
                 edit_digest=excluded.edit_digest,
                 blueprint_json=excluded.blueprint_json,
                 current_slide=excluded.current_slide,
                 updated_at=now()""",
            (
                job_id,
                current_base_hash,
                report.get("edit_digest"),
                json.dumps(blueprint, ensure_ascii=False),
                int(item.get("current_slide") or 0),
            ),
        )
        con.execute(
            """INSERT INTO lesson_presentation_revisions(
                 job_id,base_hash,edit_digest,blueprint_json,current_slide,action,label
               ) VALUES (%s,%s,%s,%s::jsonb,%s,'restore',%s)""",
            (
                job_id,
                current_base_hash,
                report.get("edit_digest"),
                json.dumps(blueprint, ensure_ascii=False),
                int(item.get("current_slide") or 0),
                _clean_label(f"Restore revision {revision_id}"),
            ),
        )
        _prune_revisions(con, job_id)
    return {
        "restored": True,
        "revision_id": revision_id,
        "base_hash": current_base_hash,
        "edit_digest": report.get("edit_digest"),
        "current_slide": int(item.get("current_slide") or 0),
        "blueprint": blueprint,
        "teacher_reapproval_required": bool(report.get("changed")),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }
