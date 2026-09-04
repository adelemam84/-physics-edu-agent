from __future__ import annotations
from fastapi import Depends, HTTPException
from .main import app
from .db import connect
from .security import require_admin

def build_adaptive_practice(student_id:int,count:int=10):
    count=max(1,min(count,30))
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s",(student_id,)).fetchone():
            raise HTTPException(404,"Student not found")
        context=con.execute("""SELECT q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id
          FROM attempts a JOIN quizzes q ON q.id=a.quiz_id
          WHERE a.student_id=%s AND a.completed_at IS NOT NULL
          ORDER BY a.completed_at DESC,a.id DESC LIMIT 1""",(student_id,)).fetchone()
        weak_concepts=list(con.execute("""SELECT qc.concept_id,
          100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0) mastery
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
          JOIN question_concepts qc ON qc.question_id=aa.question_id
          WHERE a.student_id=%s
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.subject_id=%s))
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.grade_level_id=%s))
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.curriculum_version_id=%s))
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.term_id=%s))
          GROUP BY qc.concept_id HAVING count(aa.id)>=2
          ORDER BY mastery ASC LIMIT 5""",(student_id,
          context["subject_id"] if context else None,context["subject_id"] if context else None,
          context["grade_level_id"] if context else None,context["grade_level_id"] if context else None,
          context["curriculum_version_id"] if context else None,context["curriculum_version_id"] if context else None,
          context["term_id"] if context else None,context["term_id"] if context else None)).fetchall())
        weak_skills=list(con.execute("""SELECT qs.skill_id,
          100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0) mastery
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
          JOIN question_skills qs ON qs.question_id=aa.question_id
          WHERE a.student_id=%s
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.subject_id=%s))
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.grade_level_id=%s))
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.curriculum_version_id=%s))
            AND (%s IS NULL OR EXISTS(SELECT 1 FROM questions z WHERE z.id=aa.question_id AND z.term_id=%s))
          GROUP BY qs.skill_id HAVING count(aa.id)>=3
          ORDER BY mastery ASC LIMIT 5""",(student_id,
          context["subject_id"] if context else None,context["subject_id"] if context else None,
          context["grade_level_id"] if context else None,context["grade_level_id"] if context else None,
          context["curriculum_version_id"] if context else None,context["curriculum_version_id"] if context else None,
          context["term_id"] if context else None,context["term_id"] if context else None)).fetchall())
        cids=[x["concept_id"] for x in weak_concepts if x["mastery"] is not None and float(x["mastery"])<70]
        sids=[x["skill_id"] for x in weak_skills if x["mastery"] is not None and float(x["mastery"])<70]
        if not cids and not sids:
            return {"student_id":student_id,"questions":[],"reason":"لا توجد نقاط ضعف مؤكدة كافية بعد"}
        rows=list(con.execute("""SELECT DISTINCT q.id,q.text_verbatim,q.difficulty,q.question_type,
          EXISTS(SELECT 1 FROM question_assets qa WHERE qa.question_id=q.id) has_asset,
          coalesce((SELECT count(*) FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
                    WHERE a.student_id=%s AND aa.question_id=q.id),0) seen_count
          FROM questions q
          WHERE q.approved=TRUE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
          AND (%s IS NULL OR q.subject_id=%s)
          AND (%s IS NULL OR q.grade_level_id=%s)
          AND (%s IS NULL OR q.curriculum_version_id=%s)
          AND (%s IS NULL OR q.term_id=%s)
          AND EXISTS(SELECT 1 FROM question_assets qa WHERE qa.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_concepts qc0 WHERE qc0.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_skills qs0 WHERE qs0.question_id=q.id)
          AND (
            EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id AND qc.concept_id=ANY(%s))
            OR EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id AND qs.skill_id=ANY(%s))
          )
          ORDER BY seen_count ASC,random() LIMIT %s""",(student_id,
          context["subject_id"] if context else None,context["subject_id"] if context else None,
          context["grade_level_id"] if context else None,context["grade_level_id"] if context else None,
          context["curriculum_version_id"] if context else None,context["curriculum_version_id"] if context else None,
          context["term_id"] if context else None,context["term_id"] if context else None,
          cids or [-1],sids or [-1],count)).fetchall())
        return {"student_id":student_id,"weak_concept_ids":cids,"weak_skill_ids":sids,"questions":rows,
                "academic_context":dict(context) if context else None,
                "policy":"approved_source_questions_only; same_academic_context; unseen_first"}

@app.get("/api/admin/students/{student_id}/adaptive-practice",dependencies=[Depends(require_admin)])
def adaptive_practice(student_id:int,count:int=10):
    return build_adaptive_practice(student_id,count)

@app.get("/api/student/adaptive-practice")
def student_adaptive_practice(student_code:str,count:int=10):
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(student_code.strip(),)).fetchone()
    if not st: raise HTTPException(404,"كود الطالب غير صحيح")
    data=build_adaptive_practice(st["id"],count)
    data["student_name"]=st["name"]
    return data


@app.post("/api/student/adaptive-practice/create")
def create_student_adaptive_quiz(student_code:str,count:int=10):
    code=student_code.strip()
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(code,)).fetchone()
    if not st:
        raise HTTPException(404,"كود الطالب غير صحيح")
    data=build_adaptive_practice(st["id"],count)
    questions=data.get("questions") or []
    if not questions:
        raise HTTPException(409,data.get("reason") or "لا توجد أسئلة علاجية مناسبة حاليًا")
    title=f'تدريب علاجي - طالب #{st["id"]}'
    with connect() as con:
        recent=con.execute("""SELECT id,title FROM quizzes WHERE title=%s AND published=TRUE
          AND created_at>=now()-interval '5 minutes' ORDER BY id DESC LIMIT 1""",(title,)).fetchone()
        if recent:
            return {"quiz_id":recent["id"],"title":recent["title"],"question_count":len(questions),
                    "student_path":f'/student/quiz/{recent["id"]}',"policy":data.get("policy"),"reused":True}
        first=con.execute("""SELECT subject_id,grade_level_id,curriculum_version_id,term_id
          FROM questions WHERE id=%s""",(questions[0]["id"],)).fetchone()
        quiz=con.execute("""INSERT INTO quizzes(title,published,subject_id,grade_level_id,curriculum_version_id,term_id)
          VALUES(%s,TRUE,%s,%s,%s,%s) RETURNING id,title,published""",
          (title,first["subject_id"],first["grade_level_id"],first["curriculum_version_id"],first["term_id"])).fetchone()
        for i,q in enumerate(questions,1):
            con.execute("INSERT INTO quiz_questions(quiz_id,question_id,position) VALUES(%s,%s,%s)",
                        (quiz["id"],q["id"],i))
    return {"quiz_id":quiz["id"],"title":quiz["title"],"question_count":len(questions),
            "student_path":f'/student/quiz/{quiz["id"]}',"policy":data.get("policy"),"reused":False}
