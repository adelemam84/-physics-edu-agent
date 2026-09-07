from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .main import app
from .db import connect
from .security import require_admin

class QuizGenerate(BaseModel):
    title: str = "اختبار"
    count: int = 10
    lesson_id: int | None = None
    subject_id: int | None = None
    grade_level_id: int | None = None
    curriculum_version_id: int | None = None
    term_id: int | None = None
    unit_id: int | None = None
    chapter: str | None = None
    difficulty: str | None = None
    question_type: str | None = None
    skill_id: int | None = None
    easy_pct: int | None = None
    medium_pct: int | None = None
    hard_pct: int | None = None
    use_balanced_blueprint: bool = False

@app.get('/api/quizzes/blueprint',dependencies=[Depends(require_admin)])
def quiz_blueprint(count:int=10,subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None,term_id:int|None=None,unit_id:int|None=None):
    if count<1 or count>100: raise HTTPException(400,'عدد الأسئلة يجب أن يكون من 1 إلى 100')
    if not all((subject_id,grade_level_id,curriculum_version_id,term_id)):
        raise HTTPException(400,'حدد المادة والصف وإصدار المنهج والترم أولًا')
    with connect() as con:
        ctx=con.execute("""SELECT c.id FROM curriculum_versions c JOIN academic_terms t ON t.curriculum_version_id=c.id
          WHERE c.id=%s AND c.subject_id=%s AND c.grade_level_id=%s AND t.id=%s AND c.active=TRUE""",
          (curriculum_version_id,subject_id,grade_level_id,term_id)).fetchone()
        if not ctx: raise HTTPException(400,'السياق الأكاديمي غير متسق')
        base="""q.approved=TRUE AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
          AND q.lesson_id IS NOT NULL AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
          AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
          AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)"""
        params=[subject_id,grade_level_id,curriculum_version_id,term_id]
        if unit_id: base+=" AND q.unit_id=%s";params.append(unit_id)
        lessons=list(con.execute("""SELECT l.id,l.title,l.chapter,count(q.id) available FROM lessons l
          LEFT JOIN questions q ON q.lesson_id=l.id AND """+base+"""
          WHERE l.subject_id=%s AND l.grade_level_id=%s AND l.curriculum_version_id=%s AND l.term_id=%s
          """+(" AND l.unit_id=%s" if unit_id else "")+"""
          GROUP BY l.id,l.title,l.chapter,l.sort_order ORDER BY l.sort_order,l.id""",
          params+[subject_id,grade_level_id,curriculum_version_id,term_id]+([unit_id] if unit_id else [])).fetchall())
        diff=list(con.execute("SELECT q.difficulty,count(*) n FROM questions q WHERE "+base+" GROUP BY q.difficulty",params).fetchall())
        types=list(con.execute("SELECT q.question_type,count(*) n FROM questions q WHERE "+base+" GROUP BY q.question_type",params).fetchall())
    available=sum(int(x['available'] or 0) for x in lessons)
    if available<count: return {'feasible':False,'requested':count,'available':available,'message':'البنك الجاهز لا يكفي لهذا العدد','lessons':[dict(x) for x in lessons]}
    active=[x for x in lessons if int(x['available'] or 0)>0]
    # Equal lesson coverage first, then distribute remaining slots where capacity exists.
    alloc={int(x['id']):0 for x in active};remaining=count
    while remaining and active:
        progressed=False
        for x in active:
            k=int(x['id']);cap=int(x['available'])
            if alloc[k]<cap and remaining:
                alloc[k]+=1;remaining-=1;progressed=True
        if not progressed: break
    lesson_plan=[{'lesson_id':int(x['id']),'lesson_title':x['title'],'chapter':x['chapter'],'available':int(x['available']),'count':alloc.get(int(x['id']),0)} for x in active if alloc.get(int(x['id']),0)]
    # Default assessment mix: 30/50/20, adjusted only when bank capacity forces it.
    target={'easy':round(count*.30),'medium':round(count*.50)}
    target['hard']=count-target['easy']-target['medium']
    caps={x['difficulty']:int(x['n']) for x in diff}
    dplan={k:min(target[k],caps.get(k,0)) for k in target};left=count-sum(dplan.values())
    for k in sorted(target,key=lambda k:caps.get(k,0)-dplan[k],reverse=True):
        add=min(left,max(0,caps.get(k,0)-dplan[k]));dplan[k]+=add;left-=add
    type_caps={x['question_type']:int(x['n']) for x in types}
    return {'feasible':left==0,'requested':count,'available':available,'lessons':lesson_plan,
      'difficulty':dplan,'difficulty_available':caps,'question_types_available':type_caps,
      'recommended_mix':{'easy_pct':round(dplan.get('easy',0)*100/count),'medium_pct':round(dplan.get('medium',0)*100/count),'hard_pct':100-round(dplan.get('easy',0)*100/count)-round(dplan.get('medium',0)*100/count)},
      'strategy':'balanced_lessons_then_difficulty','student_visible':False}

