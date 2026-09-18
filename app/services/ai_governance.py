from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Literal

from .provider_http import retry_snapshot


Provider = Literal["gemini", "openai", "mathpix", "deterministic"]


@dataclass(frozen=True)
class AITaskPolicy:
    """One explicit execution contract for an AI-assisted or deterministic task."""

    task: str
    label_ar: str
    provider: Provider
    model: str | None
    mode: str
    ready: bool
    source_grounded: bool
    advisory_only: bool
    can_write_question_bank: bool
    can_auto_approve: bool
    can_publish: bool
    human_gate: str
    reasoning_effort: str | None = None
    notes_ar: str = ""


def _value(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _review_effort() -> str:
    raw = _value("LESSON_STUDIO_REVIEW_REASONING_EFFORT", "high").lower()
    return raw if raw in {"low", "medium", "high", "xhigh", "max"} else "high"


def model_settings() -> dict:
    """Return secret-free model configuration used across the platform."""
    return {
        "gemini_research": _value("GEMINI_RESEARCH_MODEL", "gemini-2.5-flash"),
        "gemini_lesson_studio": _value(
            "LESSON_STUDIO_GEMINI_MODEL",
            _value("GEMINI_RESEARCH_MODEL", "gemini-2.5-flash"),
        ),
        "openai_scientific_reviewer": _value("LESSON_STUDIO_REVIEW_MODEL", "gpt-5.6-sol"),
        "openai_scientific_reviewer_reasoning": _review_effort(),
        "openai_visual_fallback": _value("VISUAL_REVIEW_OPENAI_MODEL", "gpt-5.6-terra"),
        "gemini_file_search_embedding": _value(
            "GEMINI_FILE_SEARCH_EMBEDDING_MODEL",
            "models/gemini-embedding-2",
        ),
    }


def provider_status() -> dict:
    """Return provider readiness without exposing keys, tokens, or credentials."""
    gemini = bool(os.getenv("GEMINI_API_KEY", "").strip())
    openai = bool(os.getenv("OPENAI_API_KEY", "").strip())
    mathpix = bool(
        os.getenv("MATHPIX_APP_ID", "").strip()
        and os.getenv("MATHPIX_APP_KEY", "").strip()
    )
    file_search = bool(os.getenv("GEMINI_FILE_SEARCH_STORE", "").strip())
    return {
        "gemini": {
            "configured": gemini,
            "file_search_configured": file_search,
            "role": "source_pdf_multimodal_and_research",
        },
        "openai": {
            "configured": openai,
            "role": "independent_high_stakes_scientific_review",
        },
        "mathpix": {
            "configured": mathpix,
            "role": "optional_stem_ocr_verifier",
        },
        "deterministic": {
            "configured": True,
            "role": "grading_selection_integrity_and_diagram_rendering",
        },
    }


def task_policies() -> tuple[AITaskPolicy, ...]:
    """Central source of truth for model-to-task routing and release authority."""
    models = model_settings()
    providers = provider_status()
    gemini_ready = bool(providers["gemini"]["configured"])
    openai_ready = bool(providers["openai"]["configured"])
    free_only = os.getenv("PROJECT_FREE_ONLY", "true").strip().lower() in {"1","true","yes","on"}
    mathpix_ready = bool(providers["mathpix"]["configured"])
    gemini_model = str(models["gemini_research"])
    lesson_model = str(models["gemini_lesson_studio"])
    review_model = str(models["openai_scientific_reviewer"])

    return (
        AITaskPolicy(
            task="source_analysis",
            label_ar="تحليل مصدر PDF",
            provider="gemini",
            model=gemini_model,
            mode="exact_pdf_or_file_search",
            ready=gemini_ready,
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="source_review",
            notes_ar="للبحث والفهم داخل المصدر فقط؛ لا ينشئ حقيقة علمية خارج PDF.",
        ),
        AITaskPolicy(
            task="lesson_support",
            label_ar="دعم شرح الدرس من المصدر",
            provider="gemini",
            model=gemini_model,
            mode="approved_source_context",
            ready=gemini_ready,
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="teacher_review",
            notes_ar="يشرح أو يلخص من المصدر المعتمد ولا يستبدل المصدر.",
        ),
        AITaskPolicy(
            task="question_review",
            label_ar="مراجعة سؤال من المصدر",
            provider="gemini",
            model=gemini_model,
            mode="exact_pdf_pages",
            ready=gemini_ready,
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="question_qa",
            notes_ar="النص الأصلي للسؤال يبقى حرفيًا ولا يتم اعتماده آليًا.",
        ),
        AITaskPolicy(
            task="visual_review",
            label_ar="قراءة سؤال أو رسم مرئي",
            provider="gemini",
            model=lesson_model,
            mode="exact_source_image_free_tier_gemini" if free_only else "exact_source_image_gemini_with_openai_fallback",
            ready=gemini_ready if free_only else bool(gemini_ready or openai_ready),
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="visual_transcription_review",
            notes_ar=("يقرأ صورة المصدر فقط عبر Gemini Free Tier؛ أي fallback مدفوع محظور، وأي جزء غير واضح يظل للمراجعة."
                      if free_only else
                      "يقرأ صورة المصدر فقط؛ Gemini أساسي وOpenAI fallback عند تعطل المزود/Rate Limit فقط، وأي جزء غير واضح يظل للمراجعة."),
        ),
        AITaskPolicy(
            task="handwriting_ocr_primary",
            label_ar="OCR أساسي لملاحظات المدرس",
            provider="gemini",
            model=lesson_model,
            mode="multimodal_verbatim_transcription",
            ready=gemini_ready,
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="ocr_review",
            notes_ar="ينسخ المعادلات والرموز دون تصحيح علمي من الذاكرة.",
        ),
        AITaskPolicy(
            task="handwriting_ocr_verifier",
            label_ar="OCR تحقق ثانٍ",
            provider="mathpix",
            model="mathpix-v3-text",
            mode="stem_ocr_verification",
            ready=mathpix_ready and not free_only,
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="ocr_conflict_review",
            notes_ar="اختياري؛ يستخدم لكشف التعارضات ولا يدمج قراءة علمية من نفسه.",
        ),
        AITaskPolicy(
            task="independent_scientific_review",
            label_ar="المراجع العلمي الثاني",
            provider="openai",
            model=review_model,
            mode="source_vs_structured_comparison",
            ready=openai_ready and not free_only,
            source_grounded=True,
            advisory_only=True,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="teacher_approval",
            reasoning_effort=str(models["openai_scientific_reviewer_reasoning"]),
            notes_ar="مراجعة عالية الدقة مستقلة عن محرك الاستخراج قبل اعتماد المدرس.",
        ),
        AITaskPolicy(
            task="grading",
            label_ar="تصحيح الإجابات",
            provider="deterministic",
            model=None,
            mode="validated_rules",
            ready=True,
            source_grounded=True,
            advisory_only=False,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="grading_contract",
            notes_ar="لا نستخدم LLM في القرار النهائي للدرجة لتقليل عدم الحتمية.",
        ),
        AITaskPolicy(
            task="adaptive_practice_selection",
            label_ar="اختيار التدريب التكيفي",
            provider="deterministic",
            model=None,
            mode="mastery_rules",
            ready=True,
            source_grounded=True,
            advisory_only=False,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="approved_question_filter",
            notes_ar="الاختيار من الأسئلة المعتمدة فقط بناءً على أداء الطالب.",
        ),
        AITaskPolicy(
            task="scientific_diagram_rendering",
            label_ar="رسم المخططات العلمية",
            provider="deterministic",
            model=None,
            mode="validated_parameterized_renderer",
            ready=True,
            source_grounded=True,
            advisory_only=False,
            can_write_question_bank=False,
            can_auto_approve=False,
            can_publish=False,
            human_gate="diagram_teacher_review",
            notes_ar="المعلمات العلمية تُراجع وتُربط ببصمة الإصدار قبل التصدير.",
        ),
    )


def get_task_policy(task: str) -> AITaskPolicy:
    for policy in task_policies():
        if policy.task == task:
            return policy
    raise KeyError(task)


def governance_snapshot() -> dict:
    """Build the admin-facing AI operations contract."""
    free_only = os.getenv("PROJECT_FREE_ONLY", "true").strip().lower() in {"1","true","yes","on"}
    providers = provider_status()
    tasks = [asdict(x) for x in task_policies()]
    recommendations: list[dict] = []

    if not providers["gemini"]["configured"]:
        recommendations.append({
            "priority": "required_for_ai_source_tools",
            "title_ar": "إعداد مفتاح Gemini",
            "reason_ar": "محرك PDF والمرئيات وOCR الأساسي لن يعمل بدون المفتاح.",
        })
    elif not providers["gemini"]["file_search_configured"]:
        recommendations.append({
            "priority": "recommended",
            "title_ar": "استكمال Gemini File Search Store",
            "reason_ar": "يحسن البحث في المصادر الكبيرة مع إبقاء المراجعة الدقيقة على الصفحات الأصلية.",
        })

    if not free_only and not providers["openai"]["configured"]:
        recommendations.append({
            "priority": "recommended_high_stakes",
            "title_ar": "إعداد مفتاح OpenAI",
            "reason_ar": "يفعّل المراجع العلمي الثاني المستقل قبل اعتماد المدرس.",
        })

    if not providers["mathpix"]["configured"]:
        recommendations.append({
            "priority": "optional",
            "title_ar": "Mathpix اختياري",
            "reason_ar": "يفيد كمراجع OCR ثانٍ للمعادلات المكتوبة في الصور، وليس شرطًا لتشغيل المنصة.",
        })

    recommendations.append({
        "priority": "architecture",
        "title_ar": "احتفظ بالنماذج التوليدية في الدور الاستشاري",
        "reason_ar": "الاعتماد والنشر والدرجة النهائية يجب أن تبقى خلف بوابات حتمية/بشرية.",
    })
    if free_only:
        recommendations.append({
            "priority": "free_only",
            "title_ar": "الاستمرار على Gemini Free Tier",
            "reason_ar": "المشروع يحظر المزودات المدفوعة افتراضيًا ويستخدم Gemini 2.5 Flash/Flash-Lite فقط في المسارات المسموح بها.",
        })
    else:
        recommendations.append({
            "priority": "cost_quality",
            "title_ar": "استخدم GPT-5.6 Sol فقط للمراجعات عالية المخاطر",
            "reason_ar": "لا حاجة لاستهلاكه في اختيار التدريب أو التصحيح أو كل تفاعل طالب.",
        })

    return {
        "schema_version": "1.1",
        "models": model_settings(),
        "provider_resilience": retry_snapshot(),
        "providers": providers,
        "tasks": tasks,
        "summary": {
            "task_count": len(tasks),
            "ready_tasks": sum(1 for x in tasks if x["ready"]),
            "blocked_tasks": sum(1 for x in tasks if not x["ready"]),
            "source_grounded_tasks": sum(1 for x in tasks if x["source_grounded"]),
            "auto_approval_tasks": sum(1 for x in tasks if x["can_auto_approve"]),
            "auto_publish_tasks": sum(1 for x in tasks if x["can_publish"]),
            "question_bank_write_tasks": sum(1 for x in tasks if x["can_write_question_bank"]),
        },
        "principles": {
            "project_free_only": free_only,
            "paid_ai_fallbacks_disabled_when_free_only": free_only,
            "pdf_is_scientific_source_of_truth": True,
            "question_text_verbatim_when_source_question": True,
            "no_model_can_auto_approve_scientific_content": True,
            "no_model_can_auto_publish_scientific_content": True,
            "grading_final_decision_is_deterministic": True,
            "adaptive_selection_uses_approved_questions_only": True,
            "independent_review_is_separate_from_source_extraction": True,
            "provider_retries_never_change_model_role": True,
            "visual_review_fallback_preserves_exact_source_image": True,
            "provider_resource_mutations_are_not_auto_replayed": True,
        },
        "recommendations": recommendations,
    }
