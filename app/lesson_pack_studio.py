from __future__ import annotations

import base64
import json
import os
import uuid

import fitz
from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from .db import connect
from .lesson_pack_guard import lesson_pack_ingestion_enabled, require_lesson_pack_ingestion_enabled
from .lesson_studio_second_reviewer import _openai_review, reviewer_status
from .main import app
from .science_lesson_studio import SUBJECTS, _gemini_text, _provider, _safe_filename, _verified_ocr
from .security import require_admin
from .services.lesson_pack_core import (
    allowed_source_refs,
    build_pack,
    render_pdf,
    source_ref,
    validate_pack_provenance,
)
from .services.rate_limit import enforce_request_policy
from .services.storage import delete_object, get_bytes, put_bytes, storage_configured

ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
PACK_MODES = {"balanced", "exam_revision", "concept_mastery"}
MAX_FILE_BYTES = int(os.getenv("LESSON_PACK_MAX_FILE_BYTES", str(12 * 1024 * 1024)))
MAX_FILES = int(os.getenv("LESSON_PACK_MAX_FILES", "6"))
MAX_PAGES = int(os.getenv("LESSON_PACK_MAX_PAGES", "40"))
RENDER_DPI = max(96, min(200, int(os.getenv("LESSON_PACK_RENDER_DPI", "144"))))
DEFAULT_QUESTION_COUNT = max(
    6, min(30, int(os.getenv("LESSON_PACK_DEFAULT_QUESTION_COUNT", "12")))
)
MAX_SOURCE_VISUALS = max(1, min(12, int(os.getenv("LESSON_PACK_MAX_SOURCE_VISUALS", "8"))))
PREVIEW_DPI = max(96, min(160, int(os.getenv("LESSON_PACK_PREVIEW_DPI", "120"))))
COVER_FIELDS = ("student_name", "class_label", "teacher_name", "school_name", "academic_term")


def _clean_cover_value(value: str | None) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:120]


def _lesson_pack_preview_bytes(job_id: str, edition: str) -> bytes:
    if edition not in {"student", "teacher"}:
        raise HTTPException(400, "edition must be student or teacher")
    job, pages = _job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before preview")
    provenance = validate_pack_provenance(pack, allowed_source_refs(pages))
    if not provenance.get("passed"):
        raise HTTPException(
            409,
            {
                "message": "Source provenance validation must pass before preview",
                "provenance": provenance,
            },
        )
    return _preview_stamp(render_pdf(pack, edition), edition)


def _preview_page_png(data: bytes, page_number: int) -> tuple[bytes, int]:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        total = doc.page_count
        if page_number < 1 or page_number > total:
            raise HTTPException(404, f"Preview page must be between 1 and {total}")
        matrix = fitz.Matrix(PREVIEW_DPI / 72.0, PREVIEW_DPI / 72.0)
        png = doc[page_number - 1].get_pixmap(matrix=matrix, alpha=False).tobytes("png")
        return png, total
    finally:
        doc.close()


def _normalize_visual_bbox(raw: dict) -> dict:
    box = raw.get("bbox") if isinstance(raw.get("bbox"), dict) else raw
    try:
        x = float(box.get("x", 0))
        y = float(box.get("y", 0))
        width = float(box.get("width", 0))
        height = float(box.get("height", 0))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "Invalid source-visual crop coordinates") from exc
    x = max(0.0, min(0.97, x))
    y = max(0.0, min(0.97, y))
    width = max(0.03, min(1.0 - x, width))
    height = max(0.03, min(1.0 - y, height))
    return {
        "x": round(x, 5),
        "y": round(y, 5),
        "width": round(width, 5),
        "height": round(height, 5),
    }


