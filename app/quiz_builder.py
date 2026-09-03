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
    subject_id: int | None = None
    grade_level_id: int | None = None
    curriculum_version_id: int | None = None
    term_id: int | None = None
    unit_id: int | None = None

@app.post('/api/quizzes/generate',dependencies=[Depends(require_admin)])
def generate_quiz(p:QuizGenerate):
    if p.count<1 or p.count>100: raise HTTPException(400,'عدد الأسئلة يجب أن يكون من 1 إلى 100')
    if p.difficulty and p.difficulty not in {'easy','medium','hard'}: raise HTTPException(400,'Invalid difficulty')
    sql="""SELECT q.id FROM questions q LEFT JOIN lessons l ON l.id=q.lesson_id
      WHERE q.approved=TRUE AND q.lesson_id IS NOT NULL AND q.question_type<>'unknown'
      AND q.difficulty<>'unclassified'
      AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)"""
    params=[]
    if p.subject_id: sql+=' AND q.subject_id=%s';params.append(p.subject_id)
    if p.grade_level_id: sql+=' AND q.grade_level_id=%s';params.append(p.grade_level_id)
    if p.curriculum_version_id: sql+=' AND q.curriculum_version_id=%s';params.append(p.curriculum_version_id)
    if p.term_id: sql+=' AND q.term_id=%s';params.append(p.term_id)
    if p.unit_id: sql+=' AND q.unit_id=%s';params.append(p.unit_id)
    if p.subject_id: sql+=' AND q.subject_id=%s';params.append(p.subject_id)
    if p.grade_level_id: sql+=' AND q.grade_level_id=%s';params.append(p.grade_level_id)
    if p.curriculum_version_id: sql+=' AND q.curriculum_version_id=%s';params.append(p.curriculum_version_id)
    if p.term_id: sql+=' AND q.term_id=%s';params.append(p.term_id)
    if p.unit_id: sql+=' AND q.unit_id=%s';params.append(p.unit_id)
    if p.lesson_id: sql+=' AND q.lesson_id=%s';params.append(p.lesson_id)
    if p.chapter: sql+=' AND l.chapter=%s';params.append(p.chapter)
    if p.difficulty: sql+=' AND q.difficulty=%s';params.append(p.difficulty)
    if p.question_type: sql+=' AND q.question_type=%s';params.append(p.question_type)
    sql+=' ORDER BY random() LIMIT %s';params.append(p.count)
    with connect() as con:
        rows=con.execute(sql,params).fetchall()
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

BUILDER=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>منشئ الاختبارات</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}.q{padding:10px;border-bottom:1px solid #eee}.muted{color:#667085;font-size:13px}</style><main><h1>منشئ الاختبارات</h1><div class="box row"><input id=key type=password placeholder="ADMIN_API_KEY"><button onclick=saveKey()>حفظ المفتاح</button><a href="/admin/bank">بنك الأسئلة</a></div><div class="box"><div class=row><input id=title value="اختبار" placeholder="اسم الاختبار"><input id=count type=number min=1 max=100 value=10><select id=chapter><option value="">كل الأبواب</option></select><select id=lesson><option value="">كل الدروس</option></select><select id=difficulty><option value="">كل الصعوبات</option><option value=easy>سهل</option><option value=medium>متوسط</option><option value=hard>صعب</option></select><select id=qtype><option value="">كل الأنواع</option><option value=mcq>اختيار من متعدد</option><option value=numeric>مسألة حسابية</option><option value=essay>مقالي</option></select><button onclick=generate()>إنشاء اختبار</button></div><p class=muted>لن يدخل الاختبار إلا سؤال معتمد ومصنف وله قصاصة مصدر محفوظة.</p><div id=msg></div></div><div class=box id=result>حدد الشروط ثم أنشئ الاختبار.</div></main><script>
let ls=[],catalog=null;key.value=localStorage.pk||'';function h(){return {'X-Admin-Key':localStorage.pk||''}}function saveKey(){localStorage.pk=key.value;msg.textContent='تم حفظ المفتاح'}async function init(){catalog=await fetch('/api/academic/catalog').then(r=>r.json());ls=await fetch('/api/lessons').then(r=>r.json());subject.innerHTML='<option value="">كل المواد</option>'+catalog.subjects.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');grade.innerHTML='<option value="">كل الصفوف</option>'+catalog.grades.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');curriculum.innerHTML='<option value="">كل إصدارات المنهج</option>'+catalog.curricula.map(x=>`<option value="${x.id}">${x.subject_name} — ${x.grade_name} — ${x.academic_year}</option>`).join('');renderAcademic();subject.onchange=renderAcademic;grade.onchange=renderAcademic;curriculum.onchange=renderAcademic;term.onchange=renderAcademic;unit.onchange=renderLessons;let cs=[...new Set(ls.map(x=>x.chapter))];chapter.innerHTML='<option value="">كل الأبواب</option>'+cs.map(x=>`<option>${x}</option>`).join('');renderLessons();chapter.onchange=renderLessons}function renderAcademic(){let cv=curriculum.value?Number(curriculum.value):null;let ts=cv?catalog.terms.filter(x=>x.curriculum_version_id==cv):catalog.terms;term.innerHTML='<option value="">كل الترمات</option>'+ts.map(x=>`<option value="${x.id}">${x.name_ar}</option>`).join('');let tv=term.value?Number(term.value):null;let us=tv?catalog.units.filter(x=>x.term_id==tv):catalog.units;unit.innerHTML='<option value="">كل الوحدات</option>'+us.map(x=>`<option value="${x.id}">${x.title}</option>`).join('');renderLessons()}function renderLessons(){let a=ls.filter(x=>(!subject.value||x.subject_id==subject.value)&&(!grade.value||x.grade_level_id==grade.value)&&(!curriculum.value||x.curriculum_version_id==curriculum.value)&&(!term.value||x.term_id==term.value)&&(!unit.value||x.unit_id==unit.value)&&(!chapter.value||x.chapter==chapter.value));lesson.innerHTML='<option value="">كل الدروس</option>'+a.map(x=>`<option value="${x.id}">${x.chapter} — ${x.title}</option>`).join('')}async function generate(){msg.textContent='جارٍ الإنشاء...';let b={title:title.value||'اختبار',count:Number(count.value)};if(chapter.value)b.chapter=chapter.value;if(lesson.value)b.lesson_id=Number(lesson.value);if(difficulty.value)b.difficulty=difficulty.value;if(qtype.value)b.question_type=qtype.value;let r=await fetch('/api/quizzes/generate',{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify(b)}),x=await r.json();if(!r.ok){msg.textContent=typeof x.detail==='object'?x.detail.message+' — المتاح: '+x.detail.available:(x.detail||'حدث خطأ');return}msg.textContent='تم إنشاء الاختبار #'+x.id;show(x.id)}async function show(id){let r=await fetch('/api/quizzes/'+id,{headers:h()}),x=await r.json();result.innerHTML='<h2>'+x.title+'</h2>'+x.questions.map(q=>`<div class=q><b>${q.position})</b> ${esc(q.text_verbatim)}<br><span class=muted>${q.chapter||''} — ${q.lesson_title||''} · ${q.difficulty} · المصدر: ${q.source_filename} ص ${q.source_page}</span></div>`).join('')}function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}init();</script></html>'''
@app.get('/admin/quiz-builder',response_class=HTMLResponse)
def quiz_builder(): return BUILDER
