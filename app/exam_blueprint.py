from __future__ import annotations

from collections import defaultdict

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin

# Historical ministry structure kept for traceability only. It is NOT the active
# project blueprint after the user's explicit 2026/2027 configuration decision.
HISTORICAL_OFFICIAL_REFERENCE = {
    'academic_year': '2024/2025',
    'subject': 'الفيزياء',
    'total_questions': 46,
    'objective_questions': 44,
    'essay_questions': 2,
    'total_marks': 60,
    'reference_authority': 'وزارة التربية والتعليم والتعليم الفني المصرية',
    'reference_url': 'https://moe.gov.eg/ar/what-s-on/news/new-old/',
    'status': 'historical_reference_only',
}

# Active project policy configured explicitly by the user.
ACTIVE_EXAM_BLUEPRINT = {
    'blueprint_id': 'physics-2026-2027-50-50-v1',
    'academic_year': '2026/2027',
    'subject': 'الفيزياء',
    'total_questions': 46,
    'objective_questions': 23,
    'essay_questions': 23,
    'objective_percentage': 50,
    'essay_percentage': 50,
    'source': 'user_configured_project_policy',
    'status': 'active',
    'content_policy': 'approved_pdf_only',
}


def _context(con):
    return con.execute("""SELECT cv.id curriculum_version_id,cv.academic_year,cv.subject_id,cv.grade_level_id,t.id term_id
      FROM curriculum_versions cv JOIN academic_terms t ON t.curriculum_version_id=cv.id
      WHERE cv.subject_id=1 AND cv.grade_level_id=6 AND cv.active=TRUE
      ORDER BY cv.id DESC,t.id LIMIT 1""").fetchone()


def _eligible_clause():
    return """q.approved=TRUE
      AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
      AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
      AND q.lesson_id IS NOT NULL
      AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id
        AND a.document_id=q.document_id AND a.page_number=coalesce(q.source_page,q.page))
      AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
      AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
      AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open')"""


def _eligible_rows(con, ctx, essay: bool):
    ready=_eligible_clause()
    type_filter="q.question_type='essay'" if essay else "q.question_type<>'essay'"
    return list(con.execute("""SELECT q.id,q.lesson_id,q.difficulty,q.question_type,l.sort_order lesson_order
      FROM questions q JOIN lessons l ON l.id=q.lesson_id
      WHERE """+ready+""" AND """+type_filter+"""
        AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
      ORDER BY l.sort_order,l.id,q.difficulty,q.id""",
      (ctx['subject_id'],ctx['grade_level_id'],ctx['curriculum_version_id'],ctx['term_id'])).fetchall())


def _balanced_pick(rows, count:int):
    by_lesson=defaultdict(list);order=[]
    for r in rows:
        lid=int(r['lesson_id'])
        if lid not in by_lesson: order.append(lid)
        by_lesson[lid].append(dict(r))
    picked=[];depth=0
    while len(picked)<count:
        progressed=False
        for lid in order:
            bucket=by_lesson[lid]
            if depth<len(bucket):
                picked.append(bucket[depth]);progressed=True
                if len(picked)>=count: break
        if not progressed: break
        depth+=1
    return picked


def blueprint_readiness():
    with connect() as con:
        ctx=_context(con)
        if not ctx:
            return {'active':False,'blueprint':ACTIVE_EXAM_BLUEPRINT,'historical_reference':HISTORICAL_OFFICIAL_REFERENCE}
        ready=_eligible_clause()
        params=(ctx['subject_id'],ctx['grade_level_id'],ctx['curriculum_version_id'],ctx['term_id'])
        counts=con.execute("""SELECT count(*) total,
          count(*) FILTER(WHERE q.question_type='essay') essay,
          count(*) FILTER(WHERE q.question_type<>'essay') objective,
          count(DISTINCT q.lesson_id) lessons,
          count(DISTINCT q.difficulty) difficulties
          FROM questions q WHERE """+ready+"""
          AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s""",params).fetchone()
        types=list(con.execute("""SELECT q.question_type label,count(*) n FROM questions q WHERE """+ready+"""
          AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
          GROUP BY q.question_type ORDER BY n DESC""",params).fetchall())
        difficulties=list(con.execute("""SELECT q.difficulty label,count(*) n FROM questions q WHERE """+ready+"""
          AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
          GROUP BY q.difficulty ORDER BY q.difficulty""",params).fetchall())
    objective=int(counts['objective'] or 0);essay=int(counts['essay'] or 0);total=int(counts['total'] or 0)
    target=ACTIVE_EXAM_BLUEPRINT
    feasible=objective>=target['objective_questions'] and essay>=target['essay_questions']
    gaps={
      'objective':max(0,target['objective_questions']-objective),
      'essay':max(0,target['essay_questions']-essay),
      'total':max(0,target['total_questions']-total),
    }
    return {
      'active':True,'curriculum':dict(ctx),'blueprint':target,
      'historical_reference':HISTORICAL_OFFICIAL_REFERENCE,
      'eligible':{'total':total,'objective':objective,'essay':essay,'lessons':int(counts['lessons'] or 0),'difficulties':int(counts['difficulties'] or 0)},
      'question_types':{r['label']:int(r['n']) for r in types},
      'difficulty':{r['label']:int(r['n']) for r in difficulties},
      'active_shape_feasible':feasible,
      'gaps':gaps,
      'policy':'46 سؤالًا = 23 اختيار من متعدد + 23 مقالي. لا يتم تحويل نوع سؤال أو اختراع محتوى لسد العجز؛ كل سؤال يجب أن يكون معتمدًا من PDF المصدر.',
    }


@app.get('/api/admin/exam-blueprint/physics',dependencies=[Depends(require_admin)])
def physics_exam_blueprint():
    return blueprint_readiness()


