from __future__ import annotations

import copy
import json

from fastapi import HTTPException

from ..science_lesson_studio import _attach_diagram_engine, _gemini_text
from .lesson_pdf_renderer import render_lesson_pdf


def source_ref(page: dict) -> str:
    return (
        f"ملف {int(page['file_index'])}: {page['original_filename']} · "
        f"صفحة {int(page['original_page'])}"
    )


def allowed_source_refs(pages: list[dict]) -> list[str]:
    return [source_ref(page) for page in pages]


def _provenance_refs(pack: dict) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    collections = (
        ("sections", "sections"),
        ("worked_examples", "worked_examples"),
        ("practice_questions", "practice_questions"),
        ("key_terms", "key_terms"),
        ("equations_or_rules", "equations_or_rules"),
        ("diagram_specs", "diagram_specs"),
        ("common_mistakes", "common_mistakes"),
        ("quick_revision", "quick_revision"),
    )
    for field, label in collections:
        for i, item in enumerate(pack.get(field) or [], 1):
            if not isinstance(item, dict):
                continue
            for ref in item.get("source_refs") or []:
                refs.append((f"{label}[{i}]", str(ref)))
    return refs


def validate_pack_provenance(pack: dict, refs: list[str]) -> dict:
    allowed = set(refs)
    seen = _provenance_refs(pack)
    invalid = [{"location": loc, "ref": ref} for loc, ref in seen if ref not in allowed]
    missing: list[str] = []
    sections = pack.get("sections") or []
    questions = pack.get("practice_questions") or []
    if not sections:
        missing.append("sections")
    if not questions:
        missing.append("practice_questions")
    for i, question in enumerate(questions, 1):
        if not isinstance(question, dict) or not question.get("source_refs"):
            missing.append(f"practice_questions[{i}]")
    for i, section in enumerate(sections, 1):
        if not isinstance(section, dict) or not section.get("source_refs"):
            missing.append(f"sections[{i}]")
    for field in (
        "worked_examples",
        "key_terms",
        "equations_or_rules",
        "diagram_specs",
        "common_mistakes",
        "quick_revision",
    ):
        for i, item in enumerate(pack.get(field) or [], 1):
            if not isinstance(item, dict) or not item.get("source_refs"):
                missing.append(f"{field}[{i}]")
    return {
        "passed": bool(sections) and bool(questions) and not invalid and not missing,
        "allowed_ref_count": len(allowed),
        "referenced_ref_count": len(seen),
        "invalid_refs": invalid,
        "missing_refs": missing,
    }


