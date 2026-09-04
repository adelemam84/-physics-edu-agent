from __future__ import annotations
from fastapi import Depends
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

@app.get("/api/admin/progress",dependencies=[Depends(require_admin)])
def progress_dashboard():
    with connect() as con:
        summary=con.execute("""SELECT count(DISTINCT s.id) students,count(DISTINCT a.id) attempts,
          round(avg(100.0*a.score/nullif(a.max_score,0)),1) avg_score
          FROM students s LEFT JOIN attempts a ON a.student_id=s.id""").fetchone()
        by_subject=list(con.execute("""SELECT sub.id,sub.name_ar,count(DISTINCT a.id) attempts,
          round(avg(100.0*a.score/nullif(a.max_score,0)),1) avg_score
          FROM subjects sub LEFT JOIN questions q ON q.subject_id=sub.id
          LEFT JOIN attempt_answers aa ON aa.question_id=q.id LEFT JOIN attempts a ON a.id=aa.attempt_id
          GROUP BY sub.id,sub.name_ar ORDER BY sub.name_ar""").fetchall())
        weak=list(con.execute("""SELECT s.id student_id,s.name student_name,l.title lesson_title,sub.name_ar subject_name,
          count(aa.id) answers,round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
          FROM students s JOIN attempts a ON a.student_id=s.id JOIN attempt_answers aa ON aa.attempt_id=a.id
          JOIN questions q ON q.id=aa.question_id JOIN lessons l ON l.id=q.lesson_id LEFT JOIN subjects sub ON sub.id=q.subject_id
          GROUP BY s.id,s.name,l.id,l.title,sub.name_ar HAVING count(aa.id)>=3
          ORDER BY mastery ASC LIMIT 20""").fetchall())
        return {"summary":summary,"subjects":by_subject,"weakest":weak}

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>متابعة تقدم الطلاب</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.big{font-size:26px;font-weight:800}.bad{color:#b42318}.muted{color:#667085}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}</style><main>
<div class=box><input id=key type=password placeholder=ADMIN_API_KEY><button onclick=load()>فتح التقرير</button> <a href="/admin/dashboard">لوحة التحكم</a></div><div id=content></div>
<script>key.value='';function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}async function load(){let r=await fetch('/api/admin/progress',{headers:{'X-Admin-Key':key.value}});if(!r.ok){content.innerHTML='<div class=box>تعذر فتح التقرير</div>';return}let x=await r.json();content.innerHTML=`<div class=box><h1>متابعة تقدم الطلاب</h1><div class=grid><div class=card><div class=muted>الطلاب</div><div class=big>${x.summary.students||0}</div></div><div class=card><div class=muted>المحاولات</div><div class=big>${x.summary.attempts||0}</div></div><div class=card><div class=muted>متوسط النتائج</div><div class=big>${x.summary.avg_score||0}%</div></div></div></div><div class=box><h2>حسب المادة</h2><div class=grid>${x.subjects.map(s=>'<div class=card><b>'+esc(s.name_ar)+'</b><div class=big>'+esc(s.avg_score||0)+'%</div><div class=muted>'+s.attempts+' محاولة</div></div>').join('')}</div></div><div class=box><h2>أولوية التدخل</h2><table><tr><th>الطالب</th><th>المادة</th><th>الدرس</th><th>الإتقان</th><th></th></tr>${x.weakest.map(w=>'<tr><td>'+esc(w.student_name)+'</td><td>'+esc(w.subject_name||'')+'</td><td>'+esc(w.lesson_title)+'</td><td class=bad>'+esc(w.mastery)+'%</td><td><a href="/admin/students/'+w.student_id+'/knowledge-map">الخريطة</a></td></tr>').join('')}</table></div>`}</script></main></html>'''
@app.get("/admin/progress",response_class=HTMLResponse)
def progress_page(): return PAGE
