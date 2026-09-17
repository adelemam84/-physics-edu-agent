from __future__ import annotations

import copy
import hashlib
from typing import Any

CARD_FEATURE_SPECS = [
    {"card": 1, "capability": "professional_overview", "title": "عرض احترافي", "enabled": True},
    {"card": 2, "capability": "intro_activity", "title": "مقدمة وفعالية", "enabled": True},
    {"card": 3, "capability": "student_teaching", "title": "عرض تعليمي للطلاب", "enabled": True},
    {"card": 4, "capability": "visual_design", "title": "تصميم جذاب", "enabled": True},
    {"card": 5, "capability": "benefits_outcomes", "title": "فوائد ونتائج", "enabled": True},
    {"card": 6, "capability": "process_steps", "title": "خطوات التنفيذ", "enabled": True},
    {"card": 7, "capability": "notes_outline_map", "title": "ملاحظات إلى مخطط", "enabled": True},
    {"card": 8, "capability": "source_summary", "title": "تلخيص المصدر", "enabled": True},
    {"card": 9, "capability": "interactive_class", "title": "عرض تفاعلي", "enabled": True},
    {"card": 10, "capability": "audio_adapter_reserved", "title": "مدخل صوتي", "enabled": False, "status": "reserved_for_separate_review"},
    {"card": 11, "capability": "visual_assets", "title": "صور ورسومات", "enabled": True},
    {"card": 12, "capability": "storytelling", "title": "Storytelling", "enabled": True},
    {"card": 13, "capability": "objective_assessment", "title": "أهداف التعلم والتقييم", "enabled": True},
    {"card": 14, "capability": "bilingual", "title": "متعدد اللغات", "enabled": True},
    {"card": 15, "capability": "smart_diagrams", "title": "رموز ومخططات", "enabled": True},
    {"card": 16, "capability": "smart_tables", "title": "جداول احترافية", "enabled": True},
    {"card": 17, "capability": "quick_revision", "title": "تلخيص النقاط الأساسية", "enabled": True},
    {"card": 18, "capability": "text_to_slides", "title": "النص إلى شرائح", "enabled": True},
    {"card": 19, "capability": "speaker_notes", "title": "ملاحظات المتحدث", "enabled": True},
    {"card": 20, "capability": "branding_themes", "title": "تصميم وهوية احترافية", "enabled": True},
]

