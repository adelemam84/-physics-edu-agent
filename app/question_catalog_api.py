from __future__ import annotations

import hashlib

import fitz
from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin
from .services.question_admin_runtime import patch_question_record
from .services.storage import get_bytes, put_bytes


WORKFLOW_STATE_SQL = """CASE
  WHEN q.approved=TRUE THEN 'approved'
  WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
       AND q.document_id IS NOT NULL
       AND coalesce(q.source_page,q.page) IS NOT NULL
       AND q.subject_id IS NOT NULL
       AND q.grade_level_id IS NOT NULL
       AND q.curriculum_version_id IS NOT NULL
       AND q.term_id IS NOT NULL
       AND q.unit_id IS NOT NULL
       AND q.lesson_id IS NOT NULL
       AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
       AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
       AND q.question_type <> 'unknown'
       AND q.difficulty <> 'unclassified'
       AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
       AND NOT EXISTS(
          SELECT 1 FROM question_review_notes qr
          WHERE qr.question_id=q.id AND qr.status='open'
       )
       THEN 'reviewed'
  WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) THEN 'cropped'
  ELSE 'draft'
END"""


class QuestionCompatPatch(BaseModel):
    approved: bool | None = None
    lesson_id: int | None = None
    subject_id: int | None = None
    grade_level_id: int | None = None
    curriculum_version_id: int | None = None
    term_id: int | None = None
    unit_id: int | None = None
    question_type: str | None = None
    difficulty: str | None = None
    accepted_answer: str | None = None
    answer_verbatim: str | None = None
    answer_document_id: int | None = None
    answer_page: int | None = None


class SourceQuestionCreate(BaseModel):
    page: int = Field(ge=1)
    text_verbatim: str = Field(min_length=1, max_length=50000)
    question_type: str = "unknown"
    lesson_id: int | None = None
    subject_id: int | None = None
    grade_level_id: int | None = None
    curriculum_version_id: int | None = None
    term_id: int | None = None
    unit_id: int | None = None
    difficulty: str = "unclassified"


def _filters(
    *,
    approved: bool | None = None,
    lesson_id: int | None = None,
    subject_id: int | None = None,
    grade_level_id: int | None = None,
    curriculum_version_id: int | None = None,
    term_id: int | None = None,
    unit_id: int | None = None,
    document_id: int | None = None,
    source_page: int | None = None,
    difficulty: str | None = None,
    question_type: str | None = None,
    workflow_state: str | None = None,
    chapter: str | None = None,
) -> tuple[list[str], list[object]]:
    where: list[str] = []
    params: list[object] = []

    pairs = (
        ("q.subject_id", subject_id),
        ("q.grade_level_id", grade_level_id),
        ("q.curriculum_version_id", curriculum_version_id),
        ("q.term_id", term_id),
        ("q.unit_id", unit_id),
        ("q.lesson_id", lesson_id),
        ("q.document_id", document_id),
    )
    for column, value in pairs:
        if value is not None:
            where.append(f"{column}=%s")
            params.append(value)

    if source_page is not None:
        if source_page < 1:
            raise HTTPException(400, "Invalid source_page")
        where.append("coalesce(q.source_page,q.page)=%s")
        params.append(source_page)

    if approved is not None:
        where.append("q.approved=%s")
        params.append(approved)

    if difficulty is not None:
        if difficulty not in {"unclassified", "easy", "medium", "hard"}:
            raise HTTPException(400, "Invalid difficulty")
        where.append("q.difficulty=%s")
        params.append(difficulty)

    if question_type is not None:
        if question_type not in {"unknown", "mcq", "numeric", "essay"}:
            raise HTTPException(400, "Invalid question_type")
        where.append("q.question_type=%s")
        params.append(question_type)

    if workflow_state is not None:
        if workflow_state not in {"draft", "cropped", "reviewed", "approved"}:
            raise HTTPException(400, "Invalid workflow_state")
        where.append(f"({WORKFLOW_STATE_SQL})=%s")
        params.append(workflow_state)

    if chapter is not None:
        where.append("l.chapter=%s")
        params.append(chapter)

    return where, params


