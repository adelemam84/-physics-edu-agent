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


def _remedial_progress(con,student_id:int,limit:int=8):
    cycles=list(con.execute("""SELECT a.id attempt_id,a.quiz_id,a.completed_at,q.title,
      round(100.0*a.score/nullif(a.max_score,0),1) cycle_score
      FROM attempts a JOIN quizzes q ON q.id=a.quiz_id
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
        AND EXISTS(SELECT 1 FROM quiz_audit_log al WHERE al.quiz_id=q.id AND al.action='adaptive_publish')
      ORDER BY a.completed_at DESC,a.id DESC LIMIT %s""",(student_id,max(1,min(limit,30)))).fetchall())
    out=[]
    for cyc in cycles:
        rows=list(con.execute("""SELECT c.id,c.title,l.title lesson_title,
          count(aa.id) FILTER(WHERE hist.completed_at < %s) before_n,
          count(aa.id) FILTER(WHERE hist.completed_at < %s AND aa.is_correct=TRUE) before_ok,
          count(aa.id) FILTER(WHERE hist.completed_at <= %s) after_n,
          count(aa.id) FILTER(WHERE hist.completed_at <= %s AND aa.is_correct=TRUE) after_ok,
          count(taa.id) cycle_n,count(taa.id) FILTER(WHERE taa.is_correct=TRUE) cycle_ok
          FROM quiz_questions qq
          JOIN question_concepts qc ON qc.question_id=qq.question_id
          JOIN concepts c ON c.id=qc.concept_id LEFT JOIN lessons l ON l.id=c.lesson_id
          LEFT JOIN attempt_answers aa ON aa.question_id IN (
            SELECT qc2.question_id FROM question_concepts qc2 WHERE qc2.concept_id=c.id)
          LEFT JOIN attempts hist ON hist.id=aa.attempt_id AND hist.student_id=%s AND hist.completed_at IS NOT NULL
          LEFT JOIN attempt_answers taa ON taa.attempt_id=%s AND taa.question_id IN (
            SELECT qc3.question_id FROM question_concepts qc3 WHERE qc3.concept_id=c.id)
          WHERE qq.quiz_id=%s
          GROUP BY c.id,c.title,l.title ORDER BY c.title""",
          (cyc["completed_at"],cyc["completed_at"],cyc["completed_at"],cyc["completed_at"],student_id,cyc["attempt_id"],cyc["quiz_id"])).fetchall())
        concepts=[]
        for r in rows:
            x=dict(r)
            bn=int(x["before_n"] or 0); bo=int(x["before_ok"] or 0); an=int(x["after_n"] or 0); ao=int(x["after_ok"] or 0)
            before=round(100*bo/bn,1) if bn else None; after=round(100*ao/an,1) if an else None
            def status(n,m):
                if n<2 or m is None:return "insufficient_data"
                if m<60:return "weak"
                if m<80:return "developing"
                return "strong"
            bs=status(bn,before); ast=status(an,after)
            x.update({"before_mastery":before,"after_mastery":after,"before_status":bs,"after_status":ast,
                      "delta":round(after-before,1) if before is not None and after is not None else None,
                      "improved":before is not None and after is not None and after>before,
                      "needs_another_cycle":ast in ("weak","developing")})
            concepts.append(x)
        out.append({**dict(cyc),"concepts":concepts,
          "improved_concepts":sum(1 for x in concepts if x["improved"]),
          "strong_after":sum(1 for x in concepts if x["after_status"]=="strong"),
          "needs_followup":any(x["needs_another_cycle"] for x in concepts)})
    return out

@app.get("/api/admin/students/{student_id}/remedial-progress",dependencies=[Depends(require_admin)])
def admin_remedial_progress(student_id:int,limit:int=8):
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s",(student_id,)).fetchone(): raise HTTPException(404,"Student not found")
        return {"student_id":student_id,"cycles":_remedial_progress(con,student_id,limit)}

@app.get("/api/student/remedial-progress")
def student_remedial_progress(student_code:str,limit:int=8):
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(student_code.strip(),)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        return {"student":st,"cycles":_remedial_progress(con,st["id"],limit)}