def normalize_generated_questions(pack: dict) -> dict:
    out = dict(pack)
    normalized = []
    for index, raw in enumerate(pack.get("practice_questions") or [], 1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["id"] = str(item.get("id") or f"Q{index}")
        item["type"] = str(item.get("type") or "conceptual")
        difficulty = str(item.get("difficulty") or "medium").lower()
        item["difficulty"] = difficulty if difficulty in {"easy", "medium", "hard"} else "medium"
        options = item.get("options")
        item["options"] = [str(x) for x in options] if isinstance(options, list) else []
        item["source_refs"] = [str(x) for x in (item.get("source_refs") or [])]
        item["generated"] = True
        item["provenance"] = "ai_generated_source_grounded_practice"
        item["official_question_bank"] = False
        item["question_bank_eligible"] = False
        item["teacher_review_required"] = True
        normalized.append(item)
    out["practice_questions"] = normalized
    out["question_policy"] = {
        "generated_practice_only": True,
        "official_question_bank_write": False,
        "auto_publish": False,
        "teacher_review_required": True,
    }
    return out


def build_pack(
    transcript: str,
    *,
    title: str,
    subject: str,
    grade_label: str,
    pack_mode: str,
    refs: list[str],
    question_count: int,
) -> dict:
    question_count = max(6, min(30, int(question_count)))
    schema = {
        "title": "string",
        "subject": subject,
        "grade_label": grade_label,
        "mode": "student_simple",
        "pack_mode": pack_mode,
        "learning_objectives": ["string"],
        "sections": [
            {"heading": "string", "body": "string", "source_refs": ["EXACT_ALLOWED_SOURCE_REF"]}
        ],
        "key_terms": [
            {"term": "string", "definition": "string", "source_refs": ["EXACT_ALLOWED_SOURCE_REF"]}
        ],
        "equations_or_rules": [
            {
                "label": "string",
                "expression": "string",
                "notes": "string",
                "source_refs": ["EXACT_ALLOWED_SOURCE_REF"],
            }
        ],
        "worked_examples": [
            {
                "title": "string",
                "problem": "string",
                "solution_steps": ["string"],
                "answer": "string",
                "source_refs": ["EXACT_ALLOWED_SOURCE_REF"],
            }
        ],
        "common_mistakes": [
            {"text": "string", "source_refs": ["EXACT_ALLOWED_SOURCE_REF"]}
        ],
        "diagram_specs": [
            {
                "kind": "simple_circuit|graph|process|comparison|classification|vector|apparatus|ray_diagram|other",
                "title": "string",
                "description": "string",
                "scientific_labels": ["string"],
                "parameters": {"source_explicit_only": True},
                "deterministic_required": True,
                "source_refs": ["EXACT_ALLOWED_SOURCE_REF"],
            }
        ],
        "practice_questions": [
            {
                "id": "Q1",
                "type": "mcq|conceptual|calculation|explain|compare|true_false",
                "difficulty": "easy|medium|hard",
                "prompt": "string",
                "options": ["string"],
                "answer": "string",
                "explanation": "string",
                "source_refs": ["EXACT_ALLOWED_SOURCE_REF"],
            }
        ],
        "quick_revision": [
            {"text": "string", "source_refs": ["EXACT_ALLOWED_SOURCE_REF"]}
        ],
        "uncertain_items": ["string"],
        "summary": "string",
    }
    developer = (
        "أنت مصمم ومحرر ملزمة طالب عربية احترافية للحصة من مصدر مغلق. المنتج النهائي سيُطبع على A4 "
        "ويذاكر منه الطالب الدرس بعد الحصة؛ لذلك لا تكتب تقريرًا عن المصدر ولا ملخصًا آليًا جافًا. "
        "اكتب شرحًا تدريجيًا واضحًا ومريحًا للمذاكرة، بفقرات قصيرة وترتيب منطقي من الفكرة إلى القانون إلى التطبيق. "
        "استخدم فقط النص المرفق ولا تضف حقيقة علمية "
        "من الذاكرة أو الإنترنت. يجوز إعادة الشرح بأسلوب أوضح ومبتكر ما دام كل ادعاء مدعومًا بالمصدر. "
        "كل قسم وكل مثال وكل سؤال وكل قانون وكل رسم وكل خطأ شائع وكل نقطة مراجعة يجب أن يحمل "
        "source_refs من القائمة المسموح بها حرفيًا فقط. "
        "أنشئ أسئلة تدريبية جديدة مبنية على الدرس، لكنها ليست أسئلة رسمية ولا يجوز الادعاء أنها وردت "
        "بالنص الأصلي. لا تغيّر القوانين أو الوحدات. وإذا استخدمت أرقامًا تدريبية جديدة فاذكر داخل "
        "explanation أنها أرقام تدريبية مولدة وأن العلاقة المستخدمة مدعومة بالمصدر. "
        "اجعل learning_objectives بين 3 و6 أهداف عملية، واجعل sections تغطي الدرس كاملًا بعناوين قصيرة واضحة. "
        "استخرج أهم المصطلحات والقوانين، وأنشئ أمثلة محلولة عند وجود أساس علمي كافٍ في المصدر. "
        "اجعل التدريبات متدرجة من السهل إلى المتوسط ثم المتقدم ومناسبة للمذاكرة بعد الحصة. "
        "اجعل quick_revision نقاطًا شديدة الاختصار تصلح للمراجعة قبل الامتحان، وsummary خلاصة مركزة للحصة. "
        "أي معلومة غير واضحة أو متعارضة ضعها في uncertain_items بدل التخمين. "
        "الرسومات المقترحة تقتصر على العلاقات والرموز الظاهرة في المصدر. أخرج JSON صالحًا فقط."
    )
    prompt = (
        f"العنوان: {title}\nالمادة: {subject}\nالصف: {grade_label}\n"
        f"نمط الملزمة: {pack_mode}\nعدد الأسئلة المطلوب: {question_count}\n\n"
        "source_refs المسموح بها (استخدم القيم حرفيًا):\n- "
        + "\n- ".join(refs)
        + "\n\nقالب JSON:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\nالنص المصدر:\n"
        + transcript
    )
    raw = _gemini_text(
        [{"text": prompt}],
        developer,
        json_mode=True,
        task="lesson_pack_generation",
    )
    try:
        pack = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "Lesson Pack generator returned invalid JSON") from exc
    if not isinstance(pack, dict):
        raise HTTPException(502, "Lesson Pack generator returned invalid JSON")

    pack.setdefault("title", title)
    pack.setdefault("subject", subject)
    pack.setdefault("grade_label", grade_label)
    pack["mode"] = "student_simple"
    pack["pack_mode"] = pack_mode
    pack = _attach_diagram_engine(pack, subject)
    pack = normalize_generated_questions(pack)
    pack["source_map"] = [{"ref": ref} for ref in refs]
    pack["provenance_validation"] = validate_pack_provenance(pack, refs)
    pack["student_pack_profile"] = {
        "primary_artifact": "printable_student_handout",
        "paper": "A4",
        "purpose": "study_after_lesson_and_revision",
        "student_answer_key": False,
        "teacher_answer_key": True,
        "clean_student_copy": True,
    }
    pack["artifact_policy"] = {
        "artifact_kind": "lesson_pack",
        "source_grounded_only": True,
        "generated_explanations_allowed": True,
        "generated_practice_questions_allowed": True,
        "official_question_bank_write": False,
        "teacher_approval_required_for_final_export": True,
        "generated_visuals_must_be_labeled": True,
    }
    return pack


def render_payload(pack: dict, edition: str) -> dict:
    if edition not in {"student", "teacher"}:
        raise ValueError("edition must be student or teacher")
    payload = copy.deepcopy(pack)
    payload["mode"] = "student_simple" if edition == "student" else "teacher_notes"
    sections = [item for item in (payload.get("sections") or []) if isinstance(item, dict)]

    examples = payload.get("worked_examples") or []
    if examples:
        body: list[str] = []
        refs: list[str] = []
        for i, item in enumerate(examples, 1):
            if not isinstance(item, dict):
                continue
            steps = "\n".join(
                f"{n}. {step}" for n, step in enumerate(item.get("solution_steps") or [], 1)
            )
            answer = f"\nالإجابة: {item.get('answer') or ''}" if edition == "teacher" else ""
            item_refs = [str(x) for x in (item.get("source_refs") or [])]
            ref_line = (
                "\nالمصدر: " + "، ".join(item_refs)
                if edition == "teacher" and item_refs else ""
            )
            body.append(
                f"مثال {i}: {item.get('title') or ''}\n{item.get('problem') or ''}\n{steps}{answer}{ref_line}"
            )
            refs.extend(item_refs)
        if body:
            sections.append(
                {"heading": "أمثلة وتطبيقات", "body": "\n\n".join(body), "source_refs": list(dict.fromkeys(refs))}
            )

    mistakes = payload.get("common_mistakes") or []
    if mistakes:
        rows: list[str] = []
        refs: list[str] = []
        for item in mistakes:
            if isinstance(item, dict):
                rows.append(f"• {item.get('text') or ''}")
                refs.extend(str(x) for x in (item.get("source_refs") or []))
            else:
                rows.append(f"• {item}")
        sections.append(
            {"heading": "أخطاء شائعة", "body": "\n".join(rows), "source_refs": list(dict.fromkeys(refs))}
        )

    questions = [item for item in (payload.get("practice_questions") or []) if isinstance(item, dict)]
    if questions:
        rows: list[str] = []
        refs: list[str] = []
        for i, question in enumerate(questions, 1):
            options = question.get("options") or []
            letters = ["أ", "ب", "ج", "د", "هـ", "و"]
            option_text = (
                "\n" + "\n".join(
                    f"   {letters[n] if n < len(letters) else n + 1}) {x}"
                    for n, x in enumerate(options)
                )
                if options else ""
            )
            item_refs = [str(x) for x in (question.get("source_refs") or [])]
            ref_line = (
                "\nالمصدر: " + "، ".join(item_refs)
                if edition == "teacher" and item_refs else ""
            )
            difficulty_map = {"easy": "سهل", "medium": "متوسط", "hard": "متقدم"}
            difficulty = difficulty_map.get(str(question.get("difficulty") or "medium"), "متوسط")
            internal_note = (
                "\n— تدريب مولد من المصدر، وليس سؤالًا منقولًا حرفيًا."
                if edition == "teacher" else ""
            )
            answer_space = ""
            if edition == "student" and not options:
                answer_space = (
                    "\n\nمساحة الحل:\n"
                    "................................................................................\n"
                    "................................................................................"
                )
            rows.append(
                f"{i}) [{difficulty}] {question.get('prompt') or ''}{option_text}"
                f"{answer_space}{internal_note}{ref_line}"
            )
            refs.extend(item_refs)
        sections.append(
            {"heading": "تدريبات الدرس", "body": "\n\n".join(rows), "source_refs": list(dict.fromkeys(refs))}
        )
        if edition == "teacher":
            answers = [
                (
                    f"{i}) الإجابة: {q.get('answer') or ''}\n"
                    f"التفسير: {q.get('explanation') or ''}\n"
                    f"المصدر: {'، '.join(str(x) for x in (q.get('source_refs') or []))}"
                )
                for i, q in enumerate(questions, 1)
            ]
            sections.append(
                {"heading": "نموذج الإجابة والتفسير", "body": "\n\n".join(answers), "source_refs": []}
            )

    quick = payload.get("quick_revision") or []
    if quick:
        rows: list[str] = []
        refs: list[str] = []
        for item in quick:
            if isinstance(item, dict):
                rows.append(f"• {item.get('text') or ''}")
                refs.extend(str(x) for x in (item.get("source_refs") or []))
            else:
                rows.append(f"• {item}")
        sections.append(
            {"heading": "مراجعة في دقيقة", "body": "\n".join(rows), "source_refs": list(dict.fromkeys(refs))}
        )
    for equation in payload.get("equations_or_rules") or []:
        if not isinstance(equation, dict):
            continue
        refs = [str(x) for x in (equation.get("source_refs") or [])]
        if refs and edition == "teacher":
            existing = str(equation.get("notes") or "").strip()
            source_line = "المصدر: " + "، ".join(refs)
            equation["notes"] = (existing + "\n" + source_line).strip()

    for diagram in payload.get("diagram_specs") or []:
        if not isinstance(diagram, dict):
            continue
        refs = [str(x) for x in (diagram.get("source_refs") or [])]
        if refs and edition == "teacher":
            existing = str(diagram.get("description") or "").strip()
            source_line = "المصدر: " + "، ".join(refs)
            diagram["description"] = (existing + "\n" + source_line).strip()

    payload["sections"] = sections
    return payload


def render_pdf(pack: dict, edition: str) -> bytes:
    return render_lesson_pdf(
        render_payload(pack, edition),
        preset="a4",
        theme="student_handout" if edition == "student" else "modern_classroom",
    )
