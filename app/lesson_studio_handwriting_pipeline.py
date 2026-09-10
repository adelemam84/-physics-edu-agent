from __future__ import annotations

from fastapi import Depends

from .lesson_studio_quality import _build_quality_snapshot
from .main import app
from .security import require_admin
from .science_lesson_studio import _job
from .services.handwriting_confidence import build_confidence_map, golden_page_contract, subject_profile


def _pipeline_stage(stage_id: str, label: str, ok: bool, tab: str, detail: str) -> dict:
    """Build one deterministic handwriting-to-PDF stage without changing lesson state."""
    return {
        "id": stage_id,
        "label": label,
        "ok": bool(ok),
        "tab": tab,
        "detail": detail,
    }


def handwriting_pipeline_snapshot(job_id: str) -> dict:
    """Describe the exact source-preserving path from handwriting to final PDF readiness."""
    row, sources = _job(job_id)
    structured = dict(row.get("structured_json") or {})
    source_items = []
    total_review_lines = 0
    for source in sources:
        cmap = build_confidence_map(
            str(source.get("extracted_text") or ""),
            float(source.get("confidence") or 0.0),
            list(source.get("ocr_conflicts") or []),
        )
        total_review_lines += int(cmap["summary"]["review_required"])
        source_items.append({
            "id": source["id"],
            "position": source["position"],
            "filename": source["filename"],
            "confidence_band": source.get("ocr_confidence_band"),
            "source_requires_review": bool(source.get("requires_review")),
            "confidence_map": cmap,
        })

    diagrams = list(structured.get("diagram_specs") or [])
    quality = _build_quality_snapshot(job_id, dict(row), [dict(x) for x in sources])
    checks = {item["id"]: item for item in quality.get("checks") or []}

    source_preserved = bool((checks.get("source_preserved") or {}).get("ok"))
    transcript_bound = bool((checks.get("source_transcript_binding") or {}).get("ok"))
    ocr_clear = bool((checks.get("ocr_review_clear") or {}).get("ok"))
    structured_ready = bool((checks.get("structured_content_ready") or {}).get("ok"))
    preapproval_ready = bool(quality.get("preapproval_ready"))
    teacher_approval_fresh = bool(quality.get("teacher_approval_fresh"))
    final_export_ready = bool(quality.get("final_ready"))

    stages = [
        _pipeline_stage(
            "source_preserved",
            "حفظ المصدر الأصلي",
            source_preserved,
            "ocr",
            "ملف/صور خط اليد الأصلية محفوظة كمصدر مرجعي.",
        ),
        _pipeline_stage(
            "ocr_review",
            "مراجعة قراءة خط اليد وOCR",
            transcript_bound and ocr_clear,
            "ocr",
            "كل النصوص مرتبطة بالمصادر الحالية ولا توجد صفحات OCR معلقة.",
        ),
        _pipeline_stage(
            "structured_note",
            "تنظيم الشرح إلى مذكرة دراسية",
            structured_ready,
            "content",
            "تم إنشاء المحتوى المنظم من النص المراجع مع الاحتفاظ بالمصدر.",
        ),
        _pipeline_stage(
            "scientific_quality",
            "بوابات الجودة العلمية والبصرية",
            preapproval_ready,
            "quality",
            "المعادلات والرسومات والمصادر والعناصر غير الواضحة اجتازت البوابات المطلوبة.",
        ),
        _pipeline_stage(
            "teacher_approval",
            "اعتماد المدرس للنسخة الحالية",
            teacher_approval_fresh,
            "quality",
            "الاعتماد مربوط بالـcontent hash والرسومات الحالية وليس اعتمادًا قديمًا.",
        ),
        _pipeline_stage(
            "pdf_export_ready",
            "جاهزية تصدير PDF",
            final_export_ready,
            "quality",
            "يمكن تصدير نسخة A4 أو Mobile فقط بعد اكتمال جميع البوابات السابقة.",
        ),
    ]
    next_action = next((stage for stage in stages if not stage["ok"]), None)

    return {
        "job_id": job_id,
        "subject": row.get("subject"),
        "status": row.get("status"),
        "source_count": len(sources),
        "subject_profile": subject_profile(str(row.get("subject") or "science")),
        "sources": source_items,
        "stages": stages,
        "next_action": next_action,
        "summary": {
            "review_lines": total_review_lines,
            "uncertain_items": len(structured.get("uncertain_items") or []),
            "diagram_reviews": sum(
                1 for d in diagrams if (d.get("diagram_engine") or {}).get("review_required")
            ),
            "notation_reviews": int(
                (structured.get("notation_quality") or {}).get("review_required") or 0
            ),
            "study_note_ready_for_teacher_review": preapproval_ready,
            "teacher_approval_fresh": teacher_approval_fresh,
            "final_export_ready": final_export_ready,
        },
        "quality_gate": {
            "preapproval_ready": preapproval_ready,
            "teacher_approved": bool(quality.get("teacher_approved")),
            "teacher_approval_fresh": teacher_approval_fresh,
            "final_ready": final_export_ready,
            "checks": quality.get("checks") or [],
        },
        "golden_page_contract": golden_page_contract(),
        "pipeline": [
            "original_source_preserved",
            "ocr_derivative_preprocessed",
            "multimodal_transcription",
            "dual_provider_consensus_when_available",
            "line_confidence_map",
            "source_preserving_structuring",
            "subject_aware_diagram_strategy",
            "teacher_review",
            "quality_gate",
            "a4_or_mobile_pdf",
        ],
        "policy": {
            "no_silent_scientific_correction": True,
            "low_confidence_science_requires_teacher_review": True,
            "ai_generated_visuals_must_be_labeled": True,
            "teacher_is_final_gate": True,
            "pdf_requires_current_approval": True,
        },
    }


@app.get(
    "/api/admin/lesson-studio/jobs/{job_id}/handwriting-pipeline",
    dependencies=[Depends(require_admin)],
)
def handwriting_pipeline(job_id: str):
    """Expose the read-only handwriting-to-PDF readiness snapshot."""
    return handwriting_pipeline_snapshot(job_id)
