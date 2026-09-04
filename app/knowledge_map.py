from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

@app.get("/api/admin/students/{student_id}/knowledge-map",dependencies=[Depends(require_admin)])
def knowledge_map(student_id:int):
    with connect() as con:
        student=con.execute("SELECT id,name,external_code FROM students WHERE id=%s",(student_id,)).fetchone()
        if not student: raise HTTPException(404,"Student not found")
        concepts=list(con.execute("""SELECT c.id,c.title,l.title lesson_title,u.title unit_title,s.name_ar subject_name,
          count(aa.id) attempts,
          count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
          FROM concepts c
          JOIN lessons l ON l.id=c.lesson_id
          LEFT JOIN units u ON u.id=l.unit_id
          LEFT JOIN subjects s ON s.id=l.subject_id
          JOIN question_concepts qc ON qc.concept_id=c.id
          JOIN attempt_answers aa ON aa.question_id=qc.question_id
          JOIN attempts a ON a.id=aa.attempt_id
          WHERE a.student_id=%s
          GROUP BY c.id,c.title,l.title,u.title,s.name_ar
          ORDER BY s.name_ar,u.title,l.title,c.title""",(student_id,)).fetchall())
        skills=list(con.execute("""SELECT s.id,s.name_ar,
          count(aa.id) attempts,
          count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
          FROM skills s
          JOIN question_skills qs ON qs.skill_id=s.id
          JOIN attempt_answers aa ON aa.question_id=qs.question_id
          JOIN attempts a ON a.id=aa.attempt_id
          WHERE a.student_id=%s
          GROUP BY s.id,s.name_ar ORDER BY mastery ASC NULLS LAST,s.sort_order,s.id""",(student_id,)).fetchall())
        lessons=list(con.execute("""SELECT l.id,l.title,u.title unit_title,s.name_ar subject_name,
          count(aa.id) attempts,
          count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
          FROM lessons l
          LEFT JOIN units u ON u.id=l.unit_id
          LEFT JOIN subjects s ON s.id=l.subject_id
          JOIN questions q ON q.lesson_id=l.id
          JOIN attempt_answers aa ON aa.question_id=q.id
          JOIN attempts a ON a.id=aa.attempt_id
          WHERE a.student_id=%s
          GROUP BY l.id,l.title,u.title,s.name_ar
          ORDER BY mastery ASC NULLS LAST,l.title""",(student_id,)).fetchall())
        recommendations=[]
        for x in concepts:
            if x["attempts"]>=2 and x["mastery"] is not None and float(x["mastery"])<60:
                recommendations.append({"type":"concept","id":x["id"],"title":x["title"],"mastery":x["mastery"],"action":"مراجعة المفهوم ثم حل تدريب قصير"})
        for x in skills:
            if x["attempts"]>=3 and x["mastery"] is not None and float(x["mastery"])<60:
                recommendations.append({"type":"skill","id":x["id"],"title":x["name_ar"],"mastery":x["mastery"],"action":"تدريب مركز على المهارة"})
        recommendations=sorted(recommendations,key=lambda x:float(x["mastery"]))[:8]
        return {"student":student,"concepts":concepts,"skills":skills,"lessons":lessons,"recommendations":recommendations}

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>خريطة معرفة الطالب</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:#fff;padding:16px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.bar{height:10px;background:#e7ecf3;border-radius:99px;overflow:hidden}.fill{height:100%;background:currentColor}.row{display:grid;grid-template-columns:1fr 110px;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid #eee}.low{color:#b42318}.mid{color:#b54708}.high{color:#067647}.muted{color:#667085;font-size:13px}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}</style><main>
<div class=box><input id=key type=password placeholder=ADMIN_API_KEY><button onclick=load()>فتح الخريطة</button> <a href="/admin/dashboard">لوحة التحكم</a></div><div id=content></div>
<script>key.value='';const id=Number(location.pathname.split('/').pop());const H=()=>({'X-Admin-Key':''});function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}function cls(v){return Number(v)<50?'low':Number(v)<75?'mid':'high'}async function load(){let r=await fetch('/api/admin/students/'+id+'/knowledge-map',{headers:H()});if(!r.ok){content.innerHTML='<div class=box>تعذر فتح الخريطة.</div>';return}let x=await r.json();content.innerHTML=`<div class=box><h1>${esc(x.student.name)}</h1><div class=muted>خريطة المعرفة مبنية فقط على نتائج الأسئلة المعتمدة المرتبطة بالمفاهيم.</div></div><div class=box><h2>المفاهيم</h2>${x.concepts.length?x.concepts.map(c=>`<div class="row ${cls(c.mastery)}"><div><b>${esc(c.title)}</b><div class=muted>${esc(c.subject_name||'')} · ${esc(c.unit_title||'')} · ${esc(c.lesson_title||'')} · ${c.attempts} إجابة</div><div class=bar><div class=fill style="width:${c.mastery||0}%"></div></div></div><b>${c.mastery||0}%</b></div>`).join(''):'لا توجد بيانات مفاهيم بعد'}</div><div class=box><h2>المهارات</h2>${x.skills.length?x.skills.map(c=>`<div class="row ${cls(c.mastery)}"><div><b>${esc(c.name_ar)}</b><div class=muted>${c.attempts} إجابة</div><div class=bar><div class=fill style="width:${c.mastery||0}%"></div></div></div><b>${c.mastery||0}%</b></div>`).join(''):'لا توجد بيانات مهارات بعد'}</div><div class=box><h2>خطة المراجعة التكيفية</h2>${x.recommendations.length?x.recommendations.map(r=>`<div class="row ${cls(r.mastery)}"><div><b>${esc(r.title)}</b><div class=muted>${esc(r.action)}</div></div><b>${r.mastery}%</b></div>`).join(''):'لا توجد نقاط ضعف مؤكدة كافية بعد'}</div><div class=box><h2>الدروس</h2>${x.lessons.map(c=>`<div class="row ${cls(c.mastery)}"><div><b>${esc(c.lesson_title)}</b><div class=muted>${esc(c.subject_name||'')} · ${esc(c.unit_title||'')} · ${c.attempts} إجابة</div><div class=bar><div class=fill style="width:${c.mastery||0}%"></div></div></div><b>${c.mastery||0}%</b></div>`).join('')}</div>`}</script></main></html>'''
@app.get("/admin/students/{student_id}/knowledge-map",response_class=HTMLResponse)
def knowledge_map_page(student_id:int): return PAGE