@app.post('/api/quizzes/generate',dependencies=[Depends(require_admin)])
def generate_quiz(p:QuizGenerate):
    if p.count<1 or p.count>100: raise HTTPException(400,'عدد الأسئلة يجب أن يكون من 1 إلى 100')
    if p.difficulty and p.difficulty not in {'easy','medium','hard'}: raise HTTPException(400,'Invalid difficulty')
    mix=[p.easy_pct,p.medium_pct,p.hard_pct]
    if any(v is not None for v in mix):
        vals=[v or 0 for v in mix]
        if any(v<0 or v>100 for v in vals) or sum(vals)!=100:
            raise HTTPException(400,'نسب الصعوبة يجب أن يكون مجموعها 100')
        if p.difficulty: raise HTTPException(400,'اختر صعوبة واحدة أو توزيع صعوبات، وليس الاثنين')
    sql="""SELECT q.id FROM questions q LEFT JOIN lessons l ON l.id=q.lesson_id
      WHERE q.approved=TRUE AND q.lesson_id IS NOT NULL AND q.question_type<>'unknown'
      AND q.difficulty<>'unclassified'
      AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
      AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
      AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
      AND EXISTS(SELECT 1 FROM question_skills qsk WHERE qsk.question_id=q.id)"""
    params=[]
    if p.subject_id: sql+=' AND q.subject_id=%s';params.append(p.subject_id)
    if p.grade_level_id: sql+=' AND q.grade_level_id=%s';params.append(p.grade_level_id)
    if p.curriculum_version_id: sql+=' AND q.curriculum_version_id=%s';params.append(p.curriculum_version_id)
    if p.term_id: sql+=' AND q.term_id=%s';params.append(p.term_id)
    if p.unit_id: sql+=' AND q.unit_id=%s';params.append(p.unit_id)
    if p.lesson_id: sql+=' AND q.lesson_id=%s';params.append(p.lesson_id)
    if p.chapter: sql+=' AND l.chapter=%s';params.append(p.chapter)
    if p.difficulty: sql+=' AND q.difficulty=%s';params.append(p.difficulty)
    if p.question_type: sql+=' AND q.question_type=%s';params.append(p.question_type)
    if p.skill_id: sql+=' AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id AND qs.skill_id=%s)';params.append(p.skill_id)
    with connect() as con:
        # Resolve and validate one coherent academic context before selecting questions.
        ctx=None
        if p.lesson_id:
            ctx=con.execute("""SELECT subject_id,grade_level_id,curriculum_version_id,term_id,unit_id
              FROM lessons WHERE id=%s""",(p.lesson_id,)).fetchone()
            if not ctx: raise HTTPException(400,'الدرس غير موجود')
        elif p.unit_id:
            ctx=con.execute("""SELECT c.subject_id,c.grade_level_id,t.curriculum_version_id,u.term_id,u.id unit_id
              FROM units u JOIN academic_terms t ON t.id=u.term_id
              JOIN curriculum_versions c ON c.id=t.curriculum_version_id WHERE u.id=%s""",(p.unit_id,)).fetchone()
            if not ctx: raise HTTPException(400,'الوحدة غير موجودة')
        elif p.curriculum_version_id and p.term_id:
            ctx=con.execute("""SELECT c.subject_id,c.grade_level_id,c.id curriculum_version_id,t.id term_id,NULL::bigint unit_id
              FROM curriculum_versions c JOIN academic_terms t ON t.curriculum_version_id=c.id
              WHERE c.id=%s AND t.id=%s AND c.active=TRUE""",(p.curriculum_version_id,p.term_id)).fetchone()
            if not ctx: raise HTTPException(400,'المنهج أو الترم غير متطابق')
        if not ctx:
            raise HTTPException(400,'حدد المادة والصف وإصدار المنهج والترم على الأقل قبل إنشاء الاختبار')
        expected={"subject_id":ctx["subject_id"],"grade_level_id":ctx["grade_level_id"],
                  "curriculum_version_id":ctx["curriculum_version_id"],"term_id":ctx["term_id"]}
        supplied={"subject_id":p.subject_id,"grade_level_id":p.grade_level_id,
                  "curriculum_version_id":p.curriculum_version_id,"term_id":p.term_id}
        bad=[k for k,v in supplied.items() if v is not None and v!=expected[k]]
        if bad: raise HTTPException(400,{"message":"السياق الأكاديمي المختار غير متسق","fields":bad})
        # Fill missing core filters from the validated context so quizzes can never mix subjects/grades.
        p.subject_id=expected["subject_id"];p.grade_level_id=expected["grade_level_id"]
        p.curriculum_version_id=expected["curriculum_version_id"];p.term_id=expected["term_id"]
        # IMPORTANT: the SQL/params above were assembled before context resolution. Rebuild
        # the academic filters here from the validated context; otherwise omitted UI fields
        # could still allow cross-subject questions into a quiz.
        sql="""SELECT q.id FROM questions q LEFT JOIN lessons l ON l.id=q.lesson_id
          WHERE q.approved=TRUE AND q.lesson_id IS NOT NULL AND q.question_type<>'unknown'
          AND q.difficulty<>'unclassified'
          AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
          AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
          AND EXISTS(SELECT 1 FROM question_skills qsk WHERE qsk.question_id=q.id)
          AND q.subject_id=%s AND q.grade_level_id=%s
          AND q.curriculum_version_id=%s AND q.term_id=%s"""
        params=[p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id]
        if p.unit_id: sql+=' AND q.unit_id=%s';params.append(p.unit_id)
        if p.lesson_id: sql+=' AND q.lesson_id=%s';params.append(p.lesson_id)
        if p.chapter: sql+=' AND l.chapter=%s';params.append(p.chapter)
        if p.difficulty: sql+=' AND q.difficulty=%s';params.append(p.difficulty)
        if p.question_type: sql+=' AND q.question_type=%s';params.append(p.question_type)
        if p.skill_id: sql+=' AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id AND qs.skill_id=%s)';params.append(p.skill_id)
        if p.use_balanced_blueprint and not p.lesson_id:
            lesson_rows=list(con.execute("""SELECT l.id,l.title,l.sort_order,count(q.id) available
              FROM lessons l LEFT JOIN questions q ON q.lesson_id=l.id AND q.approved=TRUE
                AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
                AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
                AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
                AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
                AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
                AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
              WHERE l.subject_id=%s AND l.grade_level_id=%s AND l.curriculum_version_id=%s AND l.term_id=%s
              """+(" AND l.unit_id=%s" if p.unit_id else "")+"""
              GROUP BY l.id,l.title,l.sort_order ORDER BY l.sort_order,l.id""",
              [p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id,
               p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id]+([p.unit_id] if p.unit_id else [])).fetchall())
            active=[x for x in lesson_rows if int(x['available'] or 0)>0]
            if not active: raise HTTPException(409,{'message':'لا توجد دروس بها أسئلة جاهزة في هذا السياق'})
            alloc={int(x['id']):0 for x in active};remaining=p.count
            while remaining:
                progressed=False
                for x in active:
                    lid=int(x['id']);cap=int(x['available'])
                    if alloc[lid]<cap and remaining:
                        alloc[lid]+=1;remaining-=1;progressed=True
                if not progressed: break
            if remaining: raise HTTPException(409,{'message':'البنك الجاهز لا يكفي لتوزيع الاختبار على الدروس','missing':remaining})
            wanted_diff=None
            if any(v is not None for v in mix):
                vals=[p.easy_pct or 0,p.medium_pct or 0,p.hard_pct or 0]
                raw=[p.count*v/100 for v in vals];nums=[int(x) for x in raw]
                for i in sorted(range(3),key=lambda i:raw[i]-nums[i],reverse=True)[:p.count-sum(nums)]: nums[i]+=1
                wanted_diff=dict(zip(['easy','medium','hard'],nums))
            selected=[];used=set();remaining_diff=dict(wanted_diff or {})
            for x in active:
                n=alloc[int(x['id'])]
                if not n: continue
                local_sql=sql+' AND q.lesson_id=%s'
                local_params=params+[int(x['id'])]
                picked=[]
                # Prefer questions that add a new concept/skill before repeating already-covered ones.
                # Difficulty remains a hard target when the blueprint supplied a mix.
                if wanted_diff:
                    for diff in ['easy','medium','hard']:
                        if not remaining_diff.get(diff,0): continue
                        need=min(remaining_diff[diff],n-len(picked))
                        if need<=0: continue
                        rr=con.execute(local_sql+""" AND q.difficulty=%s AND NOT (q.id=ANY(%s))
                          ORDER BY
                            (SELECT count(*) FROM question_concepts qc WHERE qc.question_id=q.id
                              AND NOT EXISTS(SELECT 1 FROM question_concepts uc WHERE uc.question_id=ANY(%s) AND uc.concept_id=qc.concept_id)) DESC,
                            (SELECT count(*) FROM question_skills qs WHERE qs.question_id=q.id
                              AND NOT EXISTS(SELECT 1 FROM question_skills us WHERE us.question_id=ANY(%s) AND us.skill_id=qs.skill_id)) DESC,
                            random() LIMIT %s""",
                          local_params+[diff,list(used) or [0],list(used) or [0],list(used) or [0],need]).fetchall()
                        picked.extend(rr);used.update(int(r['id']) for r in rr);remaining_diff[diff]-=len(rr)
                if len(picked)<n:
                    rr=con.execute(local_sql+""" AND NOT (q.id=ANY(%s))
                      ORDER BY
                        (SELECT count(*) FROM question_concepts qc WHERE qc.question_id=q.id
                          AND NOT EXISTS(SELECT 1 FROM question_concepts uc WHERE uc.question_id=ANY(%s) AND uc.concept_id=qc.concept_id)) DESC,
                        (SELECT count(*) FROM question_skills qs WHERE qs.question_id=q.id
                          AND NOT EXISTS(SELECT 1 FROM question_skills us WHERE us.question_id=ANY(%s) AND us.skill_id=qs.skill_id)) DESC,
                        random() LIMIT %s""",
                      local_params+[list(used) or [0],list(used) or [0],list(used) or [0],n-len(picked)]).fetchall()
                    picked.extend(rr);used.update(int(r['id']) for r in rr)
                if len(picked)<n: raise HTTPException(409,{'message':'تعذر تحقيق حصة أحد الدروس','lesson_id':int(x['id']),'requested':n,'selected':len(picked)})
                selected.extend(picked)
            if len(selected)!=p.count: raise HTTPException(409,{'message':'تعذر إكمال الخطة المتوازنة','selected':len(selected),'requested':p.count})
            rows=selected
        elif any(v is not None for v in mix):
            vals=[p.easy_pct or 0,p.medium_pct or 0,p.hard_pct or 0]
            raw=[p.count*v/100 for v in vals]
            nums=[int(x) for x in raw]
            for i in sorted(range(3),key=lambda i:raw[i]-nums[i],reverse=True)[:p.count-sum(nums)]: nums[i]+=1
            rows=[]
            for diff,n in zip(['easy','medium','hard'],nums):
                if not n: continue
                rr=con.execute(sql+' AND q.difficulty=%s ORDER BY random() LIMIT %s',params+[diff,n]).fetchall()
                if len(rr)<n: raise HTTPException(409,{'message':'لا توجد أسئلة كافية لتحقيق توزيع الصعوبة','difficulty':diff,'available':len(rr),'requested':n})
                rows.extend(rr)
        else:
            rows=con.execute(sql+' ORDER BY random() LIMIT %s',params+[p.count]).fetchall()
        if len(rows)<p.count: raise HTTPException(409,{'message':'عدد الأسئلة المعتمدة المطابقة أقل من المطلوب','available':len(rows),'requested':p.count})
        quiz=con.execute("""INSERT INTO quizzes(title,published,lesson_id,subject_id,grade_level_id,curriculum_version_id,term_id)
          VALUES (%s,FALSE,%s,%s,%s,%s,%s) RETURNING id,title,published""",
          (p.title,p.lesson_id,p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id)).fetchone()
        for i,r in enumerate(rows,1):
            con.execute("INSERT INTO quiz_questions(quiz_id,question_id,position) VALUES (%s,%s,%s)",(quiz['id'],r['id'],i))
        coverage=con.execute("""SELECT count(DISTINCT qc.concept_id) concepts,count(DISTINCT qs.skill_id) skills
          FROM quiz_questions qq LEFT JOIN question_concepts qc ON qc.question_id=qq.question_id
          LEFT JOIN question_skills qs ON qs.question_id=qq.question_id WHERE qq.quiz_id=%s""",(quiz['id'],)).fetchone()
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,details)
          VALUES(%s,'create',NULL,'draft',%s::jsonb)""",(quiz['id'],'{"source":"quiz_builder"}'))
        return {**quiz,'question_count':len(rows),'question_ids':[r['id'] for r in rows],
                'coverage':{'concepts':int(coverage['concepts'] or 0),'skills':int(coverage['skills'] or 0)},
                'balanced_blueprint':bool(p.use_balanced_blueprint)}

@app.patch('/api/quizzes/{quiz_id}/attempt-policy',dependencies=[Depends(require_admin)])
def update_attempt_policy(quiz_id:int,p:AttemptPolicy):
    if not 1<=p.max_attempts<=20: raise HTTPException(400,'عدد المحاولات من 1 إلى 20')
    if not 0<=p.retry_wait_minutes<=10080: raise HTTPException(400,'فترة الانتظار غير صحيحة')
    if p.score_policy not in ('highest','latest'): raise HTTPException(400,'سياسة الدرجة غير صحيحة')
    with connect() as con:
        old=con.execute("SELECT lifecycle_status,max_attempts,retry_wait_minutes,score_policy FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        if not old: raise HTTPException(404,'Quiz not found')
        q=con.execute("""UPDATE quizzes SET max_attempts=%s,retry_wait_minutes=%s,score_policy=%s
          WHERE id=%s RETURNING id,title,max_attempts,retry_wait_minutes,score_policy""",
          (p.max_attempts,p.retry_wait_minutes,p.score_policy,quiz_id)).fetchone()
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,details)
          VALUES(%s,'attempt_policy_update',%s,%s,%s::jsonb)""",
          (quiz_id,old['lifecycle_status'],old['lifecycle_status'],
           __import__('json').dumps({'max_attempts':p.max_attempts,'retry_wait_minutes':p.retry_wait_minutes,'score_policy':p.score_policy})))
    return q

@app.get('/api/quizzes/{quiz_id}/quality-check',dependencies=[Depends(require_admin)])
def quiz_quality_check(quiz_id:int):
    with connect() as con:
        quiz=con.execute("SELECT * FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        if not quiz: raise HTTPException(404,'Quiz not found')
        rows=list(con.execute("""SELECT q.id,q.lesson_id,q.difficulty,q.question_type,q.approved,
          q.document_id,coalesce(q.source_page,q.page) source_page,q.accepted_answer,
          EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open') qa_open,
          array(SELECT qc.concept_id FROM question_concepts qc WHERE qc.question_id=q.id) concepts,
          array(SELECT qs.skill_id FROM question_skills qs WHERE qs.question_id=q.id) skills
          FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id
          WHERE qq.quiz_id=%s ORDER BY qq.position""",(quiz_id,)).fetchall())
        scope_lesson=quiz['lesson_id']
        expected=con.execute("""SELECT count(DISTINCT q.lesson_id) n,
          count(DISTINCT q.difficulty) diff_n,count(DISTINCT q.question_type) type_n,
          count(DISTINCT qc.concept_id) concept_n,count(DISTINCT qs.skill_id) skill_n
          FROM questions q
          LEFT JOIN question_concepts qc ON qc.question_id=q.id
          LEFT JOIN question_skills qs ON qs.question_id=q.id
          WHERE q.approved=TRUE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
            AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
            AND (%s::bigint IS NULL OR q.lesson_id=%s::bigint)
            AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open')""",
          (quiz['subject_id'],quiz['grade_level_id'],quiz['curriculum_version_id'],quiz['term_id'],scope_lesson,scope_lesson)).fetchone()
    n=len(rows)
    if not n:return {'quiz_id':quiz_id,'ready':False,'score':0,'checks':[],'message':'الاختبار بلا أسئلة'}
    lessons={r['lesson_id'] for r in rows if r['lesson_id'] is not None};concepts={x for r in rows for x in (r['concepts'] or [])};skills={x for r in rows for x in (r['skills'] or [])}
    diffs={};types={}
    for r in rows: diffs[r['difficulty']]=diffs.get(r['difficulty'],0)+1;types[r['question_type']]=types.get(r['question_type'],0)+1
    lesson_target=max(1,min(n,int(expected['n'] or 0) or len(lessons) or 1));lesson_cov=min(1,len(lessons)/lesson_target)
    concept_target=max(1,min(n,int(expected['concept_n'] or 0) or len(concepts) or 1));concept_cov=min(1,len(concepts)/concept_target)
    skill_target=max(1,min(n,3,int(expected['skill_n'] or 0) or len(skills) or 1));skill_cov=min(1,len(skills)/skill_target)
    required_diffs=max(1,min(3,n,int(expected['diff_n'] or 0) or 1))
    required_types=max(1,min(2,n,int(expected['type_n'] or 0) or 1))
    max_lesson=max((sum(1 for r in rows if r['lesson_id']==x) for x in lessons),default=n)/n
    max_concept=max((sum(1 for r in rows if x in (r['concepts'] or [])) for x in concepts),default=n)/n
    source_ready=all(r['document_id'] is not None and r['source_page'] is not None for r in rows)
    approval_ready=all(bool(r['approved']) for r in rows)
    answer_ready=all(r['accepted_answer'] is not None and str(r['accepted_answer']).strip() for r in rows)
    qa_clear=all(not r['qa_open'] for r in rows)
    checks=[
      {'id':'source_grounding','label':'كل الأسئلة مرتبطة بالمصدر','ok':source_ready,'value':source_ready},
      {'id':'approval_gate','label':'كل الأسئلة معتمدة','ok':approval_ready,'value':approval_ready},
      {'id':'answer_coverage','label':'كل الأسئلة لها إجابة معتمدة','ok':answer_ready,'value':answer_ready},
      {'id':'qa_clear','label':'لا توجد ملاحظات QA مفتوحة','ok':qa_clear,'value':qa_clear},
      {'id':'lesson_coverage','label':'تغطية الدروس المتاحة','ok':lesson_cov>=.8,'value':round(lesson_cov*100)},
      {'id':'concept_coverage','label':'تنوع المفاهيم المتاحة','ok':concept_cov>=.8,'value':len(concepts)},
      {'id':'skill_coverage','label':'تنوع المهارات المتاحة','ok':skill_cov>=.67,'value':len(skills)},
      {'id':'difficulty_mix','label':'تنوع مستويات الصعوبة المتاحة','ok':len(diffs)>=required_diffs,'value':diffs},
      {'id':'question_type_mix','label':'تنوع أنواع الأسئلة المتاحة','ok':len(types)>=required_types,'value':types},
      {'id':'lesson_concentration','label':'عدم التركز في درس واحد','ok':max_lesson<=.6 or len(lessons)==1,'value':round(max_lesson*100)},
      {'id':'concept_concentration','label':'عدم التركز في مفهوم واحد','ok':max_concept<=.6 or len(concepts)==1,'value':round(max_concept*100)}]
    score=round(sum(1 for x in checks if x['ok'])*100/len(checks))
    return {'quiz_id':quiz_id,'ready':all(x['ok'] for x in checks),'score':score,'checks':checks,'coverage':{'lessons':len(lessons),'concepts':len(concepts),'skills':len(skills)},'difficulty':diffs,'question_types':types,'student_visible':False}

@app.post('/api/quizzes/{quiz_id}/publish',dependencies=[Depends(require_admin)])
def publish_quiz(quiz_id:int):
    quality=quiz_quality_check(quiz_id)
    if not quality.get('ready'):
        failed=[{'id':x['id'],'label':x['label'],'value':x.get('value')} for x in quality.get('checks',[]) if not x.get('ok')]
        suggestions={
          'lesson_coverage':'أعد إنشاء الاختبار بالخطة المتوازنة أو أضف أسئلة من الدروس غير المغطاة.',
          'concept_coverage':'اختر أسئلة تغطي مفاهيم إضافية بدل تكرار نفس المفاهيم.',
          'skill_coverage':'زد تنوع المهارات المقاسة داخل الاختبار.',
          'difficulty_mix':'استخدم توزيع صعوبة متوازنًا بين السهل والمتوسط والصعب.',
          'question_type_mix':'أضف أكثر من نوع سؤال عندما يسمح بنك الأسئلة بذلك.',
          'lesson_concentration':'قلل عدد الأسئلة من الدرس المسيطر ووزعها على دروس أخرى.',
          'concept_concentration':'استبدل بعض الأسئلة بأسئلة من مفاهيم أخرى.'}
        for x in failed:x['suggestion']=suggestions.get(x['id'],'حسّن هذا المعيار ثم أعد فحص الجودة.')
        raise HTTPException(409,{'message':'تم منع النشر لأن الاختبار لم يجتز بوابة الجودة','score':quality.get('score',0),'failed':failed})
    with connect() as con:
        old=con.execute("SELECT lifecycle_status FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        q=con.execute("""UPDATE quizzes SET published=TRUE,lifecycle_status='published',quality_score=%s,
          ready_at=COALESCE(ready_at,now()),published_at=now(),archived_at=NULL WHERE id=%s RETURNING id,title,published,lifecycle_status""",(quality['score'],quiz_id)).fetchone()
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score,details)
          VALUES(%s,'publish',%s,'published',%s,%s::jsonb)""",(quiz_id,old['lifecycle_status'] if old else None,quality['score'],'{"publication_gate":"passed"}'))
        if not q: raise HTTPException(404,'Quiz not found')
    return {**q,'quality_score':quality['score'],'publication_gate':'passed'}

@app.post('/api/quizzes/{quiz_id}/unpublish',dependencies=[Depends(require_admin)])
def unpublish_quiz(quiz_id:int):
    with connect() as con:
        old=con.execute("SELECT lifecycle_status FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        q=con.execute("UPDATE quizzes SET published=FALSE,lifecycle_status='ready' WHERE id=%s RETURNING id,title,published,lifecycle_status",(quiz_id,)).fetchone()
        if q: con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score)
          SELECT %s,'unpublish',%s,'ready',quality_score FROM quizzes WHERE id=%s""",(quiz_id,old['lifecycle_status'] if old else None,quiz_id))
        if not q: raise HTTPException(404,'Quiz not found')
    return q

@app.post('/api/quizzes/{quiz_id}/review',dependencies=[Depends(require_admin)])
def review_quiz(quiz_id:int):
    quality=quiz_quality_check(quiz_id)
    target='ready' if quality.get('ready') else 'quality_review'
    with connect() as con:
        old=con.execute("SELECT lifecycle_status FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        if not old: raise HTTPException(404,'Quiz not found')
        q=con.execute("""UPDATE quizzes SET lifecycle_status=%s,quality_score=%s,
          ready_at=CASE WHEN %s='ready' THEN COALESCE(ready_at,now()) ELSE NULL END
          WHERE id=%s RETURNING id,title,lifecycle_status,quality_score""",(target,quality.get('score'),target,quiz_id)).fetchone()
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score,details)
          VALUES(%s,'quality_review',%s,%s,%s,%s::jsonb)""",(quiz_id,old['lifecycle_status'],target,quality.get('score'),'{"automatic":true}'))
    return {**q,'quality':quality}

