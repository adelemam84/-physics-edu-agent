from __future__ import annotations

from ..db import connect


def active_content_integrity_snapshot() -> dict:
    """Read active-curriculum data integrity without mutating questions or source files."""
    with connect() as con:
        ctx=con.execute(
            """SELECT cv.id curriculum_version_id,cv.academic_year,cv.subject_id,cv.grade_level_id
               FROM curriculum_versions cv
               WHERE cv.subject_id=1 AND cv.grade_level_id=6 AND cv.active=TRUE
               ORDER BY cv.id DESC LIMIT 1"""
        ).fetchone()
        if not ctx:
            return {
                "active": False,
                "ready": False,
                "reason": "no_active_curriculum",
                "invalid_approved_questions": 0,
                "question_lesson_mismatches": 0,
                "quiz_question_mismatches": 0,
            }

        params=(ctx["curriculum_version_id"],)
        approved=con.execute(
            """SELECT
              count(*) FILTER(WHERE q.approved=TRUE) approved_total,
              count(*) FILTER(WHERE q.approved=TRUE AND (
                q.accepted_answer IS NULL OR btrim(q.accepted_answer)=''
                OR q.lesson_id IS NULL
                OR NOT EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
                OR NOT EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
                OR NOT EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
              )) invalid_approved_questions,
              count(*) FILTER(WHERE q.approved=TRUE
                AND (q.accepted_answer IS NULL OR btrim(q.accepted_answer)='')) missing_answer,
              count(*) FILTER(WHERE q.approved=TRUE AND q.lesson_id IS NULL) missing_lesson,
              count(*) FILTER(WHERE q.approved=TRUE
                AND NOT EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)) missing_asset,
              count(*) FILTER(WHERE q.approved=TRUE
                AND NOT EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)) missing_concept,
              count(*) FILTER(WHERE q.approved=TRUE
                AND NOT EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)) missing_skill
              FROM questions q
              WHERE q.curriculum_version_id=%s""",
            params,
        ).fetchone()

        q_lesson=con.execute(
            """SELECT count(*) n
               FROM questions q
               JOIN lessons l ON l.id=q.lesson_id
               WHERE q.curriculum_version_id=%s
                 AND (
                   q.subject_id IS DISTINCT FROM l.subject_id
                   OR q.grade_level_id IS DISTINCT FROM l.grade_level_id
                   OR q.curriculum_version_id IS DISTINCT FROM l.curriculum_version_id
                   OR q.term_id IS DISTINCT FROM l.term_id
                   OR q.unit_id IS DISTINCT FROM l.unit_id
                 )""",
            params,
        ).fetchone()["n"]

        quiz_context=con.execute(
            """SELECT count(DISTINCT z.id) n
               FROM quizzes z
               JOIN quiz_questions qq ON qq.quiz_id=z.id
               JOIN questions q ON q.id=qq.question_id
               WHERE z.curriculum_version_id=%s
                 AND (
                   z.subject_id IS DISTINCT FROM q.subject_id
                   OR z.grade_level_id IS DISTINCT FROM q.grade_level_id
                   OR z.curriculum_version_id IS DISTINCT FROM q.curriculum_version_id
                   OR z.term_id IS DISTINCT FROM q.term_id
                 )""",
            params,
        ).fetchone()["n"]

        critical_qa=con.execute(
            """SELECT count(*) n
               FROM question_review_notes qr
               JOIN questions q ON q.id=qr.question_id
               WHERE q.curriculum_version_id=%s
                 AND qr.status='open' AND qr.severity='critical'""",
            params,
        ).fetchone()["n"]

    invalid=int(approved["invalid_approved_questions"] or 0)
    lesson_mismatch=int(q_lesson or 0)
    quiz_mismatch=int(quiz_context or 0)
    critical=int(critical_qa or 0)
    return {
        "active": True,
        "curriculum_version_id": int(ctx["curriculum_version_id"]),
        "academic_year": ctx["academic_year"],
        "approved_total": int(approved["approved_total"] or 0),
        "invalid_approved_questions": invalid,
        "reasons": {
            "missing_answer": int(approved["missing_answer"] or 0),
            "missing_lesson": int(approved["missing_lesson"] or 0),
            "missing_asset": int(approved["missing_asset"] or 0),
            "missing_concept": int(approved["missing_concept"] or 0),
            "missing_skill": int(approved["missing_skill"] or 0),
        },
        "question_lesson_mismatches": lesson_mismatch,
        "quiz_question_mismatches": quiz_mismatch,
        "critical_open_qa": critical,
        "ready": invalid == 0 and lesson_mismatch == 0 and quiz_mismatch == 0 and critical == 0,
        "policy": "active_curriculum_only",
    }
