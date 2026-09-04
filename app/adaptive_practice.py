from __future__ import annotations
from fastapi import Depends, HTTPException
from .main import app
from .db import connect
from .security import require_admin

def _latest_remedial_targets(con,student_id:int):
    last=con.execute("""SELECT a.id,a.quiz_id,a.completed_at FROM attempts a JOIN quizzes q ON q.id=a.quiz_id
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
      AND EXISTS(SELECT 1 FROM quiz_audit_log al WHERE al.quiz_id=q.id AND al.action='adaptive_publish')
      ORDER BY a.completed_at DESC,a.id DESC LIMIT 1""",(student_id,)).fetchone()
    if not last:return None
    rows=list(con.execute("""SELECT c.id concept_id,
      count(aa.id) responses,count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
      round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
      FROM quiz_questions qq JOIN question_concepts qc ON qc.question_id=qq.question_id JOIN concepts c ON c.id=qc.concept_id
      LEFT JOIN question_concepts allqc ON allqc.concept_id=c.id
      LEFT JOIN attempt_answers aa ON aa.question_id=allqc.question_id
      LEFT JOIN attempts hist ON hist.id=aa.attempt_id AND hist.student_id=%s AND hist.completed_at IS NOT NULL AND hist.completed_at<=%s
      WHERE qq.quiz_id=%s GROUP BY c.id ORDER BY mastery NULLS FIRST""",(student_id,last["completed_at"],last["quiz_id"])).fetchall())
    unresolved=[r["concept_id"] for r in rows if int(r["responses"] or 0)<2 or r["mastery"] is None or float(r["mastery"])<80]
    mastered=[r["concept_id"] for r in rows if int(r["responses"] or 0)>=2 and r["mastery"] is not None and float(r["mastery"])>=80]
    avg=sum(float(r["mastery"]) for r in rows if r["mastery"] is not None)/max(1,sum(1 for r in rows if r["mastery"] is not None))
    return {"attempt_id":last["id"],"quiz_id":last["quiz_id"],"unresolved_concept_ids":unresolved,
            "mastered_concept_ids":mastered,"average_mastery":round(avg,1),"closed":not unresolved}

