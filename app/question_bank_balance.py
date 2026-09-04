from __future__ import annotations

import os
from fastapi import Depends
from fastapi.responses import HTMLResponse
from .db import connect
from .main import app
from .security import require_admin

MIN_PER_LESSON=max(1,int(os.getenv("BANK_MIN_QUESTIONS_PER_LESSON","5") or 5))
MIN_PER_CONCEPT=max(1,int(os.getenv("BANK_MIN_QUESTIONS_PER_CONCEPT","3") or 3))

def _filters(subject_id,grade_level_id,curriculum_version_id,term_id):
    parts=[];params=[]
    for col,val in (("q.subject_id",subject_id),("q.grade_level_id",grade_level_id),("q.curriculum_version_id",curriculum_version_id),("q.term_id",term_id)):
        if val is not None: parts.append(col+"=%s");params.append(val)
    return (" AND "+" AND ".join(parts) if parts else ""),params

@app.get("/api/admin/question-bank-balance",dependencies=[Depends(require_admin)])
def question_bank_balance(subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None,term_id:int|None=None):
    extra,params=_filters(subject_id,grade_level_id,curriculum_version_id,term_id)
    ready="""q.approved=TRUE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
      AND q.subject_id IS NOT NULL AND q.grade_level_id IS NOT NULL AND q.curriculum_version_id IS NOT NULL
      AND q.term_id IS NOT NULL AND q.unit_id IS NOT NULL AND q.lesson_id IS NOT NULL
      AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
      AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
      AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
      AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)"""
    with connect() as con:
        totals=con.execute("SELECT count(*) total,count(*) FILTER(WHERE "+ready+") ready FROM questions q WHERE 1=1"+extra,params).fetchone()
        difficulty=list(con.execute("""SELECT q.difficulty label,count(*) n FROM questions q
          WHERE """+ready+extra+""" GROUP BY q.difficulty ORDER BY q.difficulty""",params).fetchall())
        qtypes=list(con.execute("""SELECT q.question_type label,count(*) n FROM questions q
          WHERE """+ready+extra+""" GROUP BY q.question_type ORDER BY q.question_type""",params).fetchall())
        lessons=list(con.execute("""SELECT l.id,l.chapter,l.title,u.title unit_title,
          count(q.id) FILTER(WHERE """+ready+""") ready
          FROM lessons l LEFT JOIN units u ON u.id=l.unit_id
          LEFT JOIN questions q ON q.lesson_id=l.id
          WHERE (%s IS NULL OR l.subject_id=%s) AND (%s IS NULL OR l.grade_level_id=%s)
            AND (%s IS NULL OR l.curriculum_version_id=%s) AND (%s IS NULL OR l.term_id=%s)
          GROUP BY l.id,l.chapter,l.title,u.title ORDER BY l.sort_order,l.id""",
          (subject_id,subject_id,grade_level_id,grade_level_id,curriculum_version_id,curriculum_version_id,term_id,term_id)).fetchall())
        concepts=list(con.execute("""SELECT c.id,c.title,l.title lesson_title,
          count(DISTINCT q.id) FILTER(WHERE """+ready+""") ready
          FROM concepts c JOIN lessons l ON l.id=c.lesson_id
          LEFT JOIN question_concepts qc ON qc.concept_id=c.id
          LEFT JOIN questions q ON q.id=qc.question_id
          WHERE (%s IS NULL OR l.subject_id=%s) AND (%s IS NULL OR l.grade_level_id=%s)
            AND (%s IS NULL OR l.curriculum_version_id=%s) AND (%s IS NULL OR l.term_id=%s)
          GROUP BY c.id,c.title,l.title ORDER BY l.sort_order,c.sort_order,c.id""",
          (subject_id,subject_id,grade_level_id,grade_level_id,curriculum_version_id,curriculum_version_id,term_id,term_id)).fetchall())
        skills=list(con.execute("""SELECT s.id,s.name_ar label,count(DISTINCT q.id) FILTER(WHERE """+ready+""") ready
          FROM skills s LEFT JOIN question_skills qs ON qs.skill_id=s.id
          LEFT JOIN questions q ON q.id=qs.question_id
          GROUP BY s.id,s.name_ar,s.sort_order ORDER BY s.sort_order,s.id""").fetchall())
    total_ready=int(totals["ready"] or 0)
    diff={r["label"]:int(r["n"]) for r in difficulty}
    type_map={r["label"]:int(r["n"]) for r in qtypes}
    lesson_rows=[dict(r)|{"gap":max(0,MIN_PER_LESSON-int(r["ready"] or 0))} for r in lessons]
    concept_rows=[dict(r)|{"gap":max(0,MIN_PER_CONCEPT-int(r["ready"] or 0))} for r in concepts]
    return {
      "total":int(totals["total"] or 0),"ready":total_ready,
      "targets":{"lesson":MIN_PER_LESSON,"concept":MIN_PER_CONCEPT},
      "difficulty":diff,"question_types":type_map,
      "lessons":lesson_rows,"concepts":concept_rows,"skills":[dict(r) for r in skills],
      "lesson_gap_total":sum(x["gap"] for x in lesson_rows),
      "concept_gap_total":sum(x["gap"] for x in concept_rows),
    }

PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name=viewport content="width=device-width,initial-scale=1"><title>توازن بنك الأسئلة</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1250px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:15px;margin:10px 0;box-shadow:0 3px 14px #0001}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{border:1px solid #e7eaf0;border-radius:12px;padding:12px}.n{font-size:27px;font-weight:800}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.muted{color:#667085}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}select,button{padding:9px;border:1px solid #ccd2dd;border-radius:9px}@media(max-width:760px){table{display:block;overflow-x:auto;white-space:nowrap}}
</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/question-bank-quality">جودة بنك الأسئلة</a> · <a href="/admin/quiz-builder">منشئ الاختبارات</a></div>
<div class=box><h1>توازن بنك الأسئلة</h1><div class=cards><select id=s><option value="">كل المواد</option></select><select id=g><option value="">كل الصفوف</option></select><select id=cv><option value="">كل المناهج</option></select><select id=t><option value="">كل الترمات</option></select><button onclick=load()>تطبيق</button></div><div id=summary class=cards style="margin-top:12px"></div></div>
<div class=box><h2>توزيع الصعوبة والنوع</h2><div id=dist class=cards></div></div>
<div class=box><h2>تغطية الدروس</h2><div id=lessons></div></div>
<div class=box><h2>تغطية المفاهيم</h2><div id=concepts></div></div>
<div class=box><h2>تغطية المهارات</h2><div id=skills></div></div>
<script>
let cat=null;function e(x){return String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function setup(){cat=await fetch('/api/academic/catalog').then(r=>r.json());s.innerHTML='<option value="">كل المواد</option>'+cat.subjects.map(x=>'<option value="'+x.id+'">'+e(x.name_ar)+'</option>').join('');g.innerHTML='<option value="">كل الصفوف</option>'+cat.grades.map(x=>'<option value="'+x.id+'">'+e(x.name_ar)+'</option>').join('');s.onchange=fill;g.onchange=fill;cv.onchange=fillTerms;fill();await load()}
function fill(){let sid=+s.value||0,gid=+g.value||0,a=cat.curricula.filter(x=>(!sid||x.subject_id==sid)&&(!gid||x.grade_level_id==gid));cv.innerHTML='<option value="">كل المناهج</option>'+a.map(x=>'<option value="'+x.id+'">'+e(x.subject_name)+' — '+e(x.grade_name)+' — '+e(x.academic_year)+'</option>').join('');fillTerms()}
function fillTerms(){let id=+cv.value||0,a=id?cat.terms.filter(x=>x.curriculum_version_id==id):[];t.innerHTML='<option value="">كل الترمات</option>'+a.map(x=>'<option value="'+x.id+'">'+e(x.name_ar)+'</option>').join('')}
function qs(){let p=new URLSearchParams();if(s.value)p.set('subject_id',s.value);if(g.value)p.set('grade_level_id',g.value);if(cv.value)p.set('curriculum_version_id',cv.value);if(t.value)p.set('term_id',t.value);return p}
async function load(){let r=await fetch('/api/admin/question-bank-balance?'+qs());if(r.status===401){location.href='/admin/login';return}let x=await r.json();summary.innerHTML=[['الأسئلة الجاهزة',x.ready],['نقص تغطية الدروس',x.lesson_gap_total],['نقص تغطية المفاهيم',x.concept_gap_total],['هدف كل درس',x.targets.lesson],['هدف كل مفهوم',x.targets.concept]].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class=n>'+v[1]+'</div></div>').join('');let ds={easy:'سهل',medium:'متوسط',hard:'صعب'},ts={mcq:'اختيار من متعدد',numeric:'مسألة حسابية',essay:'مقالي'};dist.innerHTML=Object.entries(x.difficulty).map(v=>'<div class=card><b>'+e(ds[v[0]]||v[0])+'</b><div class=n>'+v[1]+'</div></div>').join('')+Object.entries(x.question_types).map(v=>'<div class=card><b>'+e(ts[v[0]]||v[0])+'</b><div class=n>'+v[1]+'</div></div>').join('');lessons.innerHTML='<table><tr><th>الوحدة</th><th>الدرس</th><th>جاهز</th><th>النقص</th></tr>'+x.lessons.map(r=>'<tr><td>'+e(r.unit_title||'—')+'</td><td>'+e((r.chapter||'')+' — '+r.title)+'</td><td>'+r.ready+'</td><td class="'+(r.gap?'bad':'ok')+'">'+r.gap+'</td></tr>').join('')+'</table>';concepts.innerHTML='<table><tr><th>الدرس</th><th>المفهوم</th><th>جاهز</th><th>النقص</th></tr>'+x.concepts.map(r=>'<tr><td>'+e(r.lesson_title)+'</td><td>'+e(r.title)+'</td><td>'+r.ready+'</td><td class="'+(r.gap?'bad':'ok')+'">'+r.gap+'</td></tr>').join('')+'</table>';skills.innerHTML='<table><tr><th>المهارة</th><th>عدد الأسئلة الجاهزة</th></tr>'+x.skills.map(r=>'<tr><td>'+e(r.label)+'</td><td>'+r.ready+'</td></tr>').join('')+'</table>'}
setup()
</script></main></html>'''

@app.get("/admin/question-bank-balance",response_class=HTMLResponse)
def question_bank_balance_page(): return PAGE
