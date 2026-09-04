from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

@app.get("/api/admin/attempts/{attempt_id}/report",dependencies=[Depends(require_admin)])
def attempt_report(attempt_id:int):
    with connect() as con:
        a=con.execute("""SELECT a.id,a.student_id,a.quiz_id,a.score,a.max_score,a.started_at,a.completed_at,a.submitted_at,
          s.name student_name,s.external_code,qz.title quiz_title
          FROM attempts a JOIN students s ON s.id=a.student_id LEFT JOIN quizzes qz ON qz.id=a.quiz_id
          WHERE a.id=%s""",(attempt_id,)).fetchone()
        if not a: raise HTTPException(404,"Attempt not found")
        answers=list(con.execute("""SELECT aa.question_id,aa.answer_text,aa.is_correct,aa.points_awarded,
          q.text_verbatim,q.accepted_answer,q.solution_verbatim,q.difficulty,q.question_type,q.source_page,
          l.id lesson_id,l.chapter,l.title lesson_title
          FROM attempt_answers aa JOIN questions q ON q.id=aa.question_id LEFT JOIN lessons l ON l.id=q.lesson_id
          WHERE aa.attempt_id=%s ORDER BY aa.id""",(attempt_id,)).fetchall())
        lessons=list(con.execute("""SELECT coalesce(l.title,'غير مصنف') lesson,
          count(*) total,count(*) FILTER(WHERE aa.is_correct=TRUE) correct,count(*) FILTER(WHERE aa.is_correct=FALSE) incorrect,
          round(100.0*count(*) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(*),0),1) percentage
          FROM attempt_answers aa JOIN questions q ON q.id=aa.question_id LEFT JOIN lessons l ON l.id=q.lesson_id
          WHERE aa.attempt_id=%s GROUP BY l.id,l.title ORDER BY percentage ASC NULLS LAST""",(attempt_id,)).fetchall())
        difficulty=list(con.execute("""SELECT q.difficulty,count(*) total,
          count(*) FILTER(WHERE aa.is_correct=TRUE) correct,count(*) FILTER(WHERE aa.is_correct=FALSE) incorrect,
          round(100.0*count(*) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(*),0),1) percentage
          FROM attempt_answers aa JOIN questions q ON q.id=aa.question_id WHERE aa.attempt_id=%s
          GROUP BY q.difficulty ORDER BY q.difficulty""",(attempt_id,)).fetchall())
        history=list(con.execute("""SELECT a.id,q.title quiz_title,a.score,a.max_score,
          round(CASE WHEN a.max_score>0 THEN a.score/a.max_score*100 ELSE 0 END,1) percentage,
          coalesce(a.completed_at,a.submitted_at) completed_at
          FROM attempts a LEFT JOIN quizzes q ON q.id=a.quiz_id WHERE a.student_id=%s
          ORDER BY coalesce(a.completed_at,a.submitted_at) DESC LIMIT 20""",(a["student_id"],)).fetchall())
        pct=round(float(a["score"] or 0)/float(a["max_score"] or 1)*100,1) if a["max_score"] else 0
        return {"attempt":{**a,"percentage":pct},"answers":answers,"lessons":lessons,"difficulty":difficulty,"history":history}

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>تقرير نتيجة الطالب</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:#fff;padding:16px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{background:#f8fafc;border:1px solid #e6eaf0;padding:13px;border-radius:13px}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}.bad{color:#b42318}.ok{color:#067647}.muted{color:#667085;font-size:13px}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}.q{border:1px solid #e6eaf0;border-radius:12px;padding:12px;margin:9px 0}@media(max-width:700px){table{font-size:12px}}</style><main>
<div class=box><input id=key type=password placeholder=ADMIN_API_KEY><button onclick=save()>فتح التقرير</button> <a href="/admin/dashboard">لوحة التحكم</a></div><div id=head></div><div id=lesson></div><div id=diff></div><div id=wrong></div><div id=history></div>
<script>key.value='';let id=Number(location.pathname.split('/').pop());const H=()=>({'X-Admin-Key':''});function save(){load()}function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){let r=await fetch('/api/admin/attempts/'+id+'/report',{headers:H()});if(!r.ok){head.innerHTML='<div class=box>تحقق من مفتاح الإدارة أو رقم المحاولة.</div>';return}let x=await r.json(),a=x.attempt;head.innerHTML=`<div class=box><h1>${e(a.student_name)}</h1><div class=muted>${e(a.quiz_title||'اختبار')} · كود الطالب: ${e(a.external_code||'—')}</div><div class=cards><div class=card>الدرجة<h2>${a.score} / ${a.max_score}</h2></div><div class=card>النسبة<h2>${a.percentage}%</h2></div><div class=card>الأسئلة<h2>${x.answers.length}</h2></div><div class=card>الأخطاء<h2>${x.answers.filter(z=>z.is_correct===false).length}</h2></div></div></div>`;
lesson.innerHTML='<div class=box><h2>الأداء حسب الدرس</h2><table><tr><th>الدرس</th><th>صحيح</th><th>خطأ</th><th>النسبة</th></tr>'+x.lessons.map(z=>`<tr><td>${e(z.lesson)}</td><td>${z.correct}</td><td>${z.incorrect}</td><td>${z.percentage??0}%</td></tr>`).join('')+'</table></div>';
diff.innerHTML='<div class=box><h2>الأداء حسب مستوى الصعوبة</h2><table><tr><th>المستوى</th><th>صحيح</th><th>خطأ</th><th>النسبة</th></tr>'+x.difficulty.map(z=>`<tr><td>${e(z.difficulty)}</td><td>${z.correct}</td><td>${z.incorrect}</td><td>${z.percentage??0}%</td></tr>`).join('')+'</table></div>';
let w=x.answers.filter(z=>z.is_correct===false);wrong.innerHTML='<div class=box><h2>الأسئلة التي أخطأ فيها الطالب</h2>'+(w.length?w.map(z=>`<div class=q><b>${e(z.lesson_title||'غير مصنف')} · ${e(z.difficulty)}</b><p>${e(z.text_verbatim)}</p><div class=bad>إجابة الطالب: ${e(z.answer_text||'بدون إجابة')}</div><div class=ok>الإجابة المعتمدة: ${e(z.accepted_answer||'—')}</div>${z.solution_verbatim?'<div class=muted>الحل من المصدر: '+e(z.solution_verbatim)+'</div>':''}</div>`).join(''):'<p class=ok>لم يسجل الطالب إجابات خاطئة.</p>')+'</div>';
history.innerHTML='<div class=box><h2>سجل محاولات الطالب</h2><table><tr><th>الاختبار</th><th>النسبة</th><th>التاريخ</th></tr>'+x.history.map(z=>`<tr><td><a href="/admin/results/${z.id}">${e(z.quiz_title||'اختبار')}</a></td><td>${z.percentage}%</td><td>${e(z.completed_at)}</td></tr>`).join('')+'</table></div>'}load()</script></main></html>'''
@app.get("/admin/results/{attempt_id}",response_class=HTMLResponse)
def result_page(attempt_id:int): return PAGE
