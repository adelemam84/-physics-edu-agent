from __future__ import annotations

import json
import os
from pathlib import Path

from app.content_completion import (
    _download_drive_pdf,
    _extract_source_page_batch,
    _store_explanatory_pdf,
    content_completion_snapshot,
)
from app.lesson_sources import LessonSourceMap, approve_lesson_source, map_lesson_source
from app.visual_review_assistant import _queue_rows, generate_visual_suggestion

TERM_ID = 2
SOURCES = [
    {
        "name": "electrical-magnetism",
        "url": "https://drive.google.com/file/d/195PEdaVl-in1SXud-lZv3JKycXJ1y6GN/view?usp=drivesdk",
        "filename": "الفيزياء الكهربية-رامي ماهر.pdf",
        "kind": "textbook",
        "mappings": [(14,5,18),(15,19,27),(16,28,36),(17,40,68),(18,70,105),(19,107,125)],
    },
    {
        "name": "modern-physics",
        "url": "https://drive.google.com/file/d/19kBzJp8OeLRqVNtHb2Uk8s-XUPTg1h92/view?usp=drivesdk",
        "filename": "الفيزياء الحديثة للثالث الثانوي ـ موقع الفريد في الفيزياء.pdf",
        "kind": "textbook",
        "mappings": [(20,1,31),(21,32,73),(22,74,80),(23,81,107)],
    },
]

def extract_all(document_id: int, page_count: int) -> dict:
    processed=0; blanks=[]; start=1
    while start<=page_count:
        row=_extract_source_page_batch(document_id,start,15)
        processed+=int(row.get("processed") or 0)
        blanks.extend(int(x) for x in (row.get("blank_pages") or []))
        if row.get("complete"): break
        start+=15
    return {"processed":processed,"blank_pages":sorted(set(blanks))}

def main() -> None:
    if str(os.getenv("CONTENT_INGESTION_ENABLED","")).lower() not in {"1","true","yes","on"}:
        raise SystemExit("CONTENT_INGESTION_ENABLED must be true")
    report={"sources":[],"visual_review":{},"policy":{"source_grounded_only":True,"no_visual_auto_approval":True}}
    for source in SOURCES:
        raw=_download_drive_pdf(source["url"])
        stored=_store_explanatory_pdf(raw,source["filename"],source["url"],source["kind"],TERM_ID)
        document=stored["document"]; document_id=int(document["id"]); page_count=int(document.get("page_count") or 0)
        extracted=extract_all(document_id,page_count)
        maps=[]
        for lesson_id,start_page,end_page in source["mappings"]:
            result=map_lesson_source(document_id,LessonSourceMap(lesson_id=lesson_id,start_page=start_page,end_page=end_page))
            mapping=result["mapping"]
            approved=approve_lesson_source(int(mapping["id"]))
            maps.append({"lesson_id":lesson_id,"start_page":start_page,"end_page":end_page,"mapping_id":int(mapping["id"]),"approved":approved["mapping"]["mapping_status"]=="approved"})
        report["sources"].append({"name":source["name"],"document_id":document_id,"duplicate":bool(stored.get("duplicate")),"page_count":page_count,"extracted":extracted,"mappings":maps})
    queue=_queue_rows(250); visual=[]
    for idx,row in enumerate(queue,1):
        qid=int(row["id"])
        if row.get("suggestion"):
            visual.append({"question_id":qid,"status":"already_suggested"}); continue
        try:
            result=generate_visual_suggestion(qid); suggestion=result.get("suggestion") or {}
            visual.append({"question_id":qid,"status":"suggested","confidence":suggestion.get("confidence"),"uncertain_parts":len(suggestion.get("uncertain_parts") or [])})
        except Exception as exc:
            visual.append({"question_id":qid,"status":"error","error":type(exc).__name__,"detail":str(exc)[:500]})
        if idx%10==0: print(f"visual review progress {idx}/{len(queue)}",flush=True)
    final_snapshot=content_completion_snapshot()
    report["visual_review"]={"queued_before":len(queue),"results":visual,"suggested":sum(1 for x in visual if x["status"] in {"suggested","already_suggested"}),"errors":sum(1 for x in visual if x["status"]=="error"),"auto_approved":False}
    report["final_snapshot"]={"content_complete":final_snapshot.get("content_complete"),"source_coverage":final_snapshot.get("source_coverage"),"qa_open_by_reason":final_snapshot.get("qa_open_by_reason"),"covered_lessons":sum(1 for x in final_snapshot.get("lessons",[]) if x.get("covered")),"total_lessons":len(final_snapshot.get("lessons",[]))}
    Path("edu001-edu003-maintenance-results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(json.dumps(report["final_snapshot"],ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