def _crop_page_image(page: dict, bbox: dict) -> bytes:
    data = get_bytes(page["object_key"])
    media = _media_type_for_page(page)
    filetype = {"image/png": "png", "image/webp": "webp"}.get(media, "jpeg")
    try:
        doc = fitz.open(stream=data, filetype=filetype)
    except Exception as exc:
        raise HTTPException(503, "Source page image is temporarily unavailable") from exc
    try:
        source_page = doc[0]
        rect = source_page.rect
        clip = fitz.Rect(
            rect.x0 + bbox["x"] * rect.width,
            rect.y0 + bbox["y"] * rect.height,
            rect.x0 + (bbox["x"] + bbox["width"]) * rect.width,
            rect.y0 + (bbox["y"] + bbox["height"]) * rect.height,
        )
        if clip.width < 12 or clip.height < 12:
            raise HTTPException(422, "Source-visual crop is too small")
        pix = source_page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), clip=clip, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def _source_visual_targets(pack: dict, pages: list[dict]) -> list[dict]:
    page_by_ref = {source_ref(page): page for page in pages}
    targets: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for index, spec in enumerate(pack.get("diagram_specs") or [], 1):
        if not isinstance(spec, dict):
            continue
        title = str(spec.get("title") or f"شكل توضيحي {index}").strip()
        description = str(spec.get("description") or "").strip()
        for ref in spec.get("source_refs") or []:
            page = page_by_ref.get(str(ref))
            if not page:
                continue
            key = (int(page["id"]), title)
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "title": title,
                    "description": description,
                    "source_ref": str(ref),
                    "page": page,
                }
            )
            break
        if len(targets) >= MAX_SOURCE_VISUALS:
            break
    return targets


def _source_visual_prompt(title: str, description: str) -> str:
    return (
        "افحص الصفحة المرفقة فقط وحدد هل يوجد داخلها شكل/رسم/صورة/مخطط أصلي واضح "
        "يدعم الهدف المحدد. لا تنشئ رسما ولا تستنتج شكلا غير ظاهر. إذا لم يوجد شكل واضح "
        "أعد found=false. إذا وجد، أعد أصغر مستطيل يشمل الشكل وعناوينه/محاوره الضرورية فقط، "
        "بإحداثيات نسبية من 0 إلى 1 بالنسبة للصفحة: x,y,width,height. "
        "تجنب تضمين فقرات نصية طويلة خارج الشكل. أخرج JSON فقط بالشكل "
        '{"found":true,"bbox":{"x":0.1,"y":0.2,"width":0.5,"height":0.3},'
        '"caption":"string","confidence":0.0}. '
        f"الهدف: {title}. الوصف: {description}"
    )


def _preview_stamp(data: bytes, edition: str) -> bytes:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        label = "PREVIEW · UNAPPROVED · NOT FOR FINAL DISTRIBUTION"
        for page in doc:
            box = fitz.Rect(42, 21, page.rect.width - 42, 39)
            page.draw_rect(box, color=(0.55, 0.18, 0.10), width=0.8)
            page.insert_textbox(
                box,
                label + (" · STUDENT" if edition == "student" else " · TEACHER"),
                fontsize=8.5,
                align=fitz.TEXT_ALIGN_CENTER,
                color=(0.45, 0.12, 0.08),
            )
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def _job(job_id: str):
    with connect() as con:
        job = con.execute("SELECT * FROM lesson_pack_jobs WHERE id=%s", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "Lesson Pack job not found")
        pages = list(
            con.execute(
                """SELECT id,job_id,position,file_index,original_filename,original_page,object_key,
                  extracted_text,alternate_ocr_text,confidence,ocr_confidence_band,ocr_conflicts,
                  requires_review,created_at,updated_at
                  FROM lesson_pack_pages WHERE job_id=%s ORDER BY position""",
                (job_id,),
            ).fetchall()
        )
    return dict(job), [dict(x) for x in pages]


def _status_after_ocr(pages: list[dict]) -> str:
    if any(not page.get("ocr_confidence_band") for page in pages):
        return "transcribing"
    if any(page.get("requires_review") for page in pages):
        return "ocr_review_required"
    return "ready_to_generate"


def _media_type_for_page(page: dict) -> str:
    key = str(page.get("object_key") or "").lower()
    if key.endswith(".png"):
        return "image/png"
    if key.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def _image_page_key(job_id: str, position: int, filename: str, content_type: str) -> str:
    safe = _safe_filename(filename)
    stem = safe.rsplit(".", 1)[0] if "." in safe else safe
    extension = IMAGE_EXTENSIONS[content_type]
    return f"lesson-pack/{job_id}/pages/{position:04d}-{stem}{extension}"


