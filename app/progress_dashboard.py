from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .security import require_admin
from .teacher_intervention_queue import build_intervention_queue

router = APIRouter()

router = APIRouter()


@router.get("/api/admin/progress", dependencies=[Depends(require_admin)])
def progress_dashboard():
    with connect() as con:
        summary = con.execute(
            """SELECT count(DISTINCT s.id) students,count(DISTINCT a.id) attempts,
              round(avg(100.0*a.score/nullif(a.max_score,0)),1) avg_score
              FROM students s LEFT JOIN attempts a ON a.student_id=s.id"""
        ).fetchone()
        by_subject = list(
            con.execute(
                """SELECT sub.id,sub.name_ar,count(DISTINCT a.id) attempts,
                  round(avg(100.0*a.score/nullif(a.max_score,0)),1) avg_score
                  FROM subjects sub LEFT JOIN questions q ON q.subject_id=sub.id
                  LEFT JOIN attempt_answers aa ON aa.question_id=q.id
                  LEFT JOIN attempts a ON a.id=aa.attempt_id
                  GROUP BY sub.id,sub.name_ar ORDER BY sub.name_ar"""
            ).fetchall()
        )
    interventions = build_intervention_queue(limit=12)
    return {
        "summary": summary,
        "subjects": by_subject,
        "intervention_summary": interventions["summary"],
        "interventions": interventions["items"],
        "intervention_policy": interventions["policy"],
    }


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>متابعة تقدم الطلاب</title><style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--bad:#b42318;--warn:#b54708;--good:#067647}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);margin:0}main{max-width:1150px;margin:auto;padding:18px}.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{border:1px solid var(--line);border-radius:12px;padding:12px}.big{font-size:26px;font-weight:800}.bad{color:var(--bad)}.warn{color:var(--warn)}.good{color:var(--good)}.muted{color:var(--muted);font-size:13px}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}a{color:#175cd3;text-decoration:none}.scroll{overflow:auto}.pill{display:inline-block;padding:5px 8px;border-radius:999px;background:#f2f4f7;font-size:12px}@media(max-width:700px){main{padding:10px}.box{padding:12px;border-radius:13px}table{min-width:850px}.grid{grid-template-columns:1fr 1fr}}@media(max-width:390px){.grid{grid-template-columns:1fr}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/intervention-queue">قائمة تدخل المدرس كاملة</a></div><div id=content></div>
<script>
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
const priorityLabel={high:'عالية',baseline:'يحتاج خط أساس',medium:'متوسطة',low:'منخفضة'};
async function load(){let r=await fetch('/api/admin/progress');if(!r.ok){content.innerHTML='<div class=box>تعذر فتح التقرير</div>';return}let x=await r.json(),s=x.intervention_summary||{};content.innerHTML=`<div class=box><h1>متابعة تقدم الطلاب</h1><div class=grid><div class=card><div class=muted>الطلاب</div><div class=big>${x.summary.students||0}</div></div><div class=card><div class=muted>المحاولات</div><div class=big>${x.summary.attempts||0}</div></div><div class=card><div class=muted>متوسط النتائج</div><div class=big>${x.summary.avg_score??'—'}%</div></div><div class=card><div class=muted>تدخل عاجل</div><div class="big ${s.high?'bad':'good'}">${s.high||0}</div></div><div class=card><div class=muted>يحتاج خط أساس</div><div class="big warn">${s.baseline||0}</div></div></div></div><div class=box><h2>حسب المادة</h2><div class=grid>${x.subjects.map(v=>'<div class=card><b>'+esc(v.name_ar)+'</b><div class=big>'+esc(v.avg_score??'—')+'%</div><div class=muted>'+v.attempts+' محاولة</div></div>').join('')}</div></div><div class="box scroll"><div style="display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap"><div><h2>أولوية التدخل</h2><div class=muted>القائمة تستخدم نفس محرك التدخل الحتمي؛ لا يوجد معيار منفصل أو تصنيف من نموذج ذكاء.</div></div><a href="/admin/intervention-queue">عرض القائمة الكاملة</a></div><table><tr><th>الطالب</th><th>الأولوية</th><th>متوسط حديث</th><th>أيام بدون نشاط</th><th>أسباب</th><th></th></tr>${x.interventions.map(v=>'<tr><td>'+esc(v.student_name)+'</td><td><span class="pill '+(v.priority==='high'?'bad':v.priority==='low'?'good':'warn')+'">'+esc(priorityLabel[v.priority]||v.priority)+' · '+v.score+'/100</span></td><td>'+(v.recent_average==null?'—':esc(v.recent_average)+'%')+'</td><td>'+(v.days_inactive==null?'—':esc(v.days_inactive))+'</td><td>'+v.reasons.map(esc).join('<br>')+'</td><td><a href="/admin/students/'+v.student_id+'/knowledge-map">خريطة المعرفة</a></td></tr>').join('')}</table></div>`}
load();
</script></main></html>'''


@router.get("/admin/progress", response_class=HTMLResponse)
def progress_page():
    return PAGE
