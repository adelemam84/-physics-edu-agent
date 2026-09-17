from __future__ import annotations

from fastapi import Body, Depends, HTTPException
from fastapi.responses import Response

from . import lesson_pack_studio
from .main import app
from .security import require_admin
from .services.lesson_presentation_blueprint import (
    CARD_FEATURE_SPECS,
    MODES,
    AUDIENCES,
    LANGUAGES,
    LENGTHS,
    THEMES,
    build_presentation_blueprint,
    normalize_request,
    presentation_preflight,
    project_edition,
)
from .services.lesson_presentation_editor import (
    presentation_editor_base_hash,
    validate_presentation_edits,
)
from .services.lesson_presentation_pptx import pptx_preflight, render_presentation_pptx


def _presentation_base(job_id: str, payload: dict) -> tuple[dict, dict]:
    job, _ = lesson_pack_studio._job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before creating a presentation")
    try:
        request = normalize_request(payload)
        blueprint = build_presentation_blueprint(pack, request, source_lesson_pack_id=job_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return blueprint, request


def _prepared_editor_blueprint(job_id: str, payload: dict) -> tuple[dict, dict]:
    base, request = _presentation_base(job_id, payload)
    edited = payload.get("edited_blueprint")
    if edited is None:
        return base, {
            "ready": True,
            "changed": False,
            "teacher_reapproval_required": False,
            "base_hash": presentation_editor_base_hash(base),
            "edit_digest": "",
            "prepared_blueprint": base,
        }
    report = validate_presentation_edits(
        base,
        edited,
        supplied_base_hash=str(payload.get("editor_base_hash") or "") or None,
    )
    if not report.get("ready"):
        raise HTTPException(409, {"message": "Presentation editor preflight failed", "preflight": report})
    return report["prepared_blueprint"], report


@app.get(
    "/api/admin/lesson-pack-studio/presentation/feature-specs",
    dependencies=[Depends(require_admin)],
)
def lesson_presentation_feature_specs():
    return {
        "features": CARD_FEATURE_SPECS,
        "modes": sorted(MODES),
        "audiences": sorted(AUDIENCES),
        "languages": sorted(LANGUAGES),
        "lengths": {key: {"min": value[0], "max": value[1]} for key, value in LENGTHS.items()},
        "themes": sorted(THEMES),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
        "slide_editor": {
            "enabled": True,
            "reorder": True,
            "hide_show": True,
            "title_and_text": True,
            "diagram_text_and_labels": True,
            "source_grounding_immutable": True,
            "teacher_reapproval_after_edit": True,
        },
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/blueprint",
    dependencies=[Depends(require_admin)],
)
def create_lesson_presentation_blueprint(job_id: str, payload: dict = Body(default_factory=dict)):
    blueprint, _ = _presentation_base(job_id, payload)
    blueprint["editor_base_hash"] = presentation_editor_base_hash(blueprint)
    return blueprint


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/editor/preflight",
    dependencies=[Depends(require_admin)],
)
def lesson_presentation_editor_preflight(job_id: str, payload: dict = Body(...)):
    base, _ = _presentation_base(job_id, payload)
    edited = payload.get("edited_blueprint")
    if not isinstance(edited, dict):
        raise HTTPException(422, "edited_blueprint is required")
    report = validate_presentation_edits(
        base,
        edited,
        supplied_base_hash=str(payload.get("editor_base_hash") or "") or None,
    )
    public = {key: value for key, value in report.items() if key != "prepared_blueprint"}
    return public


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/edition/{edition}",
    dependencies=[Depends(require_admin)],
)
def create_lesson_presentation_edition(
    job_id: str,
    edition: str,
    payload: dict = Body(default_factory=dict),
):
    if edition not in {"student", "teacher"}:
        raise HTTPException(400, "edition must be student or teacher")
    blueprint, _ = _presentation_base(job_id, payload)
    try:
        blueprint["request"]["audience"] = edition
        projected = project_edition(blueprint, edition)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return projected


@app.post(
    "/api/admin/lesson-pack-studio/presentation/preflight",
    dependencies=[Depends(require_admin)],
)
def lesson_presentation_preflight(payload: dict = Body(...), edition: str | None = None):
    if edition is not None and edition not in {"student", "teacher"}:
        raise HTTPException(400, "edition must be student or teacher")
    report = presentation_preflight(payload, edition=edition)
    return {
        "preflight": report,
        "ready": report["ready"],
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/export-pptx/{edition}",
    dependencies=[Depends(require_admin)],
)
def export_lesson_presentation_pptx(
    job_id: str,
    edition: str,
    payload: dict = Body(default_factory=dict),
):
    if edition not in {"student", "teacher"}:
        raise HTTPException(400, "edition must be student or teacher")
    try:
        blueprint, edit_report = _prepared_editor_blueprint(job_id, payload)
        if edit_report.get("changed"):
            expected_digest = str(edit_report.get("edit_digest") or "")
            supplied_digest = str(payload.get("validation_digest") or "")
            if not supplied_digest or supplied_digest != expected_digest:
                raise HTTPException(
                    409,
                    {
                        "message": "Edited presentation must pass the latest pre-export validation",
                        "code": "editor_validation_required",
                    },
                )
            if payload.get("teacher_reapproved") is not True:
                raise HTTPException(
                    409,
                    {
                        "message": "Teacher re-approval is required after slide edits",
                        "code": "teacher_reapproval_required",
                    },
                )
            blueprint["approval_state"]["teacher_approved"] = True

        projected = project_edition(blueprint, edition)
        preflight = projected.get("preflight") or presentation_preflight(projected, edition=edition)
        if not preflight.get("ready"):
            raise HTTPException(409, {"message": "Presentation preflight failed", "preflight": preflight})
        data = render_presentation_pptx(blueprint, edition)
        pptx_report = pptx_preflight(data, len(projected.get("slides") or []))
        if not pptx_report.get("ready"):
            raise HTTPException(409, {"message": "PPTX preflight failed", "preflight": pptx_report})
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f'attachment; filename="lesson-presentation-{edition}-{job_id}.pptx"',
            "X-Presentation-Slides": str(pptx_report["slide_count"]),
            "X-Official-Question-Bank-Write": "false",
            "X-Presentation-Edited": "true" if edit_report.get("changed") else "false",
        },
    )