MODES = {
    "lesson_explanation",
    "exam_revision",
    "concept_summary",
    "quick_revision",
    "storytelling",
    "interactive_class",
    "process_steps",
    "question_driven",
}
AUDIENCES = {"student", "teacher", "classroom"}
LANGUAGES = {"ar", "en", "bilingual"}
LENGTHS = {"short": (6, 8), "medium": (10, 15), "full": (15, 25)}
THEMES = {"clean_academic", "exam_night", "visual_concept", "dark_classroom"}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _refs(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    return list(dict.fromkeys(str(x) for x in (item.get("source_refs") or []) if str(x).strip()))


def normalize_request(raw: dict | None) -> dict:
    raw = dict(raw or {})
    mode = str(raw.get("mode") or "lesson_explanation")
    audience = str(raw.get("audience") or "student")
    language = str(raw.get("language") or "ar")
    length = str(raw.get("length") or "medium")
    theme = str(raw.get("theme") or "clean_academic")
    if mode not in MODES:
        raise ValueError("unsupported presentation mode")
    if audience not in AUDIENCES:
        raise ValueError("unsupported presentation audience")
    if language not in LANGUAGES:
        raise ValueError("unsupported presentation language")
    if length not in LENGTHS:
        raise ValueError("unsupported presentation length")
    if theme not in THEMES:
        raise ValueError("unsupported presentation theme")
    include = dict(raw.get("include") or {})
    defaults = {
        "examples": True,
        "laws": True,
        "visuals": True,
        "tables": True,
        "activities": mode in {"interactive_class", "lesson_explanation"},
        "checkpoints": mode in {"interactive_class", "question_driven", "lesson_explanation", "exam_revision"},
        "speaker_notes": audience in {"teacher", "classroom"},
    }
    defaults.update({k: bool(v) for k, v in include.items() if k in defaults})
    return {
        "mode": mode,
        "audience": audience,
        "language": language,
        "length": length,
        "theme": theme,
        "include": defaults,
    }


def _block(kind: str, text: str, refs: list[str], **extra: Any) -> dict:
    out = {"kind": kind, "text": str(text or "").strip(), "source_refs": refs}
    out.update(extra)
    return out


def _slide(deck_id: str, order: int, kind: str, title: str, blocks: list[dict], refs: list[str], **extra: Any) -> dict:
    out = {
        "slide_id": _stable_id("slide", deck_id, order, kind, title),
        "order": order,
        "kind": kind,
        "title": title,
        "content_blocks": blocks,
        "source_refs": list(dict.fromkeys(refs)),
        "objective_ids": [],
        "visual_specs": [],
        "table_specs": [],
        "speaker_notes": [],
    }
    out.update(extra)
    return out


def _presentation_policy() -> dict:
    return {
        "artifact_kind": "lesson_presentation",
        "source_grounded_only": True,
        "official_question_bank_write": False,
        "generated_practice_questions_allowed": True,
        "question_bank_eligible": False,
        "teacher_approval_required_for_final_export": True,
        "student_answer_leakage_allowed": False,
        "generated_visuals_must_be_labeled": True,
        "content_ingestion_unchanged": True,
    }


def build_presentation_blueprint(pack: dict, request: dict | None = None, *, source_lesson_pack_id: str = "") -> dict:
    req = normalize_request(request)
    title = str(pack.get("title") or "Lesson Presentation")
    deck_id = _stable_id("deck", source_lesson_pack_id, title, req["mode"], req["audience"], req["language"], req["length"], req["theme"])
    objectives = [str(x).strip() for x in (pack.get("learning_objectives") or []) if str(x).strip()]
    objective_map = [{"objective_id": f"O{i}", "text": text} for i, text in enumerate(objectives, 1)]
    slides: list[dict] = []

    def add(kind: str, slide_title: str, blocks: list[dict], refs: list[str], **extra: Any) -> dict:
        item = _slide(deck_id, len(slides) + 1, kind, slide_title, blocks, refs, **extra)
        slides.append(item)
        return item

    add("cover", title, [_block("subtitle", str(pack.get("grade_label") or ""), [])], [])

    if objective_map:
        s = add("objectives", "أهداف التعلم", [_block("objective", x["text"], [], objective_id=x["objective_id"]) for x in objective_map], [])
        s["objective_ids"] = [x["objective_id"] for x in objective_map]

    summary = str(pack.get("summary") or "").strip()
    if summary:
        summary_refs = list(dict.fromkeys(ref for sec in (pack.get("sections") or []) if isinstance(sec, dict) for ref in _refs(sec)))
        add("hook" if req["mode"] == "storytelling" else "summary", "الفكرة الأساسية", [_block("text", summary, summary_refs)], summary_refs)

    sections = [x for x in (pack.get("sections") or []) if isinstance(x, dict)]
    for sec in sections:
        refs = _refs(sec)
        slide = add("concept", str(sec.get("heading") or "مفهوم"), [_block("text", str(sec.get("body") or ""), refs)], refs)
        if objective_map:
            slide["objective_ids"] = [objective_map[(len(slides) - 1) % len(objective_map)]["objective_id"]]

    if req["include"]["laws"]:
        laws = [x for x in (pack.get("equations_or_rules") or []) if isinstance(x, dict)]
        if laws:
            refs = list(dict.fromkeys(ref for x in laws for ref in _refs(x)))
            blocks = [_block("law", f"{x.get('label') or ''}: {x.get('expression') or ''}", _refs(x), notes=str(x.get("notes") or "")) for x in laws]
            s = add("laws", "القوانين والعلاقات", blocks, refs)
            if req["include"]["tables"]:
                s["table_specs"].append({"kind": "law_table", "columns": ["label", "expression", "notes"], "rows": [{"label": str(x.get("label") or ""), "expression": str(x.get("expression") or ""), "notes": str(x.get("notes") or ""), "source_refs": _refs(x)} for x in laws]})

    if req["include"]["examples"]:
        for ex in [x for x in (pack.get("worked_examples") or []) if isinstance(x, dict)]:
            refs = _refs(ex)
            blocks = [_block("problem", str(ex.get("problem") or ""), refs)]
            for step in ex.get("solution_steps") or []:
                blocks.append(_block("solution_step", str(step), refs, teacher_only=False))
            blocks.append(_block("answer", str(ex.get("answer") or ""), refs, teacher_only=True))
            add("worked_example", str(ex.get("title") or "مثال محلول"), blocks, refs)

    if req["include"]["visuals"]:
        approved = [x for x in (pack.get("source_visuals") or []) if isinstance(x, dict) and x.get("approved") and x.get("object_key")]
        if approved:
            refs = list(dict.fromkeys(ref for x in approved for ref in _refs(x)))
            s = add("source_visuals", "صور ورسومات من المصدر", [], refs)
            s["visual_specs"] = [{"kind": "source_visual", "title": str(x.get("title") or ""), "object_key": x.get("object_key"), "source_refs": _refs(x), "approved": True, "generated": False} for x in approved]
        diagrams = [x for x in (pack.get("diagram_specs") or []) if isinstance(x, dict)]
        if diagrams:
            refs = list(dict.fromkeys(ref for x in diagrams for ref in _refs(x)))
            s = add("diagram_specs", "مخططات توضيحية", [], refs)
            s["visual_specs"] += [{"kind": str(x.get("kind") or "other"), "title": str(x.get("title") or ""), "description": str(x.get("description") or ""), "source_refs": _refs(x), "generated": True, "label": "generated_visual"} for x in diagrams]

    questions = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    if req["include"]["checkpoints"] and questions:
        selected = questions[: min(3, len(questions))]
        refs = list(dict.fromkeys(ref for x in selected for ref in _refs(x)))
        blocks = []
        for q in selected:
            blocks.append(_block("checkpoint", str(q.get("prompt") or ""), _refs(q), question_id=str(q.get("id") or ""), official_question_bank=False, question_bank_eligible=False))
            blocks.append(_block("answer", str(q.get("answer") or ""), _refs(q), question_id=str(q.get("id") or ""), teacher_only=True))
            blocks.append(_block("explanation", str(q.get("explanation") or ""), _refs(q), question_id=str(q.get("id") or ""), teacher_only=True))
        add("checkpoint", "توقف واختبر فهمك", blocks, refs)

    if req["include"]["activities"]:
        refs = list(dict.fromkeys(ref for sec in sections[:2] for ref in _refs(sec)))
        add("activity", "نشاط صفي", [_block("activity_prompt", "ناقش الفكرة الأساسية مع زميلك ثم اربطها بمثال من الشريحة السابقة.", refs, generated=True, official_question_bank=False)], refs)

    mistakes = [x for x in (pack.get("common_mistakes") or []) if isinstance(x, dict)]
    if mistakes:
        refs = list(dict.fromkeys(ref for x in mistakes for ref in _refs(x)))
        add("common_mistakes", "أخطاء شائعة", [_block("mistake", str(x.get("text") or ""), _refs(x)) for x in mistakes], refs)

    revision = [x for x in (pack.get("quick_revision") or []) if isinstance(x, dict)]
    if revision:
        refs = list(dict.fromkeys(ref for x in revision for ref in _refs(x)))
        add("recap", "مراجعة سريعة", [_block("revision", str(x.get("text") or ""), _refs(x)) for x in revision], refs)

    if req["mode"] == "process_steps":
        for slide in slides:
            if slide["kind"] == "concept":
                slide["kind"] = "process_step"
    elif req["mode"] == "quick_revision":
        keep = {"cover", "objectives", "summary", "laws", "common_mistakes", "recap", "checkpoint"}
        slides = [x for x in slides if x["kind"] in keep]
    elif req["mode"] == "question_driven":
        slides = [x for x in slides if x["kind"] in {"cover", "objectives", "checkpoint", "laws", "recap"}]

    if req["audience"] in {"teacher", "classroom"} and req["include"]["speaker_notes"]:
        for slide in slides:
            slide["speaker_notes"] = [f"قدّم الشريحة «{slide['title']}» تدريجيًا، واطلب من الطلاب تفسير ما يظهر قبل الانتقال للنقطة التالية."]

    if req["language"] == "bilingual":
        for slide in slides:
            slide["translation_required"] = True
            for block in slide["content_blocks"]:
                block["semantic_pair"] = {"ar": block.get("text", ""), "en": None}

    for i, slide in enumerate(slides, 1):
        slide["order"] = i

    blueprint = {
        "deck_id": deck_id,
        "source_lesson_pack_id": source_lesson_pack_id,
        "title": title,
        "subject": str(pack.get("subject") or ""),
        "grade_label": str(pack.get("grade_label") or ""),
        "request": req,
        "objectives": objective_map,
        "slides": slides,
        "feature_capabilities": [x["capability"] for x in CARD_FEATURE_SPECS if x.get("enabled")],
        "generated_content_policy": _presentation_policy(),
        "approval_state": {"teacher_approved": False, "revision": 1},
    }
    blueprint["preflight"] = presentation_preflight(blueprint)
    return blueprint


def project_edition(blueprint: dict, edition: str) -> dict:
    if edition not in {"student", "teacher"}:
        raise ValueError("edition must be student or teacher")
    out = copy.deepcopy(blueprint)
    out["edition"] = edition
    for slide in out.get("slides") or []:
        if edition == "student":
            slide["speaker_notes"] = []
            slide["content_blocks"] = [b for b in (slide.get("content_blocks") or []) if not b.get("teacher_only")]
        else:
            slide["content_blocks"] = list(slide.get("content_blocks") or [])
    out["preflight"] = presentation_preflight(out, edition=edition)
    return out


def presentation_preflight(blueprint: dict, *, edition: str | None = None) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    slides = [x for x in (blueprint.get("slides") or []) if isinstance(x, dict)]
    ids = [str(x.get("slide_id") or "") for x in slides]
    if not slides:
        blockers.append("slides_present")
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        blockers.append("unique_slide_ids")
    policy = blueprint.get("generated_content_policy") or {}
    if policy.get("official_question_bank_write") is not False or policy.get("content_ingestion_unchanged") is not True:
        blockers.append("presentation_policy")

    for slide in slides:
        if not str(slide.get("title") or "").strip():
            blockers.append("slide_titles")
            break
        for block in slide.get("content_blocks") or []:
            if block.get("kind") in {"text", "law", "problem", "solution_step", "answer", "explanation", "checkpoint", "mistake", "revision"} and not block.get("source_refs"):
                blockers.append("source_grounding")
                break

    objective_ids = {x.get("objective_id") for x in (blueprint.get("objectives") or []) if isinstance(x, dict)}
    covered = {oid for slide in slides for oid in (slide.get("objective_ids") or [])}
    if blueprint.get("request", {}).get("mode") in {"lesson_explanation", "interactive_class", "storytelling"} and objective_ids - covered:
        blockers.append("objective_coverage")

    language = blueprint.get("request", {}).get("language")
    if language == "bilingual":
        untranslated = any(block.get("semantic_pair", {}).get("en") is None for slide in slides for block in (slide.get("content_blocks") or []) if block.get("semantic_pair"))
        if untranslated:
            blockers.append("bilingual_translation_complete")

    if edition == "student":
        if any(slide.get("speaker_notes") for slide in slides):
            blockers.append("student_speaker_notes_leak")
        if any(block.get("teacher_only") for slide in slides for block in (slide.get("content_blocks") or [])):
            blockers.append("student_answer_leak")

    target = LENGTHS.get(str(blueprint.get("request", {}).get("length") or "medium"), LENGTHS["medium"])
    if len(slides) < max(3, target[0] - 3) or len(slides) > target[1] + 5:
        warnings.append("slide_count_outside_soft_target")
    if any(len(str(block.get("text") or "")) > 700 for slide in slides for block in (slide.get("content_blocks") or [])):
        warnings.append("high_text_density")

    return {
        "ready": not blockers,
        "blocking_failures": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "slide_count": len(slides),
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }
