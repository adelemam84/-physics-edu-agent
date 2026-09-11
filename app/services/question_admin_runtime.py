from __future__ import annotations

from fastapi import HTTPException

from ..db import connect


ALLOWED_FIELDS = {
    "approved",
    "lesson_id",
    "subject_id",
    "grade_level_id",
    "curriculum_version_id",
    "term_id",
    "unit_id",
    "question_type",
    "difficulty",
    "accepted_answer",
    "answer_verbatim",
    "answer_document_id",
    "answer_page",
}


def patch_question_record(question_id: int, raw_values: dict) -> dict:
    """Update one question behind the full source/academic approval gate.

    This is the single write path used by both the modern admin API and the
    backwards-compatible review workspace route. It never edits verbatim text.
    """
    values = {k: v for k, v in raw_values.items() if k in ALLOWED_FIELDS}
    if not values:
        raise HTTPException(400, "No changes")
    if "difficulty" in values and values["difficulty"] not in {
        "unclassified",
        "easy",
        "medium",
        "hard",
    }:
        raise HTTPException(400, "Invalid difficulty")

    with connect() as con:
        current = con.execute(
            """SELECT id,document_id,subject_id,grade_level_id,curriculum_version_id,
                      term_id,unit_id,lesson_id
               FROM questions WHERE id=%s""",
            (question_id,),
        ).fetchone()
        if not current:
            raise HTTPException(404, "Question not found")

        academic_keys = {
            "subject_id",
            "grade_level_id",
            "curriculum_version_id",
            "term_id",
            "unit_id",
            "lesson_id",
        }
        answer_source_keys = {"answer_document_id", "answer_page", "answer_verbatim"}

        if answer_source_keys.intersection(values):
            effective_answer_document = values.get("answer_document_id")
            effective_answer_page = values.get("answer_page")
            if "answer_document_id" not in values or "answer_page" not in values:
                stored = con.execute(
                    "SELECT answer_document_id,answer_page FROM questions WHERE id=%s",
                    (question_id,),
                ).fetchone()
                if "answer_document_id" not in values:
                    effective_answer_document = stored["answer_document_id"]
                if "answer_page" not in values:
                    effective_answer_page = stored["answer_page"]

            if (effective_answer_document is None) != (effective_answer_page is None):
                raise HTTPException(400, "مصدر الإجابة يحتاج ملفًا ورقم صفحة معًا")

            if effective_answer_document is not None:
                adoc = con.execute(
                    """SELECT id,kind,subject_id,grade_level_id,curriculum_version_id,term_id
                       FROM documents WHERE id=%s""",
                    (effective_answer_document,),
                ).fetchone()
                if not adoc:
                    raise HTTPException(400, "ملف مصدر الإجابة غير موجود")
                if adoc["kind"] not in ("answers", "reference"):
                    raise HTTPException(
                        400, "مصدر الإجابة يجب أن يكون مفتاح إجابة أو مرجعًا"
                    )
                if not con.execute(
                    "SELECT 1 FROM document_pages WHERE document_id=%s AND page_number=%s",
                    (effective_answer_document, effective_answer_page),
                ).fetchone():
                    raise HTTPException(400, "صفحة مصدر الإجابة غير موجودة")

                effective_context = {
                    k: values.get(k, current[k])
                    for k in (
                        "subject_id",
                        "grade_level_id",
                        "curriculum_version_id",
                        "term_id",
                    )
                }
                mismatched = [
                    k
                    for k in effective_context
                    if adoc[k] is not None
                    and effective_context[k] is not None
                    and adoc[k] != effective_context[k]
                ]
                if mismatched:
                    raise HTTPException(
                        400,
                        {
                            "message": "مصدر الإجابة لا يطابق سياق السؤال",
                            "fields": mismatched,
                        },
                    )

            if values.get("answer_verbatim") is not None and not str(
                values.get("answer_verbatim") or ""
            ).strip():
                values["answer_verbatim"] = None

        if academic_keys.intersection(values):
            effective = {k: values.get(k, current[k]) for k in academic_keys}

            if effective["curriculum_version_id"]:
                curriculum = con.execute(
                    """SELECT subject_id,grade_level_id FROM curriculum_versions
                       WHERE id=%s AND active=TRUE""",
                    (effective["curriculum_version_id"],),
                ).fetchone()
                if (
                    not curriculum
                    or (
                        effective["subject_id"]
                        and curriculum["subject_id"] != effective["subject_id"]
                    )
                    or (
                        effective["grade_level_id"]
                        and curriculum["grade_level_id"] != effective["grade_level_id"]
                    )
                ):
                    raise HTTPException(400, "إصدار المنهج لا يطابق المادة والصف")

            if effective["term_id"]:
                term = con.execute(
                    "SELECT curriculum_version_id FROM academic_terms WHERE id=%s",
                    (effective["term_id"],),
                ).fetchone()
                if (
                    not term
                    or (
                        effective["curriculum_version_id"]
                        and term["curriculum_version_id"]
                        != effective["curriculum_version_id"]
                    )
                ):
                    raise HTTPException(400, "الترم لا يطابق إصدار المنهج")

            if effective["unit_id"]:
                unit = con.execute(
                    "SELECT term_id FROM units WHERE id=%s", (effective["unit_id"],)
                ).fetchone()
                if (
                    not unit
                    or (effective["term_id"] and unit["term_id"] != effective["term_id"])
                ):
                    raise HTTPException(400, "الوحدة لا تطابق الترم")

            if effective["lesson_id"]:
                lesson = con.execute(
                    """SELECT subject_id,grade_level_id,curriculum_version_id,term_id,unit_id
                       FROM lessons WHERE id=%s""",
                    (effective["lesson_id"],),
                ).fetchone()
                if not lesson:
                    raise HTTPException(400, "الدرس غير موجود")
                mismatched = [
                    k
                    for k in (
                        "subject_id",
                        "grade_level_id",
                        "curriculum_version_id",
                        "term_id",
                        "unit_id",
                    )
                    if effective[k] and lesson[k] != effective[k]
                ]
                if mismatched:
                    raise HTTPException(
                        400,
                        {
                            "message": "الدرس لا يطابق السياق الأكاديمي المختار",
                            "fields": mismatched,
                        },
                    )

            if current["document_id"]:
                document = con.execute(
                    """SELECT subject_id,grade_level_id,curriculum_version_id,term_id
                       FROM documents WHERE id=%s""",
                    (current["document_id"],),
                ).fetchone()
                if document:
                    mismatched = [
                        k
                        for k in (
                            "subject_id",
                            "grade_level_id",
                            "curriculum_version_id",
                            "term_id",
                        )
                        if document[k] is not None
                        and effective[k] is not None
                        and document[k] != effective[k]
                    ]
                    if mismatched:
                        raise HTTPException(
                            400,
                            {
                                "message": "تصنيف السؤال لا يطابق ملف المصدر",
                                "fields": mismatched,
                            },
                        )

        approval_sensitive = set(values).difference({"approved"})
        if approval_sensitive and values.get("approved") is not True:
            # Any substantive edit invalidates the previous human approval.
            # The reviewer must explicitly approve the new state after all
            # source/academic/QA gates pass again.
            values["approved"] = False

        if values.get("approved") is True:
            gate = con.execute(
                """SELECT q.id,q.document_id,coalesce(q.source_page,q.page) page_number,
                          q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id,
                          q.unit_id,q.lesson_id,q.question_type,q.difficulty,q.accepted_answer,
                          EXISTS(
                            SELECT 1 FROM document_pages p
                            WHERE p.document_id=q.document_id
                              AND p.page_number=coalesce(q.source_page,q.page)
                          ) source_page_exists,
                          EXISTS(
                            SELECT 1 FROM question_assets a
                            WHERE a.question_id=q.id AND a.document_id=q.document_id
                              AND a.page_number=coalesce(q.source_page,q.page)
                          ) asset_valid,
                          EXISTS(
                            SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id
                          ) has_concept,
                          EXISTS(
                            SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id
                          ) has_skill
                   FROM questions q WHERE q.id=%s""",
                (question_id,),
            ).fetchone()
            if not gate:
                raise HTTPException(404, "Question not found")

            effective_subject = values.get("subject_id", gate["subject_id"])
            effective_grade = values.get("grade_level_id", gate["grade_level_id"])
            effective_curriculum = values.get(
                "curriculum_version_id", gate["curriculum_version_id"]
            )
            effective_term = values.get("term_id", gate["term_id"])
            effective_unit = values.get("unit_id", gate["unit_id"])
            effective_lesson = values.get("lesson_id", gate["lesson_id"])
            effective_type = values.get("question_type", gate["question_type"])
            effective_difficulty = values.get("difficulty", gate["difficulty"])
            effective_answer = values.get("accepted_answer", gate["accepted_answer"])

            effective_academic_consistent = bool(
                effective_lesson
                and con.execute(
                    """SELECT 1 FROM lessons
                       WHERE id=%s AND subject_id=%s AND grade_level_id=%s
                         AND curriculum_version_id=%s AND term_id=%s AND unit_id=%s""",
                    (
                        effective_lesson,
                        effective_subject,
                        effective_grade,
                        effective_curriculum,
                        effective_term,
                        effective_unit,
                    ),
                ).fetchone()
            )
            effective_concept_consistent = not bool(
                con.execute(
                    """SELECT 1 FROM question_concepts qc
                       JOIN concepts c ON c.id=qc.concept_id
                       WHERE qc.question_id=%s
                         AND c.lesson_id IS DISTINCT FROM %s
                       LIMIT 1""",
                    (question_id, effective_lesson),
                ).fetchone()
            )

            source_answer = con.execute(
                "SELECT answer_document_id,answer_page FROM questions WHERE id=%s",
                (question_id,),
            ).fetchone()
            effective_answer_document = values.get(
                "answer_document_id", source_answer["answer_document_id"]
            )
            effective_answer_page = values.get("answer_page", source_answer["answer_page"])

            missing: list[str] = []
            if not gate["document_id"]:
                missing.append("document")
            if not gate["page_number"]:
                missing.append("source_page")
            if not gate["source_page_exists"]:
                missing.append("valid_source_page")
            if not gate["asset_valid"]:
                missing.append("question_asset")
            if not effective_subject:
                missing.append("subject")
            if not effective_grade:
                missing.append("grade_level")
            if not effective_curriculum:
                missing.append("curriculum_version")
            if not effective_term:
                missing.append("term")
            if not effective_unit:
                missing.append("unit")
            if not effective_lesson:
                missing.append("lesson")
            if not gate["has_concept"]:
                missing.append("concept")
            if not gate["has_skill"]:
                missing.append("skill")
            if not effective_academic_consistent:
                missing.append("academic_consistency")
            if not effective_concept_consistent:
                missing.append("concept_consistency")
            if not effective_type or effective_type == "unknown":
                missing.append("question_type")
            if not effective_difficulty or effective_difficulty == "unclassified":
                missing.append("difficulty")
            if not effective_answer or not str(effective_answer).strip():
                missing.append("accepted_answer")
            if effective_answer_document is not None and not effective_answer_page:
                missing.append("answer_source_page")

            # A live QA note always wins over deterministic completeness.
            unresolved = con.execute(
                """SELECT reason_code FROM question_review_notes
                   WHERE question_id=%s AND status='open'
                   ORDER BY updated_at DESC LIMIT 1""",
                (question_id,),
            ).fetchone()
            if unresolved:
                missing.append("open_quality_review")

            if missing:
                raise HTTPException(
                    409,
                    {
                        "message": "لا يمكن اعتماد السؤال قبل اكتمال المصدر والتصنيف والمراجعة",
                        "missing": list(dict.fromkeys(missing)),
                    },
                )

        setters = ", ".join(f"{k}=%s" for k in values)
        row = con.execute(
            f"UPDATE questions SET {setters} WHERE id=%s RETURNING *",
            list(values.values()) + [question_id],
        ).fetchone()
        if not row:
            raise HTTPException(404, "Question not found")
        return dict(row)
