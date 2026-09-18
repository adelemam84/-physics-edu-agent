from __future__ import annotations

import json
from typing import Any

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import Response

from . import lesson_pack_studio
from .db import connect
from .main import app
from .science_lesson_studio import _verified_ocr
from .security import require_admin
from .services.ocr_consensus import compare_ocr, single_provider_result
from .services.rate_limit import enforce_request_policy
from .services.source_cleanup import analyze_page, enhance_page
from .services.storage import delete_object, get_bytes, put_bytes

_PROFILES = {"balanced", "text_priority", "tables_priority", "diagrams_priority", "safe"}
_VARIANTS = {"original", "visual", "ocr", "diff"}
_MAX_BATCH = 12


def _page(job_id: str, page_id: int) -> dict:
    _, pages = lesson_pack_studio._job(job_id)
    page = next((x for x in pages if int(x["id"]) == int(page_id)), None)
    if not page:
        raise HTTPException(404, "Lesson Pack page not found")
    return page


def _enhancement(page_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(
            """SELECT page_id,job_id,original_object_key,visual_object_key,ocr_object_key,
                      diff_object_key,profile,params_json,metrics_before_json,metrics_after_json,
                      fidelity_json,ocr_comparison_json,teacher_approved,approval_notes,
                      created_at,updated_at
               FROM lesson_pack_page_enhancements WHERE page_id=%s""",
            (page_id,),
        ).fetchone()
    return dict(row) if row else None


def _cleanup_key(job_id: str, page_id: int, variant: str) -> str:
    return f"lesson-pack/{job_id}/cleanup/{page_id}/{variant}.png"


def _public_enhancement(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "page_id": row["page_id"],
        "profile": row["profile"],
        "params": row.get("params_json") or {},
        "metrics_before": row.get("metrics_before_json") or {},
        "metrics_after": row.get("metrics_after_json") or {},
        "fidelity": row.get("fidelity_json") or {},
        "ocr_comparison": row.get("ocr_comparison_json"),
        "teacher_approved": bool(row.get("teacher_approved")),
        "approval_notes": row.get("approval_notes"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "has_visual": bool(row.get("visual_object_key")),
        "has_ocr": bool(row.get("ocr_object_key")),
        "has_diff": bool(row.get("diff_object_key")),
        "content_synthesis_used": False,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup",
    dependencies=[Depends(require_admin)],
)
def source_cleanup_status(job_id: str):
    _, pages = lesson_pack_studio._job(job_id)
    page_ids = [int(page["id"]) for page in pages]
    rows: dict[int, dict] = {}
    if page_ids:
        with connect() as con:
            found = list(
                con.execute(
                    """SELECT page_id,job_id,original_object_key,visual_object_key,ocr_object_key,
                              diff_object_key,profile,params_json,metrics_before_json,metrics_after_json,
                              fidelity_json,ocr_comparison_json,teacher_approved,approval_notes,
                              created_at,updated_at
                       FROM lesson_pack_page_enhancements
                       WHERE job_id=%s ORDER BY page_id""",
                    (job_id,),
                ).fetchall()
            )
        rows = {int(row["page_id"]): dict(row) for row in found}
    return {
        "job_id": job_id,
        "pages": [
            {
                "id": int(page["id"]),
                "position": int(page["position"]),
                "filename": page["original_filename"],
                "source_ref": lesson_pack_studio.source_ref(page),
                "ocr_confidence_band": page.get("ocr_confidence_band"),
                "requires_review": bool(page.get("requires_review")),
                "enhancement": _public_enhancement(rows.get(int(page["id"]))),
            }
            for page in pages
        ],
        "profiles": sorted(_PROFILES),
        "max_batch": _MAX_BATCH,
        "non_generative": True,
        "originals_immutable": True,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/analyze",
    dependencies=[Depends(require_admin)],
)
def analyze_source_cleanup_page(job_id: str, page_id: int, request: Request):
    enforce_request_policy(
        request,
        name="admin_source_cleanup_analyze",
        default_limit=120,
        default_window_seconds=3600,
    )
    page = _page(job_id, page_id)
    try:
        result = analyze_page(get_bytes(page["object_key"]))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "page_id": page_id,
        **result,
        "original_preserved": True,
        "non_generative": True,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/enhance",
    dependencies=[Depends(require_admin)],
)
def enhance_source_cleanup_page(
    job_id: str,
    page_id: int,
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    enforce_request_policy(
        request,
        name="admin_source_cleanup_enhance",
        default_limit=90,
        default_window_seconds=3600,
    )
    page = _page(job_id, page_id)
    profile = str(payload.get("profile") or "balanced").strip()
    if profile not in _PROFILES:
        raise HTTPException(422, "Unsupported cleanup profile")
    params = payload.get("params") or {}
    previous = _enhancement(page_id)
    try:
        result = enhance_page(
            get_bytes(page["object_key"]),
            profile=profile,
            params=params,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    visual_key = _cleanup_key(job_id, page_id, "visual")
    ocr_key = _cleanup_key(job_id, page_id, "ocr")
    diff_key = _cleanup_key(job_id, page_id, "diff")
    put_bytes(visual_key, result.visual_png, "image/png")
    put_bytes(ocr_key, result.ocr_png, "image/png")
    put_bytes(diff_key, result.diff_png, "image/png")

    with connect() as con:
        con.execute(
            """INSERT INTO lesson_pack_page_enhancements(
                 page_id,job_id,original_object_key,visual_object_key,ocr_object_key,diff_object_key,
                 profile,params_json,metrics_before_json,metrics_after_json,fidelity_json,
                 ocr_comparison_json,teacher_approved,approval_notes,updated_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
                         NULL,FALSE,NULL,now())
               ON CONFLICT (page_id) DO UPDATE SET
                 job_id=excluded.job_id,
                 original_object_key=excluded.original_object_key,
                 visual_object_key=excluded.visual_object_key,
                 ocr_object_key=excluded.ocr_object_key,
                 diff_object_key=excluded.diff_object_key,
                 profile=excluded.profile,
                 params_json=excluded.params_json,
                 metrics_before_json=excluded.metrics_before_json,
                 metrics_after_json=excluded.metrics_after_json,
                 fidelity_json=excluded.fidelity_json,
                 ocr_comparison_json=NULL,
                 teacher_approved=FALSE,
                 approval_notes=NULL,
                 updated_at=now()""",
            (
                page_id,
                job_id,
                page["object_key"],
                visual_key,
                ocr_key,
                diff_key,
                result.profile,
                json.dumps(result.params, ensure_ascii=False),
                json.dumps(result.metrics_before, ensure_ascii=False),
                json.dumps(result.metrics_after, ensure_ascii=False),
                json.dumps(result.fidelity, ensure_ascii=False),
            ),
        )
    if previous and previous.get("teacher_approved"):
        with connect() as con:
            con.execute(
                "UPDATE lesson_pack_jobs SET teacher_approved=FALSE,updated_at=now() WHERE id=%s",
                (job_id,),
            )
    return {
        "page_id": page_id,
        "profile": result.profile,
        "params": result.params,
        "suggested_profile": result.suggested_profile,
        "metrics_before": result.metrics_before,
        "metrics_after": result.metrics_after,
        "fidelity": result.fidelity,
        "teacher_approved": False,
        "approval_invalidated": bool(previous and previous.get("teacher_approved")),
        "variants": ["original", "visual", "ocr", "diff"],
        "original_preserved": True,
        "content_synthesis_used": False,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/batch-enhance",
    dependencies=[Depends(require_admin)],
)
def batch_enhance_source_cleanup(
    job_id: str,
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    enforce_request_policy(
        request,
        name="admin_source_cleanup_batch",
        default_limit=20,
        default_window_seconds=3600,
    )
    _, pages = lesson_pack_studio._job(job_id)
    requested = payload.get("page_ids")
    if requested is None:
        page_ids = [int(page["id"]) for page in pages][: _MAX_BATCH]
    elif isinstance(requested, list):
        page_ids = []
        known = {int(page["id"]) for page in pages}
        for value in requested:
            try:
                pid = int(value)
            except (TypeError, ValueError):
                continue
            if pid in known and pid not in page_ids:
                page_ids.append(pid)
        page_ids = page_ids[: _MAX_BATCH]
    else:
        raise HTTPException(422, "page_ids must be an array")

    profile = str(payload.get("profile") or "balanced")
    params = payload.get("params") or {}
    only_low_quality = bool(payload.get("only_low_quality", False))
    results = []
    for page_id in page_ids:
        page = _page(job_id, page_id)
        source = get_bytes(page["object_key"])
        analysis = analyze_page(source)
        if only_low_quality and not analysis.get("needs_cleanup"):
            results.append(
                {
                    "page_id": page_id,
                    "skipped": True,
                    "reason": "quality_already_good",
                    "metrics": analysis["metrics"],
                }
            )
            continue
        try:
            result = enhance_page(source, profile=profile, params=params)
        except ValueError as exc:
            results.append({"page_id": page_id, "error": str(exc)})
            continue
        visual_key = _cleanup_key(job_id, page_id, "visual")
        ocr_key = _cleanup_key(job_id, page_id, "ocr")
        diff_key = _cleanup_key(job_id, page_id, "diff")
        put_bytes(visual_key, result.visual_png, "image/png")
        put_bytes(ocr_key, result.ocr_png, "image/png")
        put_bytes(diff_key, result.diff_png, "image/png")
        with connect() as con:
            con.execute(
                """INSERT INTO lesson_pack_page_enhancements(
                     page_id,job_id,original_object_key,visual_object_key,ocr_object_key,diff_object_key,
                     profile,params_json,metrics_before_json,metrics_after_json,fidelity_json,
                     teacher_approved,updated_at
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,FALSE,now())
                   ON CONFLICT (page_id) DO UPDATE SET
                     original_object_key=excluded.original_object_key,
                     visual_object_key=excluded.visual_object_key,
                     ocr_object_key=excluded.ocr_object_key,
                     diff_object_key=excluded.diff_object_key,
                     profile=excluded.profile,
                     params_json=excluded.params_json,
                     metrics_before_json=excluded.metrics_before_json,
                     metrics_after_json=excluded.metrics_after_json,
                     fidelity_json=excluded.fidelity_json,
                     ocr_comparison_json=NULL,
                     teacher_approved=FALSE,
                     approval_notes=NULL,
                     updated_at=now()""",
                (
                    page_id,
                    job_id,
                    page["object_key"],
                    visual_key,
                    ocr_key,
                    diff_key,
                    result.profile,
                    json.dumps(result.params, ensure_ascii=False),
                    json.dumps(result.metrics_before, ensure_ascii=False),
                    json.dumps(result.metrics_after, ensure_ascii=False),
                    json.dumps(result.fidelity, ensure_ascii=False),
                ),
            )
        results.append(
            {
                "page_id": page_id,
                "enhanced": True,
                "fidelity": result.fidelity,
                "metrics_before": result.metrics_before,
                "metrics_after": result.metrics_after,
            }
        )
    return {
        "processed": len(results),
        "results": results,
        "max_batch": _MAX_BATCH,
        "originals_immutable": True,
        "content_synthesis_used": False,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/preview/{variant}",
    dependencies=[Depends(require_admin)],
)
def source_cleanup_preview(job_id: str, page_id: int, variant: str):
    if variant not in _VARIANTS:
        raise HTTPException(400, "variant must be original, visual, ocr, or diff")
    page = _page(job_id, page_id)
    if variant == "original":
        return Response(get_bytes(page["object_key"]), media_type=lesson_pack_studio._media_type_for_page(page))
    row = _enhancement(page_id)
    if not row:
        raise HTTPException(404, "No enhanced output exists for this page")
    key = row.get(f"{variant}_object_key")
    if not key:
        raise HTTPException(404, f"No {variant} output exists for this page")
    return Response(get_bytes(key), media_type="image/png")


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/approve",
    dependencies=[Depends(require_admin)],
)
def approve_source_cleanup_page(
    job_id: str,
    page_id: int,
    payload: dict = Body(default_factory=dict),
):
    _page(job_id, page_id)
    row = _enhancement(page_id)
    if not row:
        raise HTTPException(409, "Enhance the page before approval")
    fidelity = row.get("fidelity_json") or {}
    if not fidelity.get("passed"):
        raise HTTPException(
            409,
            {
                "message": "Fidelity check must pass before cleanup approval",
                "fidelity": fidelity,
            },
        )
    approved = payload.get("approved", True) is True
    notes = " ".join(str(payload.get("notes") or "").strip().split())[:500] or None
    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_page_enhancements
               SET teacher_approved=%s,approval_notes=%s,updated_at=now()
               WHERE page_id=%s AND job_id=%s""",
            (approved, notes, page_id, job_id),
        )
    return {
        "page_id": page_id,
        "teacher_approved": approved,
        "ocr_source_when_processing": "approved_enhanced" if approved else "original",
        "original_preserved": True,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}/verify-ocr",
    dependencies=[Depends(require_admin)],
)
def verify_source_cleanup_ocr(job_id: str, page_id: int, request: Request):
    enforce_request_policy(
        request,
        name="admin_source_cleanup_ocr_verify",
        default_limit=60,
        default_window_seconds=3600,
    )
    page = _page(job_id, page_id)
    row = _enhancement(page_id)
    if not row or not row.get("ocr_object_key"):
        raise HTTPException(409, "Create an OCR-enhanced output first")
    enhanced_text, alternate, verification = _verified_ocr(
        get_bytes(row["ocr_object_key"]),
        "image/png",
        int(page["position"]),
    )
    original_text = str(page.get("extracted_text") or "").strip()
    if original_text:
        comparison = compare_ocr(original_text, enhanced_text).as_dict()
    else:
        comparison = single_provider_result(enhanced_text).as_dict()
    result = {
        "original_ocr_available": bool(original_text),
        "enhanced_ocr": enhanced_text,
        "alternate_ocr": alternate,
        "enhanced_provider_verification": verification,
        "comparison_to_current_original_ocr": comparison,
        "automatic_text_replacement": False,
        "teacher_review_required": bool(comparison.get("requires_review")),
    }
    with connect() as con:
        con.execute(
            """UPDATE lesson_pack_page_enhancements
               SET ocr_comparison_json=%s::jsonb,updated_at=now()
               WHERE page_id=%s AND job_id=%s""",
            (json.dumps(result, ensure_ascii=False), page_id, job_id),
        )
    return {
        "page_id": page_id,
        **result,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }


@app.delete(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup/pages/{page_id}",
    dependencies=[Depends(require_admin)],
)
def delete_source_cleanup_page(job_id: str, page_id: int):
    _page(job_id, page_id)
    row = _enhancement(page_id)
    if not row:
        return {"deleted": False}
    keys = [
        row.get("visual_object_key"),
        row.get("ocr_object_key"),
        row.get("diff_object_key"),
    ]
    with connect() as con:
        con.execute(
            "DELETE FROM lesson_pack_page_enhancements WHERE page_id=%s AND job_id=%s",
            (page_id, job_id),
        )
    for key in keys:
        if key:
            try:
                delete_object(key)
            except Exception:
                pass
    return {
        "deleted": True,
        "original_preserved": True,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }
