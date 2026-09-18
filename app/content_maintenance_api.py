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
from .lesson_sources import LessonSourceMap, approve_lesson_source, map_lesson_source
from .main import app
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
        "mappings": [(20,1,31),(21,32,73),(22,74,80),(23,81,107)],
    },
}


def _authorize(request: Request) -> None:
    expected=os.getenv("CONTENT_MAINTENANCE_TOKEN","").strip()
    supplied=request.headers.get("x-content-maintenance-token","").strip()
    if (
        os.getenv("VERCEL_ENV","").strip().lower() != "production"
        or os.getenv("RELEASE_GIT_REF","").strip() != "main"
        or str(os.getenv("CONTENT_INGESTION_ENABLED","")).strip().lower() not in {"1","true","yes","on"}
        or not expected or not supplied or not hmac.compare_digest(expected,supplied)
    ):
        raise HTTPException(status_code=404, detail="Not found")


def _extract_all(document_id:int,page_count:int) -> dict:
    processed=0
    blank_pages=[]
    start=1
    while start<=page_count:
        row=_extract_source_page_batch(document_id,start,15)
        processed+=int(row.get("processed") or 0)
        blank_pages.extend(int(x) for x in (row.get("blank_pages") or []))
        if row.get("complete"):
            break
        start+=15
    return {"processed":processed,"blank_pages":sorted(set(blank_pages))}


def _execute_source(key:str) -> dict:
    source=SOURCES[key]
    raw=_download_drive_pdf(source["url"])
    stored=_store_explanatory_pdf(
        raw,source["filename"],source["url"],source["kind"],int(source["term_id"])
    )
    document=dict(stored["document"])
    document_id=int(document["id"])
    page_count=int(document.get("page_count") or 0)
    extracted=_extract_all(document_id,page_count)
    mappings=[]
    for lesson_id,start_page,end_page in source["mappings"]:
        draft=map_lesson_source(
            document_id,
            LessonSourceMap(
                lesson_id=int(lesson_id),
                start_page=int(start_page),
                end_page=int(end_page),
            ),
        )
        mapping=dict(draft["mapping"])
        approved=approve_lesson_source(int(mapping["id"]))
        mappings.append({
            "mapping_id":int(mapping["id"]),
            "lesson_id":int(lesson_id),
            "start_page":int(start_page),
            "end_page":int(end_page),
            "approved":approved["mapping"]["mapping_status"]=="approved",
        })
    return {
        "source":key,
        "document_id":document_id,
        "duplicate":bool(stored.get("duplicate")),
        "page_count":page_count,
        "extracted":extracted,
        "mappings":mappings,
    }


@app.post("/api/internal/content-maintenance/source/{source_key}", include_in_schema=False)
def content_maintenance_source(source_key:str,request:Request):
    _authorize(request)
    if source_key not in SOURCES:
        raise HTTPException(404,"Not found")
    return _execute_source(source_key)


@app.post("/api/internal/content-maintenance/visual-batch", include_in_schema=False)
def content_maintenance_visual_batch(request:Request,limit:int=5):
    _authorize(request)
    bounded=min(max(int(limit),1),5)
    rows=[x for x in _queue_rows(250) if not x.get("suggestion")][:bounded]
    results=[]
    for row in rows:
        qid=int(row["id"])
        try:
            result=generate_visual_suggestion(qid)
            suggestion=result.get("suggestion") or {}
            results.append({
                "question_id":qid,
                "status":"suggested",
                "confidence":suggestion.get("confidence"),
                "uncertain_parts":len(suggestion.get("uncertain_parts") or []),
            })
        except Exception as exc:
            results.append({
                "question_id":qid,
                "status":"error",
                "error":type(exc).__name__,
                "detail":str(exc)[:300],
            })
    remaining=sum(1 for x in _queue_rows(250) if not x.get("suggestion"))
    return {
        "processed":len(results),
        "remaining_without_suggestion":remaining,
        "results":results,
        "auto_approved":False,
    }


@app.get("/api/internal/content-maintenance/status", include_in_schema=False)
def content_maintenance_status(request:Request):
    _authorize(request)
    snapshot=content_completion_snapshot()
    queue=_queue_rows(250)
    return {
        "content_complete":snapshot.get("content_complete"),
        "source_coverage":snapshot.get("source_coverage"),
        "qa_open_by_reason":snapshot.get("qa_open_by_reason"),
        "covered_lessons":sum(1 for x in snapshot.get("lessons",[]) if x.get("covered")),
        "total_lessons":len(snapshot.get("lessons",[])),
        "visual_queue":{
            "total":len(queue),
            "with_suggestion":sum(1 for x in queue if x.get("suggestion")),
            "without_suggestion":sum(1 for x in queue if not x.get("suggestion")),
        },
        "policy":"source_grounded_only_no_visual_auto_approval",
    }