def _learning_recommendations(con,student_id:int):
    mastery=_student_mastery(con,student_id)
    remedial=_remedial_progress(con,student_id,1)
    latest_lesson=con.execute("""SELECT l.id,l.title,l.sort_order,l.subject_id,l.grade_level_id,l.curriculum_version_id,l.term_id,l.unit_id
      FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
      JOIN lessons l ON l.id=q.lesson_id
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
      ORDER BY a.completed_at DESC,aa.id DESC LIMIT 1""",(student_id,)).fetchone()
    recs=[]
    if remedial and remedial[0]["needs_followup"]:
        pending=[x for x in remedial[0]["concepts"] if x["needs_another_cycle"]]
        if pending:
            recs.append({"priority":1,"type":"remedial_followup","title":"أكمل التدريب العلاجي",
              "reason":"بعض المفاهيم المستهدفة لم تصل بعد إلى مستوى الإتقان.",
              "items":[{"id":x["id"],"title":x["title"],"mastery":x["after_mastery"],"status":x["after_status"]} for x in pending[:5]],
              "action":"adaptive_practice"})
    for x in mastery["priority"]["concepts"][:3]:
        recs.append({"priority":2,"type":"concept_review","title":"راجع المفهوم: "+x["title"],
          "reason":f'نسبة الإتقان الحالية {x["mastery"]}% من {x["responses"]} إجابات.',
          "lesson_title":x.get("lesson_title"),"mastery":x["mastery"],"action":"adaptive_practice"})
    for x in mastery["priority"]["skills"][:2]:
        recs.append({"priority":3,"type":"skill_practice","title":"درّب المهارة: "+x["name_ar"],
          "reason":f'نسبة الإتقان الحالية {x["mastery"]}% من {x["responses"]} إجابات.',
          "mastery":x["mastery"],"action":"adaptive_practice"})
    if not recs:
        developing=[x for x in mastery["concepts"] if x["status"]=="developing"]
        for x in developing[:2]:
            recs.append({"priority":4,"type":"concept_strengthen","title":"ثبّت المفهوم: "+x["title"],
              "reason":f'أنت قريب من الإتقان ({x["mastery"]}%). دورة قصيرة قد تنقله إلى مستوى قوي.',
              "lesson_title":x.get("lesson_title"),"mastery":x["mastery"],"action":"adaptive_practice"})
    readiness={"ready_for_next":False,"current_lesson":dict(latest_lesson) if latest_lesson else None,
               "next_lesson":None,"reason":"لا توجد بيانات كافية بعد"}
    if latest_lesson:
        lm=next((x for x in mastery["lessons"] if x["id"]==latest_lesson["id"]),None)
        lesson_concepts=[x for x in mastery["concepts"] if x.get("lesson_title")==latest_lesson["title"]]
        blockers=[x for x in lesson_concepts if x["status"] in ("weak","developing")]
        strong_enough=bool(lm and lm["status"]=="strong" and lm["confidence"] in ("medium","high"))
        if strong_enough and not blockers:
            nxt=con.execute("""SELECT id,title,chapter,unit_id,sort_order FROM lessons
              WHERE subject_id=%s AND grade_level_id=%s AND curriculum_version_id=%s AND term_id=%s
                AND sort_order>%s ORDER BY sort_order,id LIMIT 1""",
              (latest_lesson["subject_id"],latest_lesson["grade_level_id"],latest_lesson["curriculum_version_id"],
               latest_lesson["term_id"],latest_lesson["sort_order"])).fetchone()
            readiness={"ready_for_next":True,"current_lesson":dict(latest_lesson),
                       "next_lesson":dict(nxt) if nxt else None,
                       "reason":"تم إتقان الدرس الحالي دون وجود مفاهيم ضعيفة أو قيد التطور."}
            if nxt:
                recs.append({"priority":5,"type":"next_lesson","title":"انتقل إلى الدرس التالي: "+nxt["title"],
                  "reason":"الدرس الحالي مستوفٍ لمعيار الإتقان.","lesson_id":nxt["id"],"action":"study_next"})
        else:
            readiness={"ready_for_next":False,"current_lesson":dict(latest_lesson),"next_lesson":None,
                       "reason":"أكمل معالجة نقاط الضعف أو المفاهيم قيد التطور قبل الانتقال." if blockers else "نحتاج أدلة أداء إضافية على الدرس الحالي."}
    if not recs:
        recs=[{"priority":9,"type":"evidence","title":"أكمل اختبارًا قصيرًا",
          "reason":"نحتاج بيانات أداء إضافية قبل تحديد توصية أكثر دقة.","action":"available_quiz"}]
    recs=sorted(recs,key=lambda x:x["priority"])[:6]
    return {"recommendations":recs,"readiness":readiness,
      "basis":{"mastery":True,"error_history":True,"remedial_progress":bool(remedial),"latest_lesson":bool(latest_lesson)}}

@app.get("/api/admin/students/{student_id}/recommendations",dependencies=[Depends(require_admin)])
def admin_student_recommendations(student_id:int):
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s",(student_id,)).fetchone(): raise HTTPException(404,"Student not found")
        return {"student_id":student_id,**_learning_recommendations(con,student_id)}

@app.get("/api/student/recommendations")
def student_recommendations(student_code:str):
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(student_code.strip(),)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        return {"student":st,**_learning_recommendations(con,st["id"])}
