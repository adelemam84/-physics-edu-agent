from __future__ import annotations

from fastapi import Depends, HTTPException

from . import lesson_pack_studio
from .security import require_admin
from .services.lesson_pack_core import render_pdf as _base_render_pdf
from .services.lesson_pack_export_preflight import pack_preflight, pdf_preflight
from .services.lesson_pack_practice_layout import prepare_practice_pack
from .services.lesson_pack_student_handout_v2 import (
    render_enhanced_student_handout_pdf as render_student_handout_pdf,
)
from .services.lesson_pack_teacher_practice_appendix import append_teacher_practice_key


def _render_lesson_pack_pdf_unchecked(pack: dict, edition: str) -> bytes:
    if edition == "student":
        return render_student_handout_pdf(pack)
    render_pack = prepare_practice_pack(pack)
    base = _base_render_pdf(render_pack, edition)
    if edition == "teacher":
        return append_teacher_practice_key(base, render_pack)
    return base


def _preflight_error(report: dict, *, stage: str) -> HTTPException:
    return HTTPException(
        409,
        {
            "message": f"Lesson Pack {stage} preflight failed",
            "preflight": report,
        },
    )


def _render_lesson_pack_pdf(pack: dict, edition: str) -> bytes:
    pack_report = pack_preflight(pack)
    if not pack_report["ready"]:
        raise _preflight_error(pack_report, stage="pack")

    # Keep the Student renderer explicit here. Existing runtime contracts verify that
    # the production Student export cannot silently fall back to the generic renderer.
    if edition == "student":
        data = render_student_handout_pdf(pack)
    else:
        data = _render_lesson_pack_pdf_unchecked(pack, edition)

    pdf_report = pdf_preflight(data, pack, edition)
    if not pdf_report["ready"]:
        raise _preflight_error(pdf_report, stage=f"{edition} PDF")
    return data


@lesson_pack_studio.app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/preflight",
    dependencies=[Depends(require_admin)],
)
def lesson_pack_export_preflight(job_id: str, edition: str = "student"):
    """Return non-mutating technical and final-export readiness for one edition."""
    if edition not in {"student", "teacher"}:
        raise HTTPException(400, "edition must be student or teacher")

    job, pages = lesson_pack_studio._job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before preflight")

    teacher_approved = bool(job.get("teacher_approved"))
    pack_report = pack_preflight(pack, lesson_pack_studio.allowed_source_refs(pages))
    result = {
        "id": job_id,
        "edition": edition,
        "pack": pack_report,
        "pdf": None,
        "preflight_ready": False,
        "teacher_approved": teacher_approved,
        "export_ready": False,
        # Backward-compatible alias: `ready` remains technical preflight readiness.
        "ready": False,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }
    if not pack_report["ready"]:
        return result

    data = _render_lesson_pack_pdf_unchecked(pack, edition)
    pdf_report = pdf_preflight(data, pack, edition)
    preflight_ready = bool(pdf_report["ready"])
    result["pdf"] = pdf_report
    result["preflight_ready"] = preflight_ready
    result["ready"] = preflight_ready
    result["export_ready"] = bool(preflight_ready and teacher_approved)
    return result


# Register the enhanced printable student/teacher Lesson Pack renderers after routes
# are loaded. The route resolves render_pdf from its module globals at request time.
lesson_pack_studio.render_pdf = _render_lesson_pack_pdf
