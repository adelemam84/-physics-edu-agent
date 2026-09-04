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


def _student_mastery(con,student_id:int):
    lessons=list(con.execute("""SELECT l.id,l.title,u.title unit_title,s.name_ar subject_name,
      count(aa.id) responses,count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
      round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
      FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
      JOIN lessons l ON l.id=q.lesson_id LEFT JOIN units u ON u.id=q.unit_id LEFT JOIN subjects s ON s.id=q.subject_id
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
      GROUP BY l.id,l.title,u.title,s.name_ar ORDER BY mastery ASC NULLS LAST,responses DESC""",(student_id,)).fetchall())
    concepts=list(con.execute("""SELECT c.id,c.title,l.title lesson_title,
      count(aa.id) responses,count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
      round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
      FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
      JOIN question_concepts qc ON qc.question_id=aa.question_id JOIN concepts c ON c.id=qc.concept_id
      LEFT JOIN lessons l ON l.id=c.lesson_id
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
      GROUP BY c.id,c.title,l.title ORDER BY mastery ASC NULLS LAST,responses DESC""",(student_id,)).fetchall())
    skills=list(con.execute("""SELECT sk.id,sk.name_ar,
      count(aa.id) responses,count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
      round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
      FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
      JOIN question_skills qs ON qs.question_id=aa.question_id JOIN skills sk ON sk.id=qs.skill_id
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
      GROUP BY sk.id,sk.name_ar,sk.sort_order ORDER BY mastery ASC NULLS LAST,responses DESC,sk.sort_order""",(student_id,)).fetchall())
    def classify(rows,min_responses):
        out=[]
        for r in rows:
            x=dict(r); n=int(x.get("responses") or 0); m=float(x["mastery"]) if x.get("mastery") is not None else None
            x["confidence"]="high" if n>=5 else "medium" if n>=min_responses else "low"
            x["status"]="weak" if n>=min_responses and m is not None and m<60 else "developing" if n>=min_responses and m is not None and m<80 else "strong" if n>=min_responses and m is not None else "insufficient_data"
            out.append(x)
        return out
    lessons=classify(lessons,2);concepts=classify(concepts,2);skills=classify(skills,3)
    weak_lessons=[x for x in lessons if x["status"]=="weak"]
    weak_concepts=[x for x in concepts if x["status"]=="weak"]
    weak_skills=[x for x in skills if x["status"]=="weak"]
    strong=[x for x in concepts if x["status"]=="strong" and x["confidence"]!="low"]
    return {"lessons":lessons,"concepts":concepts,"skills":skills,
      "summary":{"weak_lessons":len(weak_lessons),"weak_concepts":len(weak_concepts),"weak_skills":len(weak_skills),"strong_concepts":len(strong)},
      "priority":{"lessons":weak_lessons[:5],"concepts":weak_concepts[:5],"skills":weak_skills[:5]}}

@app.get("/api/admin/students/{student_id}/mastery",dependencies=[Depends(require_admin)])
def admin_student_mastery(student_id:int):
    with connect() as con:
        st=con.execute("SELECT id,name,external_code FROM students WHERE id=%s",(student_id,)).fetchone()
        if not st: raise HTTPException(404,"Student not found")
        data=_student_mastery(con,student_id)
    return {"student":st,**data}

@app.get("/api/student/mastery")
def student_mastery(student_code:str):
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(student_code.strip(),)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        data=_student_mastery(con,st["id"])
    return {"student":st,**data}