@app.post('/api/admin/exam-blueprint/physics/create',dependencies=[Depends(require_admin)])
def create_5050_physics_exam():
    """Create a draft 46-question 50/50 exam only when the approved PDF bank can satisfy it."""
    with connect() as con:
        ctx=_context(con)
        if not ctx: raise HTTPException(409,'لا يوجد منهج فيزياء نشط')
        objectives=_eligible_rows(con,ctx,False)
        essays=_eligible_rows(con,ctx,True)
        need_obj=ACTIVE_EXAM_BLUEPRINT['objective_questions'];need_essay=ACTIVE_EXAM_BLUEPRINT['essay_questions']
        if len(objectives)<need_obj or len(essays)<need_essay:
            raise HTTPException(409,{
              'message':'البنك المعتمد لا يكفي بعد لإنشاء امتحان 50% اختيار و50% مقالي دون اختراع محتوى.',
              'available':{'objective':len(objectives),'essay':len(essays)},
              'required':{'objective':need_obj,'essay':need_essay},
              'gaps':{'objective':max(0,need_obj-len(objectives)),'essay':max(0,need_essay-len(essays))},
            })
        obj_pick=_balanced_pick(objectives,need_obj);essay_pick=_balanced_pick(essays,need_essay)
        if len(obj_pick)!=need_obj or len(essay_pick)!=need_essay:
            raise HTTPException(409,'تعذر تحقيق التوزيع المتوازن على الدروس من البنك الحالي')
        quiz=con.execute("""INSERT INTO quizzes(title,published,lifecycle_status,duration_minutes,max_attempts,retry_wait_minutes,score_policy,
          subject_id,grade_level_id,curriculum_version_id,term_id)
          VALUES(%s,FALSE,'draft',180,1,0,'highest',%s,%s,%s,%s) RETURNING id,title""",
          ('محاكاة الفيزياء 2026/2027 — 50% اختيار + 50% مقالي',ctx['subject_id'],ctx['grade_level_id'],ctx['curriculum_version_id'],ctx['term_id'])).fetchone()
        # Interleave question types so the exam is not split into two artificial blocks.
        merged=[]
        for i in range(max(len(obj_pick),len(essay_pick))):
            if i<len(obj_pick): merged.append(obj_pick[i])
            if i<len(essay_pick): merged.append(essay_pick[i])
        for pos,r in enumerate(merged,1):
            con.execute("INSERT INTO quiz_questions(quiz_id,question_id,position,points) VALUES(%s,%s,%s,1)",(quiz['id'],r['id'],pos))
        con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,details)
          VALUES(%s,'create_5050_blueprint',NULL,'draft',%s::jsonb)""",
          (quiz['id'],'{"blueprint_id":"physics-2026-2027-50-50-v1","objective":23,"essay":23,"content":"approved_pdf_only"}'))
    return {'id':quiz['id'],'title':quiz['title'],'published':False,'lifecycle_status':'draft','question_count':46,
            'objective_questions':23,'essay_questions':23,'blueprint_id':ACTIVE_EXAM_BLUEPRINT['blueprint_id']}


PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>جاهزية امتحان الفيزياء 50/50</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1050px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.n{font-size:28px;font-weight:800}.muted{color:#667085}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}button{padding:11px 15px;border:0;border-radius:10px;background:#175cd3;color:#fff;font-weight:700;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/question-bank-balance">توازن البنك</a> · <a href="/admin/quiz-builder">منشئ الاختبارات</a></div>
<div class=box><h1>Blueprint امتحان الفيزياء 2026/2027</h1><div id=active></div><p class=muted>المواصفة النشطة للمشروع: 46 سؤالًا بنسبة 50% اختيار من متعدد و50% مقالي. المرجع الوزاري السابق محفوظ تاريخيًا فقط ولا يتحكم في إنشاء الامتحانات الجديدة.</p></div>
<div class=box><h2>جاهزية البنك الحالي</h2><div id=cards class=grid></div><div id=status></div><button id=createBtn onclick=createExam()>إنشاء محاكاة 50/50</button><div id=createMsg class=muted style="margin-top:10px"></div></div>
<div class=box><h2>الفجوات</h2><div id=gaps class=grid></div></div>
<div class=box><h2>المرجع التاريخي</h2><div id=history class=muted></div></div>
<script>function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}let state=null;async function load(){let r=await fetch('/api/admin/exam-blueprint/physics');if(r.status===401){location.href='/admin/login';return}let x=state=await r.json(),z=x.blueprint,h=x.historical_reference;active.innerHTML='<div class=card><b>'+z.total_questions+' سؤال</b><div>'+z.objective_questions+' اختيار من متعدد ('+z.objective_percentage+'%) + '+z.essay_questions+' مقالي ('+z.essay_percentage+'%)</div></div>';let a=x.eligible;cards.innerHTML=[['جاهز كليًا',a.total],['اختيار/موضوعي',a.objective],['مقالي',a.essay],['الدروس المغطاة',a.lessons],['مستويات الصعوبة',a.difficulties]].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class=n>'+v[1]+'</div></div>').join('');status.innerHTML='<p class="'+(x.active_shape_feasible?'ok':'warn')+'"><b>'+(x.active_shape_feasible?'البنك قادر حاليًا على بناء امتحان 23+23 دون اختراع محتوى.':'الامتحان 23+23 غير جاهز بعد؛ النظام سيمنع الإنشاء حتى يكتمل النوع الناقص.')+'</b></p>';createBtn.disabled=!x.active_shape_feasible;gaps.innerHTML=[['نقص الاختياري',x.gaps.objective],['نقص المقالي',x.gaps.essay],['نقص الإجمالي',x.gaps.total]].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class="n '+(v[1]?'bad':'ok')+'">'+v[1]+'</div></div>').join('');history.innerHTML='مرجع '+e(h.academic_year)+': '+h.total_questions+' سؤال ('+h.objective_questions+' موضوعي + '+h.essay_questions+' مقالي) — محفوظ للتوثيق فقط.'}async function createExam(){createBtn.disabled=true;createMsg.textContent='جارٍ الإنشاء...';let r=await fetch('/api/admin/exam-blueprint/physics/create',{method:'POST'}),x=await r.json().catch(()=>({}));if(r.ok){createMsg.innerHTML='<span class=ok>تم إنشاء الاختبار كمسودة رقم #'+x.id+'. راجعه ثم انشره من منشئ الاختبارات.</span>'}else{createMsg.innerHTML='<span class=bad>'+e(x.detail?.message||x.detail||'تعذر إنشاء الاختبار')+'</span>';createBtn.disabled=false}}load()</script></main></html>'''

@app.get('/admin/exam-blueprint/physics',response_class=HTMLResponse)
def physics_exam_blueprint_page(): return PAGE
