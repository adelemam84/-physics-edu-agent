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
from .services.lesson_presentation_pptx import pptx_preflight, render_presentation_pptx


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
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/blueprint",
    dependencies=[Depends(require_admin)],
)
def create_lesson_presentation_blueprint(job_id: str, payload: dict = Body(default_factory=dict)):
    job, _ = lesson_pack_studio._job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before creating a presentation")
    try:
        request = normalize_request(payload)
        blueprint = build_presentation_blueprint(pack, request, source_lesson_pack_id=job_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return blueprint


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
    job, _ = lesson_pack_studio._job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before creating a presentation")
    try:
        request = normalize_request(payload)
        request["audience"] = edition
        blueprint = build_presentation_blueprint(pack, request, source_lesson_pack_id=job_id)
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
    job, _ = lesson_pack_studio._job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before creating a presentation")
    try:
        request = normalize_request(payload)
        request["audience"] = edition
        blueprint = build_presentation_blueprint(pack, request, source_lesson_pack_id=job_id)
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
        },
    )
