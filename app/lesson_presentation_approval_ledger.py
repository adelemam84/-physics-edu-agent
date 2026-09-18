from __future__ import annotations

from fastapi import Body, Depends, HTTPException

from . import lesson_presentation_studio
from .main import app
from .security import require_admin
from .services.lesson_presentation_approval import (
    active_approval,
    list_approvals,
    record_approval,
    revoke_approval,
)
from .services.lesson_presentation_editor import presentation_edit_digest, presentation_editor_base_hash


def _approval_context(job_id: str, payload: dict) -> tuple[dict, dict]:
    edited = payload.get("edited_blueprint")
    if edited is None:
        base, _ = lesson_presentation_studio._presentation_base(job_id, payload)
        base_hash = presentation_editor_base_hash(base)
        return base, {
            "ready": True,
            "changed": False,
            "base_hash": base_hash,
            "edit_digest": presentation_edit_digest(base_hash, base),
            "prepared_blueprint": base,
        }

    base, _ = lesson_presentation_studio._presentation_editor_base(job_id, payload)
    report = lesson_presentation_studio.validate_presentation_edits(
        base,
        edited,
        supplied_base_hash=str(payload.get("editor_base_hash") or "") or None,
    )
    if not report.get("ready"):
        raise HTTPException(
            409,
            {"message": "Presentation approval preflight failed", "preflight": report},
        )
    if report.get("changed"):
        supplied_digest = str(payload.get("validation_digest") or "")
        expected = str(report.get("edit_digest") or "")
        if not supplied_digest or supplied_digest != expected:
            raise HTTPException(
                409,
                {
                    "message": "Run the latest editor preflight before approval",
                    "code": "editor_validation_required",
                },
            )
    return report["prepared_blueprint"], report


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approval-state",
    dependencies=[Depends(require_admin)],
)
def presentation_approval_state(job_id: str, payload: dict = Body(default_factory=dict)):
    _, report = _approval_context(job_id, payload)
    approval = active_approval(
        job_id,
        str(report.get("base_hash") or ""),
        str(report.get("edit_digest") or ""),
    )
    return {
        "approved": bool(approval),
        "approval": approval,
        "base_hash": report.get("base_hash"),
        "edit_digest": report.get("edit_digest"),
        "changed": bool(report.get("changed")),
        "teacher_approval_required_for_final_export": True,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approvals",
    dependencies=[Depends(require_admin)],
)
def approve_presentation_revision(job_id: str, payload: dict = Body(...)):
    blueprint, report = _approval_context(job_id, payload)
    approval = record_approval(
        job_id,
        base_hash=str(report.get("base_hash") or ""),
        edit_digest=str(report.get("edit_digest") or ""),
        blueprint=blueprint,
        notes=payload.get("notes"),
    )
    return {
        "approved": True,
        "approval": approval,
        "base_hash": report.get("base_hash"),
        "edit_digest": report.get("edit_digest"),
        "changed": bool(report.get("changed")),
        "persistent": True,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approvals",
    dependencies=[Depends(require_admin)],
)
def presentation_approval_history(job_id: str):
    return {
        "approvals": list_approvals(job_id),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approvals/{approval_id}/revoke",
    dependencies=[Depends(require_admin)],
)
def revoke_presentation_revision_approval(
    job_id: str,
    approval_id: int,
    payload: dict = Body(default_factory=dict),
):
    item = revoke_approval(job_id, approval_id, payload.get("reason"))
    if not item:
        raise HTTPException(404, "Presentation approval not found")
    return {
        "revoked": True,
        "approval": item,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }
