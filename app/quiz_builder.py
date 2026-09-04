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
        if any(v is not None for v in mix):
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
        quiz=con.execute("""INSERT INTO quizzes(title,published,subject_id,grade_level_id,curriculum_version_id,term_id)
          VALUES (%s,FALSE,%s,%s,%s,%s) RETURNING id,title,published""",
          (p.title,p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id)).fetchone()
        for i,r in enumerate(rows,1):
            con.execute("INSERT INTO quiz_questions(quiz_id,question_id,position) VALUES (%s,%s,%s)",(quiz['id'],r['id'],i))
        return {**quiz,'question_count':len(rows),'question_ids':[r['id'] for r in rows]}

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

BUILDER=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>منشئ الاختبارات</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}.q{padding:10px;border-bottom:1px solid #eee}.muted{color:#667085;font-size:13px}</style><main><h1>منشئ الاختبارات</h1><div class="box row"><a href="/admin/dashboard">جلسة الإدارة</a><a href="/admin/bank">بنك الأسئلة</a></div><div class="box"><div class=row><input id=title value="اختبار" placeholder="اسم الاختبار"><input id=count type=number min=1 max=100 value=10><select id=subject><option value="">كل المواد</option></select><select id=grade><option value="">كل الصفوف</option></select><select id=curriculum><option value="">كل إصدارات المنهج</option></select><select id=term><option value="">كل الترمات</option></select><select id=unit><option value="">كل الوحدات</option></select><select id=chapter><option value="">كل الأبواب</option></select><select id=lesson><option value="">كل الدروس</option></select><select id=difficulty><option value="">كل الصعوبات</option><option value=easy>سهل</option><option value=medium>متوسط</option><option value=hard>صعب</option></select><select id=skill><option value="">كل المهارات</option></select><select id=qtype><option value="">كل الأنواع</option><option value=mcq>اختيار من متعدد</option><option value=numeric>مسألة حسابية</option><option value=essay>مقالي</option></select><input id=easyPct type=number min=0 max=100 placeholder="سهل %"><input id=mediumPct type=number min=0 max=100 placeholder="متوسط %"><input id=hardPct type=number min=0 max=100 placeholder="صعب %"><button onclick=generate()>إنشاء اختبار</button></div><p class=muted>لن يدخل الاختبار إلا سؤال معتمد ومصنف وله قصاصة مصدر محفوظة.</p><div id=msg></div></div><div class=box id=result>حدد الشروط ثم أنشئ الاختبار.</div></main><script>
let ls=[],catalog=null;function h(){return {}}function saveKey(){location.href='/admin/login'}async function init(){catalog=await fetch('/api/academic/catalog').then(r=>r.json());ls=await fetch('/api/lessons').then(r=>r.json());let skills=await fetch('/api/academic/skills').then(r=>r.json());skill.innerHTML='<option value="">كل المهارات</option>'+skills.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');subject.innerHTML='<option value="">كل المواد</option>'+catalog.subjects.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');grade.innerHTML='<option value="">كل الصفوف</option>'+catalog.grades.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');curriculum.innerHTML='<option value="">كل إصدارات المنهج</option>'+catalog.curricula.map(x=>`<option value="${x.id}">${x.subject_name} — ${x.grade_name} — ${x.academic_year}</option>`).join('');renderAcademic();subject.onchange=renderAcademic;grade.onchange=renderAcademic;curriculum.onchange=renderAcademic;term.onchange=renderAcademic;unit.onchange=renderLessons;let cs=[...new Set(ls.map(x=>x.chapter))];chapter.innerHTML='<option value="">كل الأبواب</option>'+cs.map(x=>`<option>${x}</option>`).join('');renderLessons();chapter.onchange=renderLessons}function renderAcademic(){let cv=curriculum.value?Number(curriculum.value):null;let ts=cv?catalog.terms.filter(x=>x.curriculum_version_id==cv):catalog.terms;term.innerHTML='<option value="">كل الترمات</option>'+ts.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');let tv=term.value?Number(term.value):null;let us=tv?catalog.units.filter(x=>x.term_id==tv):catalog.units;unit.innerHTML='<option value="">كل الوحدات</option>'+us.map(x=>`<option value="${x.id}">${x.title}</option>`).join('');renderLessons()}function renderLessons(){let a=ls.filter(x=>(!subject.value||x.subject_id==subject.value)&&(!grade.value||x.grade_level_id==grade.value)&&(!curriculum.value||x.curriculum_version_id==curriculum.value)&&(!term.value||x.term_id==term.value)&&(!unit.value||x.unit_id==unit.value)&&(!chapter.value||x.chapter==chapter.value));lesson.innerHTML='<option value="">كل الدروس</option>'+a.map(x=>`<option value="${x.id}">${x.chapter} — ${x.title}</option>`).join('')}async function generate(){msg.textContent='جارٍ الإنشاء...';let b={title:title.value||'اختبار',count:Number(count.value)};if(subject.value)b.subject_id=Number(subject.value);if(grade.value)b.grade_level_id=Number(grade.value);if(curriculum.value)b.curriculum_version_id=Number(curriculum.value);if(term.value)b.term_id=Number(term.value);if(unit.value)b.unit_id=Number(unit.value);if(chapter.value)b.chapter=chapter.value;if(lesson.value)b.lesson_id=Number(lesson.value);if(difficulty.value)b.difficulty=difficulty.value;if(qtype.value)b.question_type=qtype.value;if(skill.value)b.skill_id=Number(skill.value);if(easyPct.value!==''||mediumPct.value!==''||hardPct.value!==''){b.easy_pct=Number(easyPct.value||0);b.medium_pct=Number(mediumPct.value||0);b.hard_pct=Number(hardPct.value||0)}let r=await fetch('/api/quizzes/generate',{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify(b)}),x=await r.json();if(!r.ok){msg.textContent=typeof x.detail==='object'?x.detail.message+' — المتاح: '+x.detail.available:(x.detail||'حدث خطأ');return}msg.textContent='تم إنشاء الاختبار #'+x.id;show(x.id)}async function show(id){let r=await fetch('/api/quizzes/'+id,{headers:h()}),x=await r.json();result.innerHTML='<h2>'+x.title+'</h2>'+x.questions.map(q=>`<div class=q><b>${q.position})</b> ${esc(q.text_verbatim)}<br><span class=muted>${q.chapter||''} — ${q.lesson_title||''} · ${q.difficulty} · المصدر: ${q.source_filename} ص ${q.source_page}</span></div>`).join('')}function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}init();</script></html>'''
@app.get('/admin/quiz-builder',response_class=HTMLResponse)
def quiz_builder(): return BUILDER
