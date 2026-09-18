from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

from .content_completion import (
    _download_drive_pdf,
    _extract_source_page_batch,
    _store_explanatory_pdf,
    content_completion_snapshot,
)
from .db import connect
from .lesson_sources import LessonSourceMap, approve_lesson_source, map_lesson_source
from .main import app
from .services.ai_governance import model_settings, provider_status
from .visual_review_assistant import _queue_rows, generate_visual_suggestion


SOURCES = {
    "electrical": {
        "url": "https://drive.google.com/file/d/195PEdaVl-in1SXud-lZv3JKycXJ1y6GN/view?usp=drivesdk",
        "filename": "الفيزياء الكهربية-رامي ماهر.pdf",
        "kind": "textbook",
        "term_id": 2,
        "mappings": [(14,5,18),(15,19,27),(16,28,36),(17,40,68),(18,70,105),(19,107,125)],
    },
    "modern": {
        "url": "https://drive.google.com/file/d/19kBzJp8OeLRqVNtHb2Uk8s-XUPTg1h92/view?usp=drivesdk",
        "filename": "الفيزياء الحديثة للثالث الثانوي ـ موقع الفريد في الفيزياء.pdf",
        "kind": "textbook",
        "term_id": 2,
        "mappings": [(20,2,31),(21,32,73),(22,74,80),(23,81,107)],
    },
}


