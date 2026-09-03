from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

@app.get("/api/admin/students/{student_id}/error-notebook",dependencies=[Depends(require_admin)])
def error_notebook(student_id:int,limit:int=100):
    limit=max(1,min(limit,300))
    with connect() as con:
        st=con.execute("SELECT id,name,external_code FROM students WHERE id=%s",(student_id,)).fetchone()
        if not st: raise HTTPException(404,"Student not found")
        rows=list(con.execute("""SELECT aa.question_id,q.text_verbatim,q.difficulty,q.question_type,
          count(*) wrong_count,max(a.completed_at) last_wrong,
          l.title lesson_title,u.title unit_title,s.name_ar subject_name,
          string_agg(DISTINCT c.title,'، ') concepts,
          string_agg(DISTINCT sk.name_ar,'، ') skills
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
          JOIN questions q ON q.id=aa.question_id
          LEFT JOIN lessons l ON l.id=q.lesson_id LEFT JOIN units u ON u.id=q.unit_id LEFT JOIN subjects s ON s.id=q.subject_id
          LEFT JOIN question_concepts qc ON qc.question_id=q.id LEFT JOIN concepts c ON c.id=qc.concept_id
          LEFT JOIN question_skills qs ON qs.question_id=q.id LEFT JOIN skills sk ON sk.id=qs.skill_id
          WHERE a.student_id=%s AND aa.is_correct=FALSE
          GROUP BY aa.question_id,q.text_verbatim,q.difficulty,q.question_type,l.title,u.title,s.name_ar
          ORDER BY wrong_count DESC,last_wrong DESC LIMIT %s""",(student_id,limit)).fetchall())
        return {"student":st,"errors":rows}

@app.get("/api/admin/question-analytics",dependencies=[Depends(require_admin)])
def question_analytics(limit:int=100):
    limit=max(1,min(limit,300))
    with connect() as con:
        return list(con.execute("""SELECT q.id,q.text_verbatim,q.difficulty,q.question_type,
          count(aa.id) responses,count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) success_rate,
          round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=FALSE)/nullif(count(aa.id),0),1) error_rate
          FROM questions q LEFT JOIN attempt_answers aa ON aa.question_id=q.id
          WHERE q.approved=TRUE GROUP BY q.id,q.text_verbatim,q.difficulty,q.question_type
          ORDER BY count(aa.id) DESC,q.id DESC LIMIT %s""",(limit,)).fetchall())

@app.get("/api/admin/coverage",dependencies=[Depends(require_admin)])
def coverage():
    with connect() as con:
        concepts=list(con.execute("""SELECT c.id,c.title,l.title lesson_title,
          count(DISTINCT qc.question_id) FILTER(WHERE q.approved=TRUE) approved_questions
          FROM concepts c JOIN lessons l ON l.id=c.lesson_id
          LEFT JOIN question_concepts qc ON qc.concept_id=c.id LEFT JOIN questions q ON q.id=qc.question_id
          GROUP BY c.id,c.title,l.title ORDER BY approved_questions,c.title""").fetchall())
        skills=list(con.execute("""SELECT s.id,s.name_ar,count(DISTINCT qs.question_id) FILTER(WHERE q.approved=TRUE) approved_questions
          FROM skills s LEFT JOIN question_skills qs ON qs.skill_id=s.id LEFT JOIN questions q ON q.id=qs.question_id
          WHERE s.active=TRUE GROUP BY s.id,s.name_ar,s.sort_order ORDER BY approved_questions,s.sort_order""").fetchall())
        return {"concepts":concepts,"skills":skills}