def _cleanup_staged_objects(keys: list[str]) -> None:
    for key in reversed(keys):
        try:
            delete_object(key)
        except Exception:
            # Preserve the original upload/database exception. Orphan cleanup can be
            # retried operationally without masking the failure that caused rollback.
            pass


@app.get("/api/admin/lesson-pack-studio/status", dependencies=[Depends(require_admin)])
def lesson_pack_status():
    return {
        "module": "Lesson Pack Studio",
        "ingestion_enabled": lesson_pack_ingestion_enabled(),
        "isolated_from_curriculum_ingestion": True,
        "subjects": sorted(SUBJECTS),
        "pack_modes": sorted(PACK_MODES),
        "ocr_provider": _provider(),
        "storage_configured": storage_configured(),
        "limits": {
            "max_files": MAX_FILES,
            "max_pages": MAX_PAGES,
            "max_file_bytes": MAX_FILE_BYTES,
            "render_dpi": RENDER_DPI,
        },
        "scientific_reviewer": reviewer_status(),
        "policy": {
            "official_question_bank_write": False,
            "teacher_approval_required_for_final_export": True,
            "source_page_provenance_required": True,
            "original_source_visuals_teacher_review_required": True,
            "pre_export_pdf_preview": True,
            "page_by_page_preview": True,
            "configurable_student_cover": True,
            "generated_questions_labeled": True,
            "curriculum_content_gate_unchanged": True,
        },
    }


