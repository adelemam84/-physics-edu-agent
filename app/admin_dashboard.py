from __future__ import annotations
from fastapi import Depends
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

@app.get("/api/admin/dashboard",dependencies=[Depends(require_admin)])
def admin_dashboard_data():
    with connect() as con:
        summary=con.execute("""SELECT
          (SELECT count(*) FROM students) students,
          (SELECT count(*) FROM guardians WHERE active=TRUE) guardians,
          (SELECT count(*) FROM quizzes) quizzes,
          (SELECT count(*) FROM quizzes WHERE published=TRUE) published_quizzes,
          (SELECT count(*) FROM attempts) attempts,
          (SELECT count(*) FROM questions WHERE approved=TRUE) approved_questions,
          (SELECT count(*) FROM parent_notifications WHERE status='queued') queued_notifications,
          (SELECT count(*) FROM parent_notifications WHERE status='failed') failed_notifications,
          (SELECT round(avg(CASE WHEN max_score>0 THEN (score/max_score)*100 END),1) FROM attempts) avg_score
        """).fetchone()
        recent=list(con.execute("""SELECT a.id,s.name student_name,q.title quiz_title,a.score,a.max_score,
          round(CASE WHEN a.max_score>0 THEN (a.score/a.max_score)*100 ELSE 0 END,1) percentage,
          coalesce(a.completed_at,a.submitted_at) completed_at
          FROM attempts a JOIN students s ON s.id=a.student_id LEFT JOIN quizzes q ON q.id=a.quiz_id
          ORDER BY coalesce(a.completed_at,a.submitted_at) DESC LIMIT 15""").fetchall())
        weak=list(con.execute("""SELECT s.id,s.name,
          count(a.id) attempts,
          round(avg(CASE WHEN a.max_score>0 THEN (a.score/a.max_score)*100 END),1) average_percentage,
          (SELECT a2.id FROM attempts a2 WHERE a2.student_id=s.id ORDER BY coalesce(a2.completed_at,a2.submitted_at) DESC LIMIT 1) latest_attempt_id
          FROM students s JOIN attempts a ON a.student_id=s.id
          GROUP BY s.id,s.name HAVING avg(CASE WHEN a.max_score>0 THEN (a.score/a.max_score)*100 END)<60
          ORDER BY average_percentage ASC NULLS LAST LIMIT 10""").fetchall())
        notifications=list(con.execute("""SELECT status,count(*) total FROM parent_notifications GROUP BY status ORDER BY status""").fetchall())
        return {"summary":summary,"recent_attempts":recent,"students_need_attention":weak,"notification_status":notifications}

PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>لوحة تحكم منصة العلوم التعليمية</title><style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e6eaf0}*{box-sizing:border-box}body{font-family:system-ui;background:var(--bg);color:var(--text);margin:0}.layout{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{background:#111827;color:white;padding:20px;position:sticky;top:0;height:100vh}.side h2{margin-top:0}.side a{display:block;color:#dbe5ff;text-decoration:none;padding:10px;border-radius:9px;margin:4px 0}.side a:hover{background:#ffffff14}.main{padding:22px;min-width:0}.top{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.box{background:var(--card);padding:15px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0000000a}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{background:#f8fafc;border:1px solid var(--line);border-radius:13px;padding:13px}.card h2{margin:5px 0 0;font-size:28px}.grid{display:grid;grid-template-columns:1.4fr .8fr;gap:12px}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid var(--line);text-align:right;font-size:14px}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}.muted{color:var(--muted);font-size:13px}.warn{color:#b54708}.bad{color:#b42318}.ok{color:#067647}@media(max-width:850px){.layout{grid-template-columns:1fr}.side{height:auto;position:static}.grid{grid-template-columns:1fr}}
</style><div class=layout><aside class=side><h2>منصة العلوم التعليمية</h2><a href="/admin/dashboard">الرئيسية</a><a href="/admin/workflow">مراجعة الأسئلة</a><a href="/admin/academic">الهيكل الأكاديمي</a><a href="/admin/bank">بنك الأسئلة</a><a href="/admin/quiz-builder">إنشاء اختبار</a><a href="/admin/quizzes">إدارة الاختبارات</a><a href="/admin/students">الطلاب والاختبارات</a><a href="/admin/parents">أولياء الأمور وواتساب</a><a href="/admin/whatsapp-monitor">مراقبة واتساب</a><a href="/admin/progress">متابعة التقدم</a><a href="/admin/readiness">جاهزية النظام</a><a href="/admin/diagnostics">تشخيص سلامة البيانات</a><a href="/admin/alerts">مركز التنبيهات</a><a href="/admin/document-recovery">استعادة ملفات PDF القديمة</a><a href="/student">بوابة الطالب</a><a href="/practice">معاينة الطالب</a></aside><main class=main>
<div class="box top"><span id=msg class=muted>جارٍ التحقق من جلسة الإدارة...</span><button onclick=logout()>تسجيل الخروج</button></div>
<h1>لوحة التحكم</h1><div id=alertSummary class=box></div><div id=cards class=cards></div>
<div class=grid><div class=box><h2>آخر نتائج الطلاب</h2><div id=recent></div></div><div class=box><h2>طلاب يحتاجون متابعة</h2><div id=weak></div></div></div>
<div class=box><h2>حالة رسائل أولياء الأمور</h2><div id=notif></div></div>
<script>
const H=()=>({});async function logout(){await fetch('/api/admin/logout',{method:'POST'});location.href='/admin/login'}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){let s=await fetch('/api/admin/session').then(r=>r.json());if(!s.authenticated){location.href='/admin/login';return}msg.textContent='جلسة الإدارة آمنة ومفعلة';let r=await fetch('/api/admin/dashboard',{headers:H()});if(!r.ok){location.href='/admin/login';return}let x=await r.json(),s=x.summary||{};let ar=await fetch('/api/admin/alert-center/summary').then(r=>r.json()).catch(()=>null);alertSummary.innerHTML=ar?(ar.total?'<b class="'+(ar.error_count?'bad':'warn')+'">⚠️ '+(ar.error_count+ar.warning_count)+' تنبيه يحتاج مراجعة</b> · <a href="/admin/alerts">فتح مركز التنبيهات</a>':'<span class=ok>✅ لا توجد تنبيهات تشغيلية حالية</span>'):'<span class=muted>تعذر تحميل مركز التنبيهات</span>';cards.innerHTML=[['الطلاب',s.students||0],['أولياء الأمور',s.guardians||0],['الاختبارات',s.quizzes||0],['الاختبارات المنشورة',s.published_quizzes||0],['المحاولات',s.attempts||0],['الأسئلة المعتمدة',s.approved_questions||0],['متوسط النتائج',(s.avg_score??0)+'%'],['رسائل في الانتظار',s.queued_notifications||0],['رسائل فاشلة',s.failed_notifications||0]].map(([a,b])=>`<div class=card><div class=muted>${a}</div><h2>${b}</h2></div>`).join('');
recent.innerHTML=x.recent_attempts.length?'<table><tr><th>الطالب</th><th>الاختبار</th><th>النتيجة</th><th></th></tr>'+x.recent_attempts.map(a=>`<tr><td>${esc(a.student_name)}</td><td>${esc(a.quiz_title||'—')}</td><td class=${Number(a.percentage)<50?'bad':Number(a.percentage)<70?'warn':'ok'}>${a.percentage}%</td><td><a href="/admin/results/${a.id}">التقرير</a></td></tr>`).join('')+'</table>':'لا توجد نتائج حتى الآن';
weak.innerHTML=x.students_need_attention.length?x.students_need_attention.map(a=>`<div style="padding:8px;border-bottom:1px solid #eee"><b>${esc(a.name)}</b><br><span class=bad>متوسط ${a.average_percentage}%</span> · ${a.attempts} اختبار ${a.latest_attempt_id?'<br><a href="/admin/results/'+a.latest_attempt_id+'">فتح آخر تقرير</a>':''}</div>`).join(''):'لا يوجد طلاب تحت حد المتابعة حاليًا';
notif.innerHTML=x.notification_status.length?x.notification_status.map(n=>`<span style="display:inline-block;padding:8px 12px;margin:4px;border:1px solid #ddd;border-radius:999px">${esc(n.status)}: <b>${n.total}</b></span>`).join(''):'لا توجد رسائل بعد'}load();
</script></main></div></html>'''
@app.get("/admin/dashboard",response_class=HTMLResponse)
def admin_dashboard_page(): return PAGE
