from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

VALID={"draft","quality_review","ready","published","archived"}

@app.get("/api/admin/quizzes/lifecycle",dependencies=[Depends(require_admin)])
def lifecycle(status:str|None=None,limit:int=250):
    if status and status not in VALID: raise HTTPException(400,"Invalid lifecycle status")
    with connect() as con:
        rows=list(con.execute("""SELECT q.id,q.title,q.lifecycle_status,q.quality_score,q.published,q.created_at,
          q.ready_at,q.published_at,q.archived_at,s.name_ar subject_name,g.name_ar grade_name,
          count(qq.question_id) question_count
          FROM quizzes q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN grade_levels g ON g.id=q.grade_level_id
          LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id
          WHERE (%s IS NULL OR q.lifecycle_status=%s)
          GROUP BY q.id,s.name_ar,g.name_ar ORDER BY q.created_at DESC LIMIT %s""",(status,status,min(max(limit,1),1000))).fetchall())
        counts=list(con.execute("""SELECT lifecycle_status,count(*) n FROM quizzes GROUP BY lifecycle_status""").fetchall())
    return {"counts":{r["lifecycle_status"]:int(r["n"]) for r in counts},"items":rows}

PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name=viewport content="width=device-width,initial-scale=1"><title>دورة حياة الاختبارات</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1250px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:15px;margin:10px 0;box-shadow:0 3px 14px #0001}.tabs{display:flex;gap:7px;flex-wrap:wrap}.tabs button,button{padding:9px 12px;border:1px solid #ccd2dd;border-radius:9px;background:#fff}.tabs .on{font-weight:800;border-color:#667085}.card{border:1px solid #e6eaf0;border-radius:13px;padding:12px;margin:8px 0}.row{display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap}.muted{color:#667085;font-size:13px}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.audit{padding:7px;border-bottom:1px solid #eee}@media(max-width:700px){.row{align-items:flex-start}}
</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/quiz-builder">إنشاء اختبار</a></div><div class=box><h1>دورة حياة الاختبارات</h1><div id=tabs class=tabs></div></div><div id=list class=box></div><div id=audit class=box style="display:none"></div><script>
const labels={draft:'مسودة',quality_review:'مراجعة الجودة',ready:'جاهز',published:'منشور',archived:'مؤرشف'};let current='';
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(st=current){current=st;let r=await fetch('/api/admin/quizzes/lifecycle'+(st?'?status='+st:''));if(r.status===401){location.href='/admin/login';return}let x=await r.json();tabs.innerHTML='<button class="'+(!st?'on':'')+'" onclick="load(\'\')">الكل</button>'+Object.keys(labels).map(k=>'<button class="'+(st===k?'on':'')+'" onclick="load(\''+k+'\')">'+labels[k]+' ('+(x.counts[k]||0)+')</button>').join('');list.innerHTML=x.items.length?x.items.map(q=>'<div class=card><div class=row><div><b>#'+q.id+' '+e(q.title)+'</b><div class=muted>'+e(q.subject_name||'—')+' · '+e(q.grade_name||'—')+' · '+q.question_count+' سؤال · الجودة '+(q.quality_score??'—')+'%</div><div><b>'+e(labels[q.lifecycle_status]||q.lifecycle_status)+'</b></div></div><div>'+actions(q)+'</div></div></div>').join(''):'لا توجد اختبارات في هذه الحالة'}
function actions(q){let a='<button onclick="showAudit('+q.id+')">السجل</button> <a href="/admin/quiz-builder">فتح المنشئ</a> ';if(q.lifecycle_status==='draft'||q.lifecycle_status==='quality_review')a+='<button onclick="act('+q.id+',\'review\')">فحص الجودة</button> ';if(q.lifecycle_status==='ready')a+='<button onclick="act('+q.id+',\'publish\')">نشر</button> ';if(q.lifecycle_status==='published')a+='<button onclick="act('+q.id+',\'unpublish\')">إلغاء النشر</button> ';if(q.lifecycle_status!=='archived')a+='<button onclick="act('+q.id+',\'archive\')">أرشفة</button>';return a}
async function act(id,a){let r=await fetch('/api/quizzes/'+id+'/'+a,{method:'POST'}),x=await r.json();if(!r.ok){alert((x.detail&&x.detail.message)||x.detail||'تعذر تنفيذ العملية');return}await load(current);await showAudit(id)}
async function showAudit(id){let r=await fetch('/api/quizzes/'+id+'/audit'),x=await r.json();audit.style.display='block';audit.innerHTML='<h2>سجل الاختبار #'+id+'</h2>'+(x.length?x.map(v=>'<div class=audit><b>'+e(v.action)+'</b> · '+e(labels[v.from_status]||v.from_status||'—')+' ← '+e(labels[v.to_status]||v.to_status||'—')+(v.quality_score!=null?' · الجودة '+v.quality_score+'%':'')+'<div class=muted>'+e(v.created_at)+'</div></div>').join(''):'لا يوجد سجل بعد');audit.scrollIntoView({behavior:'smooth'})}
load()
</script></main></html>'''

@app.get("/admin/quizzes",response_class=HTMLResponse)
def lifecycle_page(): return PAGE