def _authorize(request: Request) -> None:
    expected = os.getenv("CONTENT_MAINTENANCE_TOKEN", "").strip()
    supplied = request.headers.get("x-content-maintenance-token", "").strip()
    if (
        os.getenv("VERCEL_ENV", "").strip().lower() != "production"
        or os.getenv("RELEASE_GIT_REF", "").strip() != "main"
        or str(os.getenv("CONTENT_INGESTION_ENABLED", "")).strip().lower()
        not in {"1", "true", "yes", "on"}
        or not expected
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(status_code=404, detail="Not found")


def _source_config(source_key: str) -> dict:
    source = SOURCES.get(source_key)
    if not source:
        raise HTTPException(404, "Not found")
    return source


def _assert_source_document(source_key: str, document_id: int) -> dict:
    source = _source_config(source_key)
    with connect() as con:
        row = con.execute(
            """SELECT d.id,d.filename,d.kind,d.status,d.storage_url,d.term_id,
                      f.page_count,f.file_sha256
               FROM documents d
               JOIN document_files f ON f.document_id=d.id
               WHERE d.id=%s""",
            (document_id,),
        ).fetchone()
    if not row or str(row["storage_url"] or "") != source["url"]:
        raise HTTPException(409, "Maintenance source/document mismatch")
    return dict(row)


@app.post("/api/internal/content-maintenance/source/{source_key}/register", include_in_schema=False)
def content_maintenance_register(source_key: str, request: Request):
    _authorize(request)
    source = _source_config(source_key)
    raw = _download_drive_pdf(source["url"])
    stored = _store_explanatory_pdf(
        raw,
        source["filename"],
        source["url"],
        source["kind"],
        int(source["term_id"]),
    )
    return {
        "source": source_key,
        "document": dict(stored["document"]),
        "duplicate": bool(stored.get("duplicate")),
        "auto_approved": False,
    }


@app.post("/api/internal/content-maintenance/source/{source_key}/extract", include_in_schema=False)
def content_maintenance_extract(
    source_key: str,
    document_id: int,
    start_page: int,
    request: Request,
):
    _authorize(request)
    document = _assert_source_document(source_key, document_id)
    row = _extract_source_page_batch(document_id, max(int(start_page), 1), 15)
    return {"source": source_key, "document_id": document_id, **row}


@app.post("/api/internal/content-maintenance/source/{source_key}/map", include_in_schema=False)
def content_maintenance_map(source_key: str, document_id: int, request: Request):
    _authorize(request)
    _assert_source_document(source_key, document_id)
    source = _source_config(source_key)
    results = []
    for lesson_id, start_page, end_page in source["mappings"]:
        draft = map_lesson_source(
            document_id,
            LessonSourceMap(
                lesson_id=int(lesson_id),
                start_page=int(start_page),
                end_page=int(end_page),
            ),
        )
        mapping = dict(draft["mapping"])
        approved = approve_lesson_source(int(mapping["id"]))
        results.append(
            {
                "mapping_id": int(mapping["id"]),
                "lesson_id": int(lesson_id),
                "start_page": int(start_page),
                "end_page": int(end_page),
                "approved": approved["mapping"]["mapping_status"] == "approved",
            }
        )
    return {
        "source": source_key,
        "document_id": document_id,
        "mappings": results,
        "all_approved": all(x["approved"] for x in results),
    }


@app.post("/api/internal/content-maintenance/visual-batch", include_in_schema=False)
def content_maintenance_visual_batch(request: Request, limit: int = 5):
    _authorize(request)
    bounded = min(max(int(limit), 1), 5)
    rows = [x for x in _queue_rows(250) if not x.get("suggestion")][:bounded]
    results = []
    for row in rows:
        qid = int(row["id"])
        try:
            result = generate_visual_suggestion(qid)
            suggestion = result.get("suggestion") or {}
            results.append(
                {
                    "question_id": qid,
                    "status": "suggested",
                    "confidence": suggestion.get("confidence"),
                    "uncertain_parts": len(suggestion.get("uncertain_parts") or []),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "question_id": qid,
                    "status": "error",
                    "error": type(exc).__name__,
                    "detail": str(exc)[:300],
                }
            )
    queue = _queue_rows(250)
    return {
        "processed": len(results),
        "remaining_without_suggestion": sum(1 for x in queue if not x.get("suggestion")),
        "with_suggestion": sum(1 for x in queue if x.get("suggestion")),
        "results": results,
        "auto_approved": False,
    }




@app.get("/api/internal/content-maintenance/visual-pending", include_in_schema=False)
def content_maintenance_visual_pending(request: Request):
    _authorize(request)
    rows = _queue_rows(250)
    return {
        "question_ids": [int(x["id"]) for x in rows if not x.get("suggestion")],
        "remaining_without_suggestion": sum(1 for x in rows if not x.get("suggestion")),
        "with_suggestion": sum(1 for x in rows if x.get("suggestion")),
    }


@app.post("/api/internal/content-maintenance/visual/{question_id}", include_in_schema=False)
def content_maintenance_visual_one(question_id: int, request: Request):
    _authorize(request)
    try:
        result = generate_visual_suggestion(int(question_id))
        suggestion = result.get("suggestion") or {}
        return {
            "question_id": int(question_id),
            "status": "suggested",
            "confidence": suggestion.get("confidence"),
            "uncertain_parts": len(suggestion.get("uncertain_parts") or []),
            "auto_approved": False,
        }
    except HTTPException as exc:
        return {
            "question_id": int(question_id),
            "status": "error",
            "error": str(exc.detail),
            "auto_approved": False,
        }


@app.get("/api/internal/content-maintenance/status", include_in_schema=False)
def content_maintenance_status(request: Request):
    _authorize(request)
    snapshot = content_completion_snapshot()
    queue = _queue_rows(250)
    return {
        "content_complete": snapshot.get("content_complete"),
        "source_coverage": snapshot.get("source_coverage"),
        "qa_open_by_reason": snapshot.get("qa_open_by_reason"),
        "covered_lessons": sum(
            1 for x in snapshot.get("lessons", []) if x.get("covered")
        ),
        "total_lessons": len(snapshot.get("lessons", [])),
        "visual_queue": {
            "total": len(queue),
            "with_suggestion": sum(1 for x in queue if x.get("suggestion")),
            "without_suggestion": sum(1 for x in queue if not x.get("suggestion")),
        },
        "ai_providers": provider_status(),
        "ai_models": {
            "gemini_visual_primary": model_settings()["gemini_lesson_studio"],
            "gemini_visual_fallbacks": [
                x.strip()
                for x in os.getenv(
                    "VISUAL_REVIEW_GEMINI_FALLBACK_MODELS",
                    "gemini-3.5-flash-lite,gemini-2.5-flash-lite",
                ).split(",")
                if x.strip()
            ],
            "openai_visual_fallback": model_settings()["openai_visual_fallback"],
        },
        "policy": "source_grounded_only_no_visual_auto_approval",
    }