@app.post('/api/quizzes/{quiz_id}/archive',dependencies=[Depends(require_admin)])
def archive_quiz(quiz_id:int):
    with connect() as con:
        old=con.execute("SELECT lifecycle_status FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        if not old: raise HTTPException(404,'Quiz not found')
        q=con.execute("""UPDATE quizzes SET published=FALSE,lifecycle_status='archived',archived_at=now()
          WHERE id=%s RETURNING id,title,published,lifecycle_status,archived_at""",(quiz_id,)).fetchone()
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score)
          SELECT %s,'archive',%s,'archived',quality_score FROM quizzes WHERE id=%s""",(quiz_id,old['lifecycle_status'],quiz_id))
    return q

@app.get('/api/quizzes/{quiz_id}/audit',dependencies=[Depends(require_admin)])
def quiz_audit(quiz_id:int):
    with connect() as con:
        if not con.execute("SELECT 1 FROM quizzes WHERE id=%s",(quiz_id,)).fetchone(): raise HTTPException(404,'Quiz not found')
        return list(con.execute("""SELECT id,action,from_status,to_status,quality_score,actor,details,created_at
          FROM quiz_audit_log WHERE quiz_id=%s ORDER BY created_at DESC,id DESC""",(quiz_id,)).fetchall())

@app.get('/api/quizzes/{quiz_id}',dependencies=[Depends(require_admin)])
def quiz_detail(quiz_id:int):
    with connect() as con:
        q=con.execute('SELECT * FROM quizzes WHERE id=%s',(quiz_id,)).fetchone()
        if not q: raise HTTPException(404,'Quiz not found')
        items=list(con.execute("""SELECT qq.position,x.id,x.text_verbatim,x.question_type,x.difficulty,l.chapter,l.title lesson_title,
          d.filename source_filename,coalesce(x.source_page,x.page) source_page
          FROM quiz_questions qq JOIN questions x ON x.id=qq.question_id JOIN documents d ON d.id=x.document_id
          LEFT JOIN lessons l ON l.id=x.lesson_id WHERE qq.quiz_id=%s ORDER BY qq.position""",(quiz_id,)).fetchall())
        return {**q,'questions':items}

BUILDER=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>منشئ الاختبارات</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}.q{padding:10px;border-bottom:1px solid #eee}.muted{color:#667085;font-size:13px}</style><main><h1>منشئ الاختبارات</h1><div class="box row"><a href="/admin/dashboard">جلسة الإدارة</a><a href="/admin/bank">بنك الأسئلة</a></div><div class="box"><div class=row><input id=title value="اختبار" placeholder="اسم الاختبار"><input id=count type=number min=1 max=100 value=10><select id=subject><option value="">كل المواد</option></select><select id=grade><option value="">كل الصفوف</option></select><select id=curriculum><option value="">كل إصدارات المنهج</option></select><select id=term><option value="">كل الترمات</option></select><select id=unit><option value="">كل الوحدات</option></select><select id=chapter><option value="">كل الأبواب</option></select><select id=lesson><option value="">كل الدروس</option></select><select id=difficulty><option value="">كل الصعوبات</option><option value=easy>سهل</option><option value=medium>متوسط</option><option value=hard>صعب</option></select><select id=skill><option value="">كل المهارات</option></select><select id=qtype><option value="">كل الأنواع</option><option value=mcq>اختيار من متعدد</option><option value=numeric>مسألة حسابية</option><option value=essay>مقالي</option></select><input id=easyPct type=number min=0 max=100 placeholder="سهل %"><input id=mediumPct type=number min=0 max=100 placeholder="متوسط %"><input id=hardPct type=number min=0 max=100 placeholder="صعب %"><button onclick=blueprint()>اقتراح خطة متوازنة</button><button onclick=generate()>إنشاء اختبار</button></div><p class=muted>لن يدخل الاختبار إلا سؤال معتمد ومصنف وله قصاصة مصدر محفوظة.</p><div id=plan></div><div id=msg></div></div><div class=box id=result>حدد الشروط ثم أنشئ الاختبار.</div><div class=box id=quality style="display:none"></div></main><script>
let ls=[],catalog=null;function h(){return {}}function saveKey(){location.href='/admin/login'}async function init(){catalog=await fetch('/api/academic/catalog').then(r=>r.json());ls=await fetch('/api/lessons').then(r=>r.json());let skills=await fetch('/api/academic/skills').then(r=>r.json());skill.innerHTML='<option value="">كل المهارات</option>'+skills.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');subject.innerHTML='<option value="">اختر المادة</option>'+catalog.subjects.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');grade.innerHTML='<option value="">اختر الصف</option>'+catalog.grades.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');subject.onchange=()=>{grade.value='';renderAcademic(true)};grade.onchange=()=>renderAcademic(true);curriculum.onchange=()=>renderAcademic(false,true);term.onchange=()=>renderAcademic(false,false,true);unit.onchange=renderLessons;chapter.onchange=renderLessons;renderAcademic(true)}
function keep(el,html){let v=el.value;el.innerHTML=html;if([...el.options].some(o=>o.value==v))el.value=v}
function renderAcademic(resetCurr=false,resetTerm=false,resetUnit=false){let sid=Number(subject.value||0),gid=Number(grade.value||0);let cvs=catalog.curricula.filter(x=>(!sid||x.subject_id==sid)&&(!gid||x.grade_level_id==gid)&&x.active!==false);keep(curriculum,'<option value="">اختر إصدار المنهج</option>'+cvs.map(x=>`<option value="${x.id}">${x.subject_name} — ${x.grade_name} — ${x.academic_year}</option>`).join(''));if(resetCurr&&!cvs.some(x=>x.id==curriculum.value))curriculum.value='';let cv=Number(curriculum.value||0);let ts=cv?catalog.terms.filter(x=>x.curriculum_version_id==cv):[];keep(term,'<option value="">اختر الترم</option>'+ts.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join(''));if(resetTerm&&!ts.some(x=>x.id==term.value))term.value='';let tv=Number(term.value||0);let us=tv?catalog.units.filter(x=>x.term_id==tv):[];keep(unit,'<option value="">اختر الوحدة</option>'+us.map(x=>`<option value="${x.id}">${x.title}</option>`).join(''));if(resetUnit&&!us.some(x=>x.id==unit.value))unit.value='';renderLessons()}
async function blueprint(){if(!subject.value||!grade.value||!curriculum.value||!term.value){msg.textContent='حدد المادة والصف والمنهج والترم أولًا';return}let p=new URLSearchParams({count:count.value,subject_id:subject.value,grade_level_id:grade.value,curriculum_version_id:curriculum.value,term_id:term.value});if(unit.value)p.set('unit_id',unit.value);let r=await fetch('/api/quizzes/blueprint?'+p),x=await r.json();if(!r.ok){msg.textContent=x.detail||'تعذر إنشاء الخطة';return}if(!x.feasible){msg.textContent=x.message+' — المتاح '+x.available+' من '+x.requested;return}easyPct.value=x.recommended_mix.easy_pct;mediumPct.value=x.recommended_mix.medium_pct;hardPct.value=x.recommended_mix.hard_pct;difficulty.value='';plan.dataset.balanced='1';plan.innerHTML='<h3>الخطة المقترحة — سيتم الالتزام بتوزيع الدروس عند الإنشاء</h3><div class=muted>الصعوبة: سهل '+x.difficulty.easy+' · متوسط '+x.difficulty.medium+' · صعب '+x.difficulty.hard+'</div>'+x.lessons.map(v=>'<div class=q>'+esc(v.chapter||'')+' — '+esc(v.lesson_title)+' : <b>'+v.count+'</b> سؤال (متاح '+v.available+')</div>').join('');msg.textContent='تم إعداد Blueprint متوازن وتطبيق نسب الصعوبة تلقائيًا'}function renderLessons(){let a=ls.filter(x=>(!subject.value||x.subject_id==subject.value)&&(!grade.value||x.grade_level_id==grade.value)&&(!curriculum.value||x.curriculum_version_id==curriculum.value)&&(!term.value||x.term_id==term.value)&&(!unit.value||x.unit_id==unit.value));let cs=[...new Set(a.map(x=>x.chapter).filter(Boolean))];keep(chapter,'<option value="">كل الأبواب</option>'+cs.map(x=>`<option>${x}</option>`).join(''));a=a.filter(x=>(!chapter.value||x.chapter==chapter.value));keep(lesson,'<option value="">كل الدروس</option>'+a.map(x=>`<option value="${x.id}">${x.chapter||''} — ${x.title}</option>`).join(''))}async function generate(){msg.textContent='جارٍ الإنشاء...';let b={title:title.value||'اختبار',count:Number(count.value)};if(subject.value)b.subject_id=Number(subject.value);if(grade.value)b.grade_level_id=Number(grade.value);if(curriculum.value)b.curriculum_version_id=Number(curriculum.value);if(term.value)b.term_id=Number(term.value);if(unit.value)b.unit_id=Number(unit.value);if(chapter.value)b.chapter=chapter.value;if(lesson.value)b.lesson_id=Number(lesson.value);if(difficulty.value)b.difficulty=difficulty.value;if(qtype.value)b.question_type=qtype.value;if(skill.value)b.skill_id=Number(skill.value);if(easyPct.value!==''||mediumPct.value!==''||hardPct.value!==''){b.easy_pct=Number(easyPct.value||0);b.medium_pct=Number(mediumPct.value||0);b.hard_pct=Number(hardPct.value||0)}if(plan.dataset.balanced==='1')b.use_balanced_blueprint=truelet r=await fetch('/api/quizzes/generate',{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify(b)}),x=await r.json();if(!r.ok){msg.textContent=typeof x.detail==='object'?x.detail.message+' — المتاح: '+x.detail.available:(x.detail||'حدث خطأ');return}msg.textContent='تم إنشاء الاختبار #'+x.id+(x.coverage?' · تغطية '+x.coverage.concepts+' مفهوم و'+x.coverage.skills+' مهارة':'');show(x.id)}async function show(id){let [r,qr]=await Promise.all([fetch('/api/quizzes/'+id,{headers:h()}),fetch('/api/quizzes/'+id+'/quality-check',{headers:h()})]),x=await r.json(),qx=await qr.json();result.innerHTML='<h2>'+x.title+'</h2>'+x.questions.map(q=>`<div class=q><b>${q.position})</b> ${esc(q.text_verbatim)}<br><span class=muted>${q.chapter||''} — ${q.lesson_title||''} · ${q.difficulty} · المصدر: ${q.source_filename} ص ${q.source_page}</span></div>`).join('');quality.style.display='block';quality.innerHTML='<h2>جودة الاختبار: '+qx.score+'% — '+(qx.ready?'جاهز للنشر':'يحتاج تحسين')+'</h2>'+qx.checks.map(v=>'<div class=q>'+(v.ok?'✅ ':'⚠️ ')+esc(v.label)+'</div>').join('')+(qx.ready?'<button onclick="publishQuiz('+id+')">نشر الاختبار</button>':'<p class=muted>لن يسمح النظام بالنشر حتى تجتاز معايير الجودة.</p>')}async function publishQuiz(id){let r=await fetch('/api/quizzes/'+id+'/publish',{method:'POST',headers:h()}),x=await r.json();if(!r.ok){let d=x.detail||{};msg.textContent=d.message||'تعذر نشر الاختبار';if(d.failed)quality.innerHTML+='<h3>المطلوب قبل النشر</h3>'+d.failed.map(v=>'<div class=q>⚠️ '+esc(v.label)+' — '+esc(v.suggestion)+'</div>').join('');return}msg.textContent='تم نشر الاختبار بنجاح بعد اجتياز بوابة الجودة';await show(id)}
function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}init();</script></html>'''
@app.get('/admin/quiz-builder',response_class=HTMLResponse)
def quiz_builder(): return BUILDER