def build_adaptive_practice(student_id:int,count:int=10):
    count=max(1,min(count,30))
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s",(student_id,)).fetchone():
            raise HTTPException(404,"Student not found")
        context=con.execute("""SELECT q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id
          FROM attempts a JOIN quizzes q ON q.id=a.quiz_id WHERE a.student_id=%s AND a.completed_at IS NOT NULL
          ORDER BY a.completed_at DESC,a.id DESC LIMIT 1""",(student_id,)).fetchone()
        ctx=[context["subject_id"],context["grade_level_id"],context["curriculum_version_id"],context["term_id"]] if context else [None]*4
        weak_lessons=list(con.execute("""SELECT q.lesson_id,
          100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0) mastery,count(aa.id) responses
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
          WHERE a.student_id=%s AND q.lesson_id IS NOT NULL
          AND (%s IS NULL OR q.subject_id=%s) AND (%s IS NULL OR q.grade_level_id=%s)
          AND (%s IS NULL OR q.curriculum_version_id=%s) AND (%s IS NULL OR q.term_id=%s)
          GROUP BY q.lesson_id HAVING count(aa.id)>=2 ORDER BY mastery ASC,responses DESC LIMIT 5""",
          (student_id,ctx[0],ctx[0],ctx[1],ctx[1],ctx[2],ctx[2],ctx[3],ctx[3])).fetchall())
        weak_concepts=list(con.execute("""SELECT qc.concept_id,
          100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0) mastery,count(aa.id) responses
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
          JOIN question_concepts qc ON qc.question_id=aa.question_id WHERE a.student_id=%s
          AND (%s IS NULL OR q.subject_id=%s) AND (%s IS NULL OR q.grade_level_id=%s)
          AND (%s IS NULL OR q.curriculum_version_id=%s) AND (%s IS NULL OR q.term_id=%s)
          GROUP BY qc.concept_id HAVING count(aa.id)>=2 ORDER BY mastery ASC,responses DESC LIMIT 8""",
          (student_id,ctx[0],ctx[0],ctx[1],ctx[1],ctx[2],ctx[2],ctx[3],ctx[3])).fetchall())
        followup=_latest_remedial_targets(con,student_id)
        weak_skills=list(con.execute("""SELECT qs.skill_id,
          100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0) mastery,count(aa.id) responses
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
          JOIN question_skills qs ON qs.question_id=aa.question_id WHERE a.student_id=%s
          AND (%s IS NULL OR q.subject_id=%s) AND (%s IS NULL OR q.grade_level_id=%s)
          AND (%s IS NULL OR q.curriculum_version_id=%s) AND (%s IS NULL OR q.term_id=%s)
          GROUP BY qs.skill_id HAVING count(aa.id)>=3 ORDER BY mastery ASC,responses DESC LIMIT 8""",
          (student_id,ctx[0],ctx[0],ctx[1],ctx[1],ctx[2],ctx[2],ctx[3],ctx[3])).fetchall())
        lids=[x["lesson_id"] for x in weak_lessons if x["mastery"] is not None and float(x["mastery"])<70]
        cids=[x["concept_id"] for x in weak_concepts if x["mastery"] is not None and float(x["mastery"])<70]
        if followup:
            if followup["closed"]:
                cids=[]
            elif followup["unresolved_concept_ids"]:
                # After a remedial cycle, focus the next cycle only on concepts not yet mastered.
                cids=[x for x in cids if x in followup["unresolved_concept_ids"]] or followup["unresolved_concept_ids"]
        sids=[x["skill_id"] for x in weak_skills if x["mastery"] is not None and float(x["mastery"])<70]
        if not lids and not cids and not sids:
            return {"student_id":student_id,"questions":[],"reason":"لا توجد نقاط ضعف مؤكدة كافية بعد"}
        # Difficulty rises only after demonstrated mastery; weak areas start easy, developing areas medium.
        weakest=min([float(x["mastery"]) for x in weak_lessons+weak_concepts+weak_skills if x["mastery"] is not None] or [0])
        if followup and followup["average_mastery"]>=70: preferred="hard"
        elif followup and followup["average_mastery"]>=50: preferred="medium"
        else: preferred="easy" if weakest<50 else "medium" if weakest<75 else "hard"
        rows=list(con.execute("""SELECT DISTINCT q.id,q.text_verbatim,q.difficulty,q.question_type,
          EXISTS(SELECT 1 FROM question_assets qa WHERE qa.question_id=q.id) has_asset,
          coalesce((SELECT count(*) FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
                    WHERE a.student_id=%s AND aa.question_id=q.id),0) seen_count,
          CASE WHEN q.lesson_id=ANY(%s) THEN 1 ELSE 0 END lesson_priority,
          CASE WHEN EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id AND qc.concept_id=ANY(%s)) THEN 1 ELSE 0 END concept_priority,
          CASE WHEN EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id AND qs.skill_id=ANY(%s)) THEN 1 ELSE 0 END skill_priority
          FROM questions q WHERE q.approved=TRUE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
          AND (%s IS NULL OR q.subject_id=%s) AND (%s IS NULL OR q.grade_level_id=%s)
          AND (%s IS NULL OR q.curriculum_version_id=%s) AND (%s IS NULL OR q.term_id=%s)
          AND EXISTS(SELECT 1 FROM question_assets qa WHERE qa.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_concepts qc0 WHERE qc0.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_skills qs0 WHERE qs0.question_id=q.id)
          AND (q.lesson_id=ANY(%s) OR EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id AND qc.concept_id=ANY(%s))
            OR EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id AND qs.skill_id=ANY(%s)))
          ORDER BY lesson_priority DESC,concept_priority DESC,skill_priority DESC,seen_count ASC,
            CASE q.difficulty WHEN %s THEN 0 WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,random() LIMIT %s""",
          (student_id,lids or [-1],cids or [-1],sids or [-1],
           ctx[0],ctx[0],ctx[1],ctx[1],ctx[2],ctx[2],ctx[3],ctx[3],
           lids or [-1],cids or [-1],sids or [-1],preferred,count)).fetchall())
        return {"student_id":student_id,"weak_lesson_ids":lids,"weak_concept_ids":cids,"weak_skill_ids":sids,
          "preferred_difficulty":preferred,"questions":rows,"academic_context":dict(context) if context else None,
          "followup":followup,"closed_concept_ids":followup["mastered_concept_ids"] if followup else [],
          "policy":"close_mastered_targets; followup_unresolved_concepts_only; weak_lesson_then_concept_then_skill; unseen_first; progressive_difficulty; approved_source_questions_only"}

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
        quiz=con.execute("""INSERT INTO quizzes(title,published,lifecycle_status,quality_score,subject_id,grade_level_id,curriculum_version_id,term_id,max_attempts,retry_wait_minutes,score_policy,published_at)
          VALUES(%s,TRUE,'published',100,%s,%s,%s,%s,1,0,'latest',now()) RETURNING id,title,published,lifecycle_status""",
          (title,first["subject_id"],first["grade_level_id"],first["curriculum_version_id"],first["term_id"])).fetchone()
        for i,q in enumerate(questions,1):
            con.execute("INSERT INTO quiz_questions(quiz_id,question_id,position) VALUES(%s,%s,%s)",
                        (quiz["id"],q["id"],i))
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score,details)
          VALUES(%s,'adaptive_publish',NULL,'published',100,%s::jsonb)""",
          (quiz["id"],'{"system_generated":true,"purpose":"adaptive_practice","source_policy":"approved_source_questions_only"}'))
    return {"quiz_id":quiz["id"],"title":quiz["title"],"question_count":len(questions),
            "student_path":f'/student/quiz/{quiz["id"]}',"policy":data.get("policy"),"reused":False}