def _question_query(where: list[str]) -> str:
    clause = " AND ".join(["q.document_id IS NOT NULL", *where])
    return f"""SELECT q.*,d.filename source_filename,ad.filename answer_source_filename,
      l.chapter,l.title lesson_title,
      CASE WHEN q.answer_document_id IS NOT NULL AND q.answer_page IS NOT NULL
           THEN 'pdf_source' ELSE 'manual_review' END AS answer_source_type,
      EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) AS has_asset,
      {WORKFLOW_STATE_SQL} AS workflow_state
      FROM questions q
      JOIN documents d ON d.id=q.document_id
      LEFT JOIN documents ad ON ad.id=q.answer_document_id
      LEFT JOIN lessons l ON l.id=q.lesson_id
      WHERE {clause}"""


@app.get("/api/admin/question-catalog", dependencies=[Depends(require_admin)])
def question_catalog(
    approved: bool | None = None,
    lesson_id: int | None = None,
    subject_id: int | None = None,
    grade_level_id: int | None = None,
    curriculum_version_id: int | None = None,
    term_id: int | None = None,
    unit_id: int | None = None,
    document_id: int | None = None,
    source_page: int | None = None,
    difficulty: str | None = None,
    question_type: str | None = None,
    workflow_state: str | None = None,
    chapter: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    limit = min(max(limit, 1), 250)
    offset = max(offset, 0)
    where, params = _filters(
        approved=approved,
        lesson_id=lesson_id,
        subject_id=subject_id,
        grade_level_id=grade_level_id,
        curriculum_version_id=curriculum_version_id,
        term_id=term_id,
        unit_id=unit_id,
        document_id=document_id,
        source_page=source_page,
        difficulty=difficulty,
        question_type=question_type,
        workflow_state=workflow_state,
        chapter=chapter,
    )
    query = _question_query(where)
    with connect() as con:
        total = con.execute(
            f"SELECT count(*) total FROM ({query}) catalog",
            params,
        ).fetchone()["total"]
        items = list(
            con.execute(
                query + " ORDER BY q.id DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            ).fetchall()
        )
    return {
        "items": items,
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < int(total or 0),
    }


@app.get("/api/questions", dependencies=[Depends(require_admin)], deprecated=True)
def legacy_questions(
    approved: bool | None = None,
    lesson_id: int | None = None,
    subject_id: int | None = None,
    grade_level_id: int | None = None,
    curriculum_version_id: int | None = None,
    term_id: int | None = None,
    unit_id: int | None = None,
    document_id: int | None = None,
    source_page: int | None = None,
    difficulty: str | None = None,
    question_type: str | None = None,
    workflow_state: str | None = None,
    chapter: str | None = None,
    limit: int = 500,
):
    result = question_catalog(
        approved=approved,
        lesson_id=lesson_id,
        subject_id=subject_id,
        grade_level_id=grade_level_id,
        curriculum_version_id=curriculum_version_id,
        term_id=term_id,
        unit_id=unit_id,
        document_id=document_id,
        source_page=source_page,
        difficulty=difficulty,
        question_type=question_type,
        workflow_state=workflow_state,
        chapter=chapter,
        limit=min(max(limit, 1), 1000),
        offset=0,
    )
    return result["items"]


@app.get("/api/question-stats", dependencies=[Depends(require_admin)], deprecated=True)
def question_stats():
    with connect() as con:
        totals = con.execute(
            """SELECT count(*) total,
              count(*) FILTER(WHERE approved) approved,
              count(*) FILTER(WHERE NOT approved) unapproved,
              count(*) FILTER(WHERE difficulty='easy') easy,
              count(*) FILTER(WHERE difficulty='medium') medium,
              count(*) FILTER(WHERE difficulty='hard') hard,
              count(*) FILTER(WHERE difficulty='unclassified') unclassified
              FROM questions"""
        ).fetchone()
        by_lesson = list(
            con.execute(
                """SELECT l.chapter,l.title,count(q.id) total,
                  count(q.id) FILTER(WHERE q.approved) approved
                  FROM lessons l LEFT JOIN questions q ON q.lesson_id=l.id
                  GROUP BY l.id,l.chapter,l.title,l.sort_order
                  ORDER BY l.sort_order,l.id"""
            ).fetchall()
        )
        by_type = list(
            con.execute(
                """SELECT question_type,count(*) total
                   FROM questions GROUP BY question_type ORDER BY total DESC"""
            ).fetchall()
        )
        by_state = list(
            con.execute(
                f"""SELECT state,count(*) total FROM (
                       SELECT {WORKFLOW_STATE_SQL} state FROM questions q
                     ) x GROUP BY state ORDER BY state"""
            ).fetchall()
        )
    return {
        "totals": totals,
        "by_lesson": by_lesson,
        "by_type": by_type,
        "by_state": by_state,
    }


@app.get("/api/documents", dependencies=[Depends(require_admin)], deprecated=True)
def legacy_documents():
    with connect() as con:
        return list(
            con.execute(
                """SELECT d.*,f.page_count,f.file_size_bytes,
                  (SELECT count(*) FROM questions q WHERE q.document_id=d.id) question_count
                  FROM documents d
                  LEFT JOIN document_files f ON f.document_id=d.id
                  ORDER BY d.id DESC"""
            ).fetchall()
        )


@app.get(
    "/api/documents/{document_id}/pages",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
def legacy_document_pages(document_id: int):
    with connect() as con:
        if not con.execute(
            "SELECT id FROM documents WHERE id=%s", (document_id,)
        ).fetchone():
            raise HTTPException(404, "Document not found")
        return list(
            con.execute(
                """SELECT p.page_number,
                  length(coalesce(p.extracted_text,'')) text_length,
                  (p.preview_object_key IS NOT NULL) preview_cached,
                  (SELECT count(*) FROM questions q
                   WHERE q.document_id=p.document_id
                     AND coalesce(q.source_page,q.page)=p.page_number) question_count
                  FROM document_pages p
                  WHERE p.document_id=%s ORDER BY p.page_number""",
                (document_id,),
            ).fetchall()
        )


@app.get(
    "/api/documents/{document_id}/page/{page}/text",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
def legacy_page_text(document_id: int, page: int):
    with connect() as con:
        row = con.execute(
            """SELECT extracted_text,text_sha256 FROM document_pages
               WHERE document_id=%s AND page_number=%s""",
            (document_id, page),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Page not found")
    return {
        "page": page,
        "extracted_text": row["extracted_text"] or "",
        "text_sha256": row["text_sha256"],
    }


@app.get(
    "/api/documents/{document_id}/page/{page}/preview",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
def legacy_page_preview(document_id: int, page: int):
    with connect() as con:
        row = con.execute(
            """SELECT p.preview_object_key,f.object_key
               FROM document_pages p
               JOIN document_files f ON f.document_id=p.document_id
               WHERE p.document_id=%s AND p.page_number=%s""",
            (document_id, page),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Page not found")
    if row["preview_object_key"]:
        return Response(
            get_bytes(row["preview_object_key"]),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=300"},
        )

    raw = get_bytes(row["object_key"])
    try:
        pdf = fitz.open(stream=raw, filetype="pdf")
        if page < 1 or page > pdf.page_count:
            pdf.close()
            raise HTTPException(404, "Page not found")
        pix = pdf.load_page(page - 1).get_pixmap(
            matrix=fitz.Matrix(1.45, 1.45), alpha=False
        )
        preview = pix.tobytes("jpeg", jpg_quality=82)
        pdf.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Unable to render page preview") from exc

    object_key = f"documents/{document_id}/pages/{page:04d}.jpg"
    put_bytes(object_key, preview, "image/jpeg")
    with connect() as con:
        con.execute(
            """UPDATE document_pages SET preview_object_key=%s
               WHERE document_id=%s AND page_number=%s""",
            (object_key, document_id, page),
        )
    return Response(
        preview,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get(
    "/api/questions/{question_id}/readiness",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
def legacy_question_readiness(question_id: int):
    with connect() as con:
        row = con.execute(
            """SELECT q.id,q.document_id,coalesce(q.source_page,q.page) page_number,
              q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id,q.unit_id,
              q.lesson_id,q.question_type,q.difficulty,q.accepted_answer,q.approved,
              EXISTS(SELECT 1 FROM document_pages p
                WHERE p.document_id=q.document_id
                  AND p.page_number=coalesce(q.source_page,q.page)) source_page_exists,
              EXISTS(SELECT 1 FROM question_assets a
                WHERE a.question_id=q.id AND a.document_id=q.document_id
                  AND a.page_number=coalesce(q.source_page,q.page)) asset_valid,
              EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
              EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
              EXISTS(SELECT 1 FROM lessons l WHERE l.id=q.lesson_id
                AND l.subject_id=q.subject_id AND l.grade_level_id=q.grade_level_id
                AND l.curriculum_version_id=q.curriculum_version_id
                AND l.term_id=q.term_id AND l.unit_id=q.unit_id) academic_consistent,
              NOT EXISTS(SELECT 1 FROM question_concepts qc
                JOIN concepts c ON c.id=qc.concept_id
                WHERE qc.question_id=q.id
                  AND c.lesson_id IS DISTINCT FROM q.lesson_id) concept_consistent,
              NOT EXISTS(SELECT 1 FROM question_review_notes qr
                WHERE qr.question_id=q.id AND qr.status='open') qa_clear
              FROM questions q WHERE q.id=%s""",
            (question_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Question not found")

    ready = bool(
        row["document_id"]
        and row["page_number"]
        and row["source_page_exists"]
        and row["asset_valid"]
        and row["subject_id"]
        and row["grade_level_id"]
        and row["curriculum_version_id"]
        and row["term_id"]
        and row["unit_id"]
        and row["lesson_id"]
        and row["has_concept"]
        and row["has_skill"]
        and row["academic_consistent"]
        and row["concept_consistent"]
        and row["qa_clear"]
        and row["question_type"] != "unknown"
        and row["difficulty"] != "unclassified"
        and str(row["accepted_answer"] or "").strip()
    )
    state = (
        "approved"
        if row["approved"]
        else "reviewed"
        if ready
        else "cropped"
        if row["asset_valid"]
        else "draft"
    )
    return {**dict(row), "ready_for_approval": ready, "workflow_state": state}


@app.patch(
    "/api/questions/{question_id}",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
def legacy_patch_question(question_id: int, patch: QuestionCompatPatch):
    return patch_question_record(question_id, patch.model_dump(exclude_unset=True))


@app.post(
    "/api/documents/{document_id}/questions/manual",
    dependencies=[Depends(require_admin)],
    deprecated=True,
)
def legacy_create_source_question(document_id: int, payload: SourceQuestionCreate):
    text = payload.text_verbatim.strip()
    if payload.difficulty not in {"unclassified", "easy", "medium", "hard"}:
        raise HTTPException(400, "Invalid difficulty")
    if payload.question_type not in {"unknown", "mcq", "numeric", "essay"}:
        raise HTTPException(400, "Invalid question_type")

    with connect() as con:
        document = con.execute(
            """SELECT subject_id,grade_level_id,curriculum_version_id,term_id
               FROM documents WHERE id=%s""",
            (document_id,),
        ).fetchone()
        if not document:
            raise HTTPException(404, "Document not found")
        if not con.execute(
            """SELECT 1 FROM document_pages
               WHERE document_id=%s AND page_number=%s""",
            (document_id, payload.page),
        ).fetchone():
            raise HTTPException(404, "Source page not found")

        supplied = {
            "subject_id": payload.subject_id,
            "grade_level_id": payload.grade_level_id,
            "curriculum_version_id": payload.curriculum_version_id,
            "term_id": payload.term_id,
        }
        for key, value in supplied.items():
            if (
                value is not None
                and document[key] is not None
                and value != document[key]
            ):
                raise HTTPException(
                    400,
                    {
                        "message": "تصنيف السؤال اليدوي لا يطابق ملف المصدر",
                        "field": key,
                    },
                )

        subject_id = payload.subject_id or document["subject_id"]
        grade_level_id = payload.grade_level_id or document["grade_level_id"]
        curriculum_version_id = (
            payload.curriculum_version_id or document["curriculum_version_id"]
        )
        term_id = payload.term_id or document["term_id"]
        unit_id = payload.unit_id
        lesson_id = payload.lesson_id

        if unit_id:
            unit = con.execute(
                """SELECT u.term_id,t.curriculum_version_id,c.subject_id,c.grade_level_id
                   FROM units u
                   JOIN academic_terms t ON t.id=u.term_id
                   JOIN curriculum_versions c ON c.id=t.curriculum_version_id
                   WHERE u.id=%s""",
                (unit_id,),
            ).fetchone()
            if (
                not unit
                or unit["term_id"] != term_id
                or unit["curriculum_version_id"] != curriculum_version_id
                or unit["subject_id"] != subject_id
                or unit["grade_level_id"] != grade_level_id
            ):
                raise HTTPException(
                    400, "الوحدة لا تطابق ملف المصدر والسياق الأكاديمي"
                )

        if lesson_id:
            lesson = con.execute(
                """SELECT subject_id,grade_level_id,curriculum_version_id,term_id,unit_id
                   FROM lessons WHERE id=%s""",
                (lesson_id,),
            ).fetchone()
            if not lesson:
                raise HTTPException(400, "الدرس غير موجود")
            expected = {
                "subject_id": subject_id,
                "grade_level_id": grade_level_id,
                "curriculum_version_id": curriculum_version_id,
                "term_id": term_id,
            }
            bad = [
                key
                for key, value in expected.items()
                if value is not None and lesson[key] != value
            ]
            if unit_id is not None and lesson["unit_id"] != unit_id:
                bad.append("unit_id")
            if bad:
                raise HTTPException(
                    400,
                    {
                        "message": "الدرس لا يطابق السياق الأكاديمي لملف المصدر",
                        "fields": bad,
                    },
                )
            if unit_id is None:
                unit_id = lesson["unit_id"]

        duplicate = con.execute(
            """SELECT id FROM questions
               WHERE document_id=%s AND coalesce(source_page,page)=%s
                 AND text_verbatim=%s LIMIT 1""",
            (document_id, payload.page, text),
        ).fetchone()
        if duplicate:
            raise HTTPException(
                409, f"هذا السؤال مسجل بالفعل برقم {duplicate['id']}"
            )

        row = con.execute(
            """INSERT INTO questions(
                 document_id,page,source_page,text_verbatim,approved,question_type,
                 lesson_id,subject_id,grade_level_id,curriculum_version_id,term_id,
                 unit_id,difficulty
               ) VALUES (%s,%s,%s,%s,FALSE,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                document_id,
                payload.page,
                payload.page,
                text,
                payload.question_type,
                lesson_id,
                subject_id,
                grade_level_id,
                curriculum_version_id,
                term_id,
                unit_id,
                payload.difficulty,
            ),
        ).fetchone()
        con.execute(
            "UPDATE documents SET status='review_required' WHERE id=%s",
            (document_id,),
        )
    return dict(row)
