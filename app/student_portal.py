from __future__ import annotations
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .adaptive_practice import build_adaptive_practice

@app.get("/api/student/portal")
def student_portal(student_code:str):
    code=student_code.strip()
    with connect() as con:
        st=con.execute("SELECT id,name,external_code FROM students WHERE external_code=%s",(code,)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        attempts=list(con.execute("""SELECT a.id,a.quiz_id,q.title quiz_title,a.score,a.max_score,a.completed_at,
          round(100.0*a.score/nullif(a.max_score,0),1) percentage
          FROM attempts a LEFT JOIN quizzes q ON q.id=a.quiz_id
          WHERE a.student_id=%s ORDER BY a.completed_at DESC NULLS LAST,a.id DESC LIMIT 10""",(st["id"],)).fetchall())
        errors=list(con.execute("""SELECT aa.question_id,q.text_verbatim,count(*) wrong_count,max(a.completed_at) last_wrong
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
          WHERE a.student_id=%s AND aa.is_correct=FALSE
          GROUP BY aa.question_id,q.text_verbatim ORDER BY wrong_count DESC,last_wrong DESC LIMIT 8""",(st["id"],)).fetchall())
        improvement=con.execute("""WITH x AS (
          SELECT a.id,a.completed_at,100.0*a.score/nullif(a.max_score,0) pct,
                 row_number() OVER(ORDER BY a.completed_at DESC NULLS LAST,a.id DESC) rn
          FROM attempts a WHERE a.student_id=%s AND a.max_score>0)
          SELECT max(pct) FILTER(WHERE rn=1) latest,max(pct) FILTER(WHERE rn=2) previous FROM x WHERE rn<=2""",(st["id"],)).fetchone()
    adaptive=build_adaptive_practice(st["id"],10)
    latest=float(improvement["latest"]) if improvement and improvement["latest"] is not None else None
    previous=float(improvement["previous"]) if improvement and improvement["previous"] is not None else None
    return {"student":st,"attempts":attempts,"errors":errors,"adaptive":adaptive,
            "improvement":{"latest":latest,"previous":previous,"delta":round(latest-previous,1) if latest is not None and previous is not None else None}}

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>بوابة الطالب</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.big{font-size:26px;font-weight:800}.muted{color:#667085}.good{color:#067647}.bad{color:#b42318}input,button{padding:11px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}button{cursor:pointer}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}@media(max-width:600px){table{font-size:13px}}</style><main>
<div class=box><h1>بوابة الطالب</h1><input id=code placeholder="كود الطالب"><button onclick=load()>دخول</button><div id=msg class=muted></div></div><div id=content></div>
<script>function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}async function load(){let r=await fetch('/api/student/portal?student_code='+encodeURIComponent(code.value)),x=await r.json();if(!r.ok){msg.textContent=x.detail||'تعذر الدخول';return}let d=x.improvement.delta;content.innerHTML=`<div class=box><h2>${esc(x.student.name)}</h2><div class=grid><div class=card><div class=muted>آخر نتيجة</div><div class=big>${x.improvement.latest??'—'}%</div></div><div class=card><div class=muted>التغير عن المحاولة السابقة</div><div class="big ${d==null?'':d>=0?'good':'bad'}">${d==null?'—':(d>0?'+':'')+d+'%'}</div></div><div class=card><div class=muted>أسئلة علاجية مقترحة</div><div class=big>${x.adaptive.questions?.length||0}</div></div></div></div><div class=box><h2>خطة المراجعة</h2>${x.adaptive.questions?.length?'<p>تم اكتشاف نقاط تحتاج مراجعة. التدريب يستخدم الأسئلة الأصلية المعتمدة فقط.</p><button onclick="practice()">ابدأ التدريب العلاجي</button>':'<p class=muted>'+esc(x.adaptive.reason||'لا توجد نقاط ضعف مؤكدة حاليًا')+'</p>'}</div><div class=box><h2>آخر النتائج</h2><table><tr><th>الاختبار</th><th>النتيجة</th><th>التاريخ</th></tr>${x.attempts.map(a=>'<tr><td>'+esc(a.quiz_title||'اختبار')+'</td><td>'+esc(a.percentage??'—')+'%</td><td>'+esc(a.completed_at||'')+'</td></tr>').join('')}</table></div><div class=box><h2>سجل الأخطاء المتكررة</h2>${x.errors.length?x.errors.map(e=>'<div class=card><b>'+esc(e.text_verbatim)+'</b><div class=muted>عدد مرات الخطأ: '+e.wrong_count+'</div></div>').join(''):'<p class=muted>لا توجد أخطاء مسجلة بعد.</p>'}</div>`}async function practice(){let r=await fetch('/api/student/adaptive-practice/create?student_code='+encodeURIComponent(code.value)+'&count=10',{method:'POST'}),x=await r.json();if(!r.ok){msg.textContent=typeof x.detail==='string'?x.detail:JSON.stringify(x.detail);return}location.href=x.student_path}</script></main></html>'''
@app.get("/student",response_class=HTMLResponse)
def portal_page(): return PAGE