@app.post("/api/admin/lesson-pack-studio/jobs", dependencies=[Depends(require_admin)])
async def create_lesson_pack_job(
    title: str = Form(...),
    subject: str = Form("physics"),
    grade_label: str = Form(""),
    pack_mode: str = Form("balanced"),
    files: list[UploadFile] = File(...),
):
    require_lesson_pack_ingestion_enabled()
    if subject not in SUBJECTS:
        raise HTTPException(400, "subject must be physics, chemistry, or science")
    if pack_mode not in PACK_MODES:
        raise HTTPException(400, "Invalid pack mode")
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"Upload between 1 and {MAX_FILES} source files")
    if not storage_configured():
        raise HTTPException(503, "Object storage is not configured")

    job_id = str(uuid.uuid4())
    staged_pages: list[tuple] = []
    written_keys: list[str] = []
    position = 0
    total_pages = 0

    try:
        for file_index, upload in enumerate(files, 1):
            content_type = (upload.content_type or "").lower()
            if content_type not in ALLOWED_TYPES:
                raise HTTPException(415, f"Unsupported source type: {content_type}")
            data = await upload.read()
            if not data or len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, f"{upload.filename}: file is empty or exceeds limit")
            filename = upload.filename or f"source-{file_index}"
            original_key = (
                f"lesson-pack/{job_id}/original/{file_index}-{_safe_filename(filename)}"
            )
            put_bytes(original_key, data, content_type)
            written_keys.append(original_key)

            if content_type == "application/pdf":
                try:
                    doc = fitz.open(stream=data, filetype="pdf")
                except Exception as exc:
                    raise HTTPException(415, f"{filename}: invalid PDF") from exc
                try:
                    total_pages += doc.page_count
                    if total_pages > MAX_PAGES:
                        raise HTTPException(413, f"Lesson Pack exceeds {MAX_PAGES} pages")
                    matrix = fitz.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
                    for page_number, page in enumerate(doc, 1):
                        position += 1
                        png = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
                        page_key = f"lesson-pack/{job_id}/pages/{position:04d}.png"
                        put_bytes(page_key, png, "image/png")
                        written_keys.append(page_key)
                        staged_pages.append(
                            (position, file_index, filename, page_number, page_key)
                        )
                finally:
                    doc.close()
            else:
                total_pages += 1
                if total_pages > MAX_PAGES:
                    raise HTTPException(413, f"Lesson Pack exceeds {MAX_PAGES} pages")
                position += 1
                page_key = _image_page_key(
                    job_id, position, filename, content_type
                )
                put_bytes(page_key, data, content_type)
                written_keys.append(page_key)
                staged_pages.append((position, file_index, filename, 1, page_key))

        with connect() as con:
            con.execute(
                """INSERT INTO lesson_pack_jobs(
                  id,title,subject,grade_label,pack_mode,status,source_file_count,source_page_count
                ) VALUES(%s,%s,%s,%s,%s,'uploaded',%s,%s)""",
                (
                    job_id,
                    title.strip(),
                    subject,
                    grade_label.strip(),
                    pack_mode,
                    len(files),
                    len(staged_pages),
                ),
            )
            for pos, file_index, filename, page_number, page_key in staged_pages:
                con.execute(
                    """INSERT INTO lesson_pack_pages(
                      job_id,position,file_index,original_filename,original_page,object_key
                    ) VALUES(%s,%s,%s,%s,%s,%s)""",
                    (job_id, pos, file_index, filename, page_number, page_key),
                )
    except Exception:
        _cleanup_staged_objects(written_keys)
        raise

    return {
        "id": job_id,
        "status": "uploaded",
        "source_file_count": len(files),
        "source_page_count": len(staged_pages),
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/process-next",
    dependencies=[Depends(require_admin)],
)
def process_next_lesson_pack_page(job_id: str, request: Request):
    enforce_request_policy(
        request,
        name="admin_lesson_pack_ocr",
        default_limit=120,
        default_window_seconds=3600,
    )
    _, pages = _job(job_id)
    pending = next((page for page in pages if not page.get("ocr_confidence_band")), None)
    if not pending:
        status = _status_after_ocr(pages)
        with connect() as con:
            con.execute(
                "UPDATE lesson_pack_jobs SET status=%s,updated_at=now() WHERE id=%s",
                (status, job_id),
            )
        return {
            "id": job_id,
            "done": True,
            "status": status,
            "processed": len(pages),
            "remaining": 0,
            "review_pages": sum(1 for page in pages if page.get("requires_review")),
        }

    provider = _provider()
    if provider == "unconfigured":
        raise HTTPException(503, "No OCR provider configured")

    data = get_bytes(pending["object_key"])
    try:
        text, alternate, verification = _verified_ocr(
            data,
            _media_type_for_page(pending),
            int(pending["position"]),
        )
    except Exception:
        with connect() as con:
            con.execute(
                "UPDATE lesson_pack_jobs SET status='ocr_error',updated_at=now() WHERE id=%s",
                (job_id,),
            )
        raise

    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_pages SET extracted_text=%s,alternate_ocr_text=%s,
              confidence=%s,ocr_confidence_band=%s,ocr_conflicts=%s::jsonb,
              requires_review=%s,updated_at=now() WHERE id=%s AND job_id=%s""",
            (
                text,
                alternate,
                verification["score"],
                verification["confidence_band"],
                json.dumps(verification["conflicts"], ensure_ascii=False),
                verification["requires_review"],
                pending["id"],
                job_id,
            ),
        )
        con.execute(
            "UPDATE lesson_pack_jobs SET status='transcribing',teacher_approved=FALSE,updated_at=now() WHERE id=%s",
            (job_id,),
        )

    _, refreshed = _job(job_id)
    remaining = sum(1 for page in refreshed if not page.get("ocr_confidence_band"))
    review_pages = sum(
        1
        for page in refreshed
        if page.get("requires_review") and page.get("ocr_confidence_band")
    )
    return {
        "id": job_id,
        "done": remaining == 0,
        "processed_page": {
            "id": pending["id"],
            "position": pending["position"],
            "source_ref": source_ref(pending),
            "requires_review": verification["requires_review"],
            "confidence_band": verification["confidence_band"],
        },
        "processed": len(refreshed) - remaining,
        "remaining": remaining,
        "review_pages": review_pages,
        "status": _status_after_ocr(refreshed),
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/pages/{page_id}/approve",
    dependencies=[Depends(require_admin)],
)
def approve_lesson_pack_page(
    job_id: str,
    page_id: int,
    corrected_text: str = Form(...),
):
    text = corrected_text.strip()
    if not text:
        raise HTTPException(400, "Approved page transcript cannot be empty")

    _, pages = _job(job_id)
    target = next((page for page in pages if int(page["id"]) == int(page_id)), None)
    if not target:
        raise HTTPException(404, "Lesson Pack page not found")
    changed = text != str(target.get("extracted_text") or "")

    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_pages SET extracted_text=%s,requires_review=FALSE,
              ocr_confidence_band='teacher_approved',updated_at=now()
              WHERE id=%s AND job_id=%s""",
            (text, page_id, job_id),
        )
        if changed:
            con.execute(
                """UPDATE lesson_pack_jobs SET pack_json=NULL,scientific_review_json=NULL,
                  teacher_approved=FALSE,pdf_student_object_key=NULL,pdf_teacher_object_key=NULL,
                  status='ready_to_generate',updated_at=now() WHERE id=%s""",
                (job_id,),
            )
        else:
            con.execute(
                "UPDATE lesson_pack_jobs SET teacher_approved=FALSE,updated_at=now() WHERE id=%s",
                (job_id,),
            )

    _, refreshed = _job(job_id)
    return {
        "approved": True,
        "page_id": page_id,
        "content_changed": changed,
        "pack_invalidated": changed,
        "review_pages": sum(1 for page in refreshed if page.get("requires_review")),
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/generate",
    dependencies=[Depends(require_admin)],
)
def generate_lesson_pack(
    job_id: str,
    request: Request,
    question_count: int = Form(DEFAULT_QUESTION_COUNT),
):
    enforce_request_policy(
        request,
        name="admin_lesson_pack_generate",
        default_limit=12,
        default_window_seconds=3600,
    )
    job, pages = _job(job_id)
    missing = [page for page in pages if not page.get("ocr_confidence_band")]
    if missing:
        raise HTTPException(
            409,
            {
                "message": "Finish OCR before generating the Lesson Pack",
                "remaining_pages": len(missing),
            },
        )

    refs = allowed_source_refs(pages)
    transcript = "\n\n".join(
        f"[{source_ref(page)}]\n{page.get('extracted_text') or ''}" for page in pages
    )
    pack = build_pack(
        transcript,
        title=job["title"],
        subject=job["subject"],
        grade_label=job.get("grade_label") or "",
        pack_mode=job["pack_mode"],
        refs=refs,
        question_count=question_count,
    )
    review_pages = sum(1 for page in pages if page.get("requires_review"))
    status = "pack_review_required" if review_pages else "scientific_review_required"

    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_jobs SET raw_transcript=%s,pack_json=%s::jsonb,
              scientific_review_json=NULL,teacher_approved=FALSE,status=%s,
              pdf_student_object_key=NULL,pdf_teacher_object_key=NULL,updated_at=now()
              WHERE id=%s""",
            (transcript, json.dumps(pack, ensure_ascii=False), status, job_id),
        )

    return {
        "id": job_id,
        "status": status,
        "review_pages": review_pages,
        "question_count": len(pack.get("practice_questions") or []),
        "provenance": pack.get("provenance_validation"),
        "pack": pack,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/scientific-review",
    dependencies=[Depends(require_admin)],
)
def scientific_review_lesson_pack(job_id: str, request: Request):
    enforce_request_policy(
        request,
        name="admin_lesson_pack_scientific_review",
        default_limit=10,
        default_window_seconds=3600,
    )
    job, _ = _job(job_id)
    pack = job.get("pack_json")
    transcript = job.get("raw_transcript") or ""
    if not pack or not transcript:
        raise HTTPException(409, "Generate the Lesson Pack before scientific review")

    status = reviewer_status()
    if not status["configured"]:
        raise HTTPException(503, "Independent scientific reviewer is not configured")

    review = _openai_review(
        transcript,
        pack,
        job["subject"],
        job.get("grade_label") or "",
        job_id=job_id,
    )
    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_jobs SET scientific_review_json=%s::jsonb,
              status='teacher_approval_required',teacher_approved=FALSE,updated_at=now()
              WHERE id=%s""",
            (json.dumps(review, ensure_ascii=False), job_id),
        )

    return {"id": job_id, "status": "teacher_approval_required", "review": review}


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/approve",
    dependencies=[Depends(require_admin)],
)
def approve_lesson_pack(
    job_id: str,
    confirm_source_grounded: bool = Form(False),
    accept_reviewer_findings: bool = Form(False),
    notes: str = Form(""),
):
    if not confirm_source_grounded:
        raise HTTPException(400, "Teacher source-grounding confirmation is required")

    job, pages = _job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before approval")

    unresolved = [
        page
        for page in pages
        if page.get("requires_review") or not page.get("ocr_confidence_band")
    ]
    if unresolved:
        raise HTTPException(
            409,
            {
                "message": "Resolve all OCR page reviews before final approval",
                "pages": len(unresolved),
            },
        )

    provenance = validate_pack_provenance(pack, allowed_source_refs(pages))
    if not provenance.get("passed"):
        raise HTTPException(
            409,
            {
                "message": "Source provenance validation must pass",
                "provenance": provenance,
            },
        )

    reviewer = reviewer_status()
    review = job.get("scientific_review_json")
    if reviewer["configured"] and not review:
        raise HTTPException(
            409, "Run the independent scientific review before final approval"
        )
    if (
        review
        and review.get("verdict") == "review_required"
        and not accept_reviewer_findings
    ):
        raise HTTPException(
            409,
            {
                "message": "Reviewer findings require explicit teacher acceptance",
                "findings": review.get("findings") or [],
            },
        )

    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_jobs SET teacher_approved=TRUE,approval_notes=%s,
              status='approved',updated_at=now() WHERE id=%s""",
            (notes.strip(), job_id),
        )

    return {
        "approved": True,
        "id": job_id,
        "status": "approved",
        "official_question_bank_write": False,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/suggest",
    dependencies=[Depends(require_admin)],
)
def suggest_lesson_pack_source_visuals(job_id: str, request: Request):
    enforce_request_policy(
        request,
        name="admin_lesson_pack_source_visuals",
        default_limit=8,
        default_window_seconds=3600,
    )
    job, pages = _job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before detecting source visuals")
    approved_existing = [
        item
        for item in (pack.get("source_visuals") or [])
        if isinstance(item, dict) and item.get("approved") and item.get("object_key")
    ]
    targets = [
        target
        for target in _source_visual_targets(pack, pages)
        if not any(
            item.get("source_ref") == target["source_ref"]
            and str(item.get("title") or "") == target["title"]
            for item in approved_existing
        )
    ]
    if not targets:
        pack["source_visuals"] = approved_existing
        with connect() as con:
            con.execute(
                "UPDATE lesson_pack_jobs SET pack_json=%s::jsonb,updated_at=now() WHERE id=%s",
                (json.dumps(pack, ensure_ascii=False), job_id),
            )
        return {"count": 0, "items": [], "message": "No source-linked diagram targets were found"}

    suggestions: list[dict] = []
    for index, target in enumerate(targets, 1):
        page = target["page"]
        image = get_bytes(page["object_key"])
        raw = _gemini_text(
            [
                {
                    "text": (
                        f"Source: {target['source_ref']}\n"
                        f"Target title: {target['title']}\n"
                        f"Target description: {target['description']}"
                    )
                },
                {
                    "inlineData": {
                        "mimeType": _media_type_for_page(page),
                        "data": base64.b64encode(image).decode("ascii"),
                    }
                },
            ],
            _source_visual_prompt(target["title"], target["description"]),
            json_mode=True,
            task="lesson_pack_source_visual",
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if payload.get("found") is not True:
            continue
        try:
            bbox = _normalize_visual_bbox(payload)
            confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
        except (HTTPException, TypeError, ValueError):
            continue
        suggestions.append(
            {
                "id": f"source-visual-{int(page['id'])}-{index}",
                "title": target["title"],
                "description": str(payload.get("caption") or target["description"] or "").strip(),
                "source_ref": target["source_ref"],
                "source_refs": [target["source_ref"]],
                "page_id": int(page["id"]),
                "bbox": bbox,
                "confidence": round(confidence, 4),
                "approved": False,
                "rejected": False,
                "review_required": True,
                "object_key": None,
                "media_type": "image/png",
                "policy": "original_source_crop_teacher_review_required",
            }
        )

    pack["source_visuals"] = approved_existing + suggestions
    with connect() as con:
        con.execute(
            "UPDATE lesson_pack_jobs SET pack_json=%s::jsonb,updated_at=now() WHERE id=%s",
            (json.dumps(pack, ensure_ascii=False), job_id),
        )
    return {
        "count": len(suggestions),
        "items": suggestions,
        "auto_approved": False,
        "policy": "original_source_crop_teacher_review_required",
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/{visual_id}/preview",
    dependencies=[Depends(require_admin)],
)
def preview_lesson_pack_source_visual(job_id: str, visual_id: str):
    job, pages = _job(job_id)
    pack = job.get("pack_json") or {}
    item = next(
        (x for x in (pack.get("source_visuals") or []) if isinstance(x, dict) and x.get("id") == visual_id),
        None,
    )
    if not item:
        raise HTTPException(404, "Source visual not found")
    page = next((x for x in pages if int(x["id"]) == int(item["page_id"])), None)
    if not page:
        raise HTTPException(404, "Source page not found")
    data = _crop_page_image(page, _normalize_visual_bbox(item))
    return Response(
        data,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-visuals/{visual_id}/review",
    dependencies=[Depends(require_admin)],
)
def review_lesson_pack_source_visual(
    job_id: str,
    visual_id: str,
    action: str = Form(...),
    x: float | None = Form(None),
    y: float | None = Form(None),
    width: float | None = Form(None),
    height: float | None = Form(None),
):
    if action not in {"approve", "reject"}:
        raise HTTPException(400, "action must be approve or reject")
    job, pages = _job(job_id)
    pack = job.get("pack_json") or {}
    visuals = [x for x in (pack.get("source_visuals") or []) if isinstance(x, dict)]
    item = next((v for v in visuals if v.get("id") == visual_id), None)
    if not item:
        raise HTTPException(404, "Source visual not found")

    if action == "approve":
        raw_bbox = item.get("bbox") or {}
        if None not in (x, y, width, height):
            raw_bbox = {"x": x, "y": y, "width": width, "height": height}
        bbox = _normalize_visual_bbox(raw_bbox)
        page = next((p for p in pages if int(p["id"]) == int(item["page_id"])), None)
        if not page:
            raise HTTPException(404, "Source page not found")
        crop = _crop_page_image(page, bbox)
        key = f"lesson-pack/{job_id}/source-visuals/{visual_id}.png"
        put_bytes(key, crop, "image/png")
        item.update(
            {
                "bbox": bbox,
                "approved": True,
                "rejected": False,
                "review_required": False,
                "object_key": key,
                "media_type": "image/png",
            }
        )
    else:
        old_key = item.get("object_key")
        if old_key:
            try:
                delete_object(str(old_key))
            except Exception:
                pass
        item.update(
            {
                "approved": False,
                "rejected": True,
                "review_required": False,
                "object_key": None,
            }
        )

    pack["source_visuals"] = visuals
    next_status = (
        "scientific_review_required"
        if reviewer_status()["configured"] and not job.get("scientific_review_json")
        else "teacher_approval_required"
    )
    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_jobs SET pack_json=%s::jsonb,teacher_approved=FALSE,
              pdf_student_object_key=NULL,pdf_teacher_object_key=NULL,
              status=%s,updated_at=now() WHERE id=%s""",
            (json.dumps(pack, ensure_ascii=False), next_status, job_id),
        )
    return {
        "id": visual_id,
        "action": action,
        "approved": bool(item.get("approved")),
        "teacher_reapproval_required": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/cover",
    dependencies=[Depends(require_admin)],
)
def update_lesson_pack_cover(
    job_id: str,
    student_name: str = Form(""),
    class_label: str = Form(""),
    teacher_name: str = Form(""),
    school_name: str = Form(""),
    academic_term: str = Form(""),
):
    job, _ = _job(job_id)
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before editing the cover")
    pack["cover"] = {
        "student_name": _clean_cover_value(student_name),
        "class_label": _clean_cover_value(class_label),
        "teacher_name": _clean_cover_value(teacher_name),
        "school_name": _clean_cover_value(school_name),
        "academic_term": _clean_cover_value(academic_term),
    }
    next_status = (
        "scientific_review_required"
        if reviewer_status()["configured"] and not job.get("scientific_review_json")
        else "teacher_approval_required"
    )
    for key in ("pdf_student_object_key", "pdf_teacher_object_key"):
        old_key = job.get(key)
        if old_key:
            try:
                delete_object(str(old_key))
            except Exception:
                pass
    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_jobs SET pack_json=%s::jsonb,teacher_approved=FALSE,
              pdf_student_object_key=NULL,pdf_teacher_object_key=NULL,status=%s,updated_at=now()
              WHERE id=%s""",
            (json.dumps(pack, ensure_ascii=False), next_status, job_id),
        )
    return {
        "id": job_id,
        "cover": pack["cover"],
        "status": next_status,
        "teacher_reapproval_required": True,
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-pdf",
    dependencies=[Depends(require_admin)],
)
def preview_lesson_pack_pdf(job_id: str, edition: str = "student"):
    data = _lesson_pack_preview_bytes(job_id, edition)
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="lesson-pack-preview-{edition}-{job_id}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Lesson-Pack-Preview": "unapproved",
        },
    )


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-manifest",
    dependencies=[Depends(require_admin)],
)
def lesson_pack_preview_manifest(job_id: str, edition: str = "student"):
    data = _lesson_pack_preview_bytes(job_id, edition)
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        total = doc.page_count
    finally:
        doc.close()
    return {
        "edition": edition,
        "page_count": total,
        "preview": True,
        "approved": False,
        "page_url_template": (
            f"/api/admin/lesson-pack-studio/jobs/{job_id}/preview-page/{{page_number}}"
            f"?edition={edition}"
        ),
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/preview-page/{page_number}",
    dependencies=[Depends(require_admin)],
)
def lesson_pack_preview_page(job_id: str, page_number: int, edition: str = "student"):
    data = _lesson_pack_preview_bytes(job_id, edition)
    png, total = _preview_page_png(data, page_number)
    return Response(
        png,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Lesson-Pack-Preview": "unapproved",
            "X-Lesson-Pack-Page": str(page_number),
            "X-Lesson-Pack-Page-Count": str(total),
        },
    )


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}",
    dependencies=[Depends(require_admin)],
)
def get_lesson_pack_job(job_id: str):
    job, pages = _job(job_id)
    for page in pages:
        page["source_ref"] = source_ref(page)
        page["image_url"] = (
            f"/api/admin/lesson-pack-studio/jobs/{job_id}/pages/{page['id']}/image"
        )

    return {
        **job,
        "pages": pages,
        "progress": {
            "total_pages": len(pages),
            "transcribed_pages": sum(
                1 for page in pages if page.get("ocr_confidence_band")
            ),
            "review_pages": sum(
                1
                for page in pages
                if page.get("requires_review") and page.get("ocr_confidence_band")
            ),
        },
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/pages/{page_id}/image",
    dependencies=[Depends(require_admin)],
)
def lesson_pack_page_image(job_id: str, page_id: int):
    _, pages = _job(job_id)
    page = next((item for item in pages if int(item["id"]) == int(page_id)), None)
    if not page:
        raise HTTPException(404, "Lesson Pack page not found")
    return Response(
        get_bytes(page["object_key"]),
        media_type=_media_type_for_page(page),
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/export-pdf",
    dependencies=[Depends(require_admin)],
)
def export_lesson_pack_pdf(job_id: str, edition: str = "student"):
    if edition not in {"student", "teacher"}:
        raise HTTPException(400, "edition must be student or teacher")

    job, pages = _job(job_id)
    if not job.get("teacher_approved"):
        raise HTTPException(
            409, "Teacher approval is required before final PDF export"
        )
    pack = job.get("pack_json")
    if not pack:
        raise HTTPException(409, "Lesson Pack has not been generated")
    provenance = validate_pack_provenance(pack, allowed_source_refs(pages))
    if not provenance.get("passed"):
        raise HTTPException(
            409,
            {
                "message": "Source provenance validation must pass before export",
                "provenance": provenance,
            },
        )

    data = render_pdf(pack, edition)
    key = f"lesson-pack/{job_id}/lesson-pack-{edition}.pdf"
    put_bytes(key, data, "application/pdf")
    column = (
        "pdf_student_object_key"
        if edition == "student"
        else "pdf_teacher_object_key"
    )
    with connect() as con:
        con.execute(
            f"UPDATE lesson_pack_jobs SET {column}=%s,status='pdf_ready',updated_at=now() WHERE id=%s",
            (key, job_id),
        )

    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="lesson-pack-{edition}-{job_id}.pdf"'
        },
    )
