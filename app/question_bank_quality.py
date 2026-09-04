from __future__ import annotations
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from .db import connect
from .main import app
from .security import require_admin

BASE="""WITH qc AS (
 SELECT q.id,q.subject_id,q.grade_level_id,q.curriculum_version_id,
  s.name_ar subject_name,g.name_ar grade_name,cv.academic_year,
  (q.document_id IS NOT NULL AND COALESCE(q.source_page,q.page) IS NOT NULL) source_ok,
  EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) asset_ok,
  (q.subject_id IS NOT NULL AND q.grade_level_id IS NOT NULL AND q.curriculum_version_id IS NOT NULL AND q.term_id IS NOT NULL AND q.unit_id IS NOT NULL AND q.lesson_id IS NOT NULL
   AND EXISTS(SELECT 1 FROM lessons l WHERE l.id=q.lesson_id AND l.subject_id=q.subject_id AND l.grade_level_id=q.grade_level_id AND l.curriculum_version_id=q.curriculum_version_id AND l.term_id=q.term_id AND l.unit_id=q.unit_id)) academic_ok,
  (EXISTS(SELECT 1 FROM question_concepts x WHERE x.question_id=q.id) AND NOT EXISTS(SELECT 1 FROM question_concepts x JOIN concepts c ON c.id=x.concept_id WHERE x.question_id=q.id AND c.lesson_id IS DISTINCT FROM q.lesson_id)) concept_ok,
  EXISTS(SELECT 1 FROM question_skills x WHERE x.question_id=q.id) skill_ok,
  COALESCE(q.question_type,'unknown')<>'unknown' type_ok,
  COALESCE(q.difficulty,'unclassified')<>'unclassified' difficulty_ok,
  COALESCE(btrim(q.accepted_answer),'')<>'' answer_ok,
  (q.answer_document_id IS NULL OR q.answer_page IS NOT NULL) answer_source_ok
 FROM questions q LEFT JOIN subjects s ON s.id=q.subject_id LEFT JOIN grade_levels g ON g.id=q.grade_level_id LEFT JOIN curriculum_versions cv ON cv.id=q.curriculum_version_id
)"""

ISSUE_SQL={
 "missing_source":"NOT source_ok","missing_asset":"NOT asset_ok","missing_academic":"NOT academic_ok",
 "missing_concept":"NOT concept_ok","missing_skill":"NOT skill_ok","missing_type":"NOT type_ok",
 "missing_difficulty":"NOT difficulty_ok","missing_answer":"NOT answer_ok","missing_answer_source":"NOT answer_source_ok",
 "any":"NOT (source_ok AND asset_ok AND academic_ok AND concept_ok AND skill_ok AND type_ok AND difficulty_ok AND answer_ok AND answer_source_ok)"
}

@app.get("/api/admin/question-bank-quality/items",dependencies=[Depends(require_admin)])
def bank_quality_items(reason:str="any",subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None,limit:int=250):
    if reason not in ISSUE_SQL: raise HTTPException(400,"Invalid quality reason")
    where=[ISSUE_SQL[reason]];params=[]
    if subject_id is not None: where.append("subject_id=%s");params.append(subject_id)
    if grade_level_id is not None: where.append("grade_level_id=%s");params.append(grade_level_id)
    if curriculum_version_id is not None: where.append("curriculum_version_id=%s");params.append(curriculum_version_id)
    sql=BASE+" SELECT id FROM qc WHERE "+" AND ".join(where)+" ORDER BY id DESC LIMIT %s";params.append(min(max(limit,1),1000))
    with connect() as con:
        ids=[r["id"] for r in con.execute(sql,params).fetchall()]
        if not ids:return {"reason":reason,"count":0,"items":[]}
        rows=list(con.execute("""SELECT q.id,q.document_id,COALESCE(q.source_page,q.page) source_page,q.text_verbatim,
          q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id,q.unit_id,q.lesson_id
          FROM questions q WHERE q.id=ANY(%s) ORDER BY q.id DESC""",(ids,)).fetchall())
    return {"reason":reason,"count":len(rows),"items":rows}

@app.get("/api/admin/question-bank-quality",dependencies=[Depends(require_admin)])
def bank_quality(subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None):
    filters=[];params=[]
    if subject_id is not None: filters.append("subject_id=%s");params.append(subject_id)
    if grade_level_id is not None: filters.append("grade_level_id=%s");params.append(grade_level_id)
    if curriculum_version_id is not None: filters.append("curriculum_version_id=%s");params.append(curriculum_version_id)
    where=(" WHERE "+" AND ".join(filters)) if filters else ""
    with connect() as con:
        rows=list(con.execute(BASE+""" SELECT subject_id,grade_level_id,curriculum_version_id,subject_name,grade_name,academic_year,
          count(*) total,
          count(*) FILTER(WHERE source_ok AND asset_ok AND academic_ok AND concept_ok AND skill_ok AND type_ok AND difficulty_ok AND answer_ok AND answer_source_ok) ready,
          count(*) FILTER(WHERE NOT source_ok) missing_source,count(*) FILTER(WHERE NOT asset_ok) missing_asset,
          count(*) FILTER(WHERE NOT academic_ok) missing_academic,count(*) FILTER(WHERE NOT concept_ok) missing_concept,
          count(*) FILTER(WHERE NOT skill_ok) missing_skill,count(*) FILTER(WHERE NOT type_ok) missing_type,
          count(*) FILTER(WHERE NOT difficulty_ok) missing_difficulty,count(*) FILTER(WHERE NOT answer_ok) missing_answer,
          count(*) FILTER(WHERE NOT answer_source_ok) missing_answer_source
          FROM qc """+where+""" GROUP BY 1,2,3,4,5,6 ORDER BY 4 NULLS LAST,5 NULLS LAST,6 NULLS LAST""",params).fetchall())
    total=sum(int(r["total"]) for r in rows);ready=sum(int(r["ready"]) for r in rows)
    reasons={k:sum(int(r[k]) for r in rows) for k in ("missing_source","missing_asset","missing_academic","missing_concept","missing_skill","missing_type","missing_difficulty","missing_answer","missing_answer_source")}
    return {"total":total,"ready":ready,"incomplete":total-ready,"ready_pct":round(ready*100/total,1) if total else 0,"reasons":reasons,"groups":rows}

PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name=viewport content="width=device-width,initial-scale=1"><title>جودة بنك الأسئلة</title><style>body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:15px;margin:10px 0;box-shadow:0 3px 14px #0001}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{border:1px solid #e7eaf0;border-radius:12px;padding:12px}.n{font-size:28px;font-weight:800}.ok{color:#067647}.bad{color:#b42318}.muted{color:#667085}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}@media(max-width:760px){table{display:block;overflow-x:auto;white-space:nowrap}}</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/workflow">مراجعة الأسئلة</a></div><div class=box><h1>جودة بنك الأسئلة</h1><div class=cards><select id=subjectFilter><option value="">كل المواد</option></select><select id=gradeFilter><option value="">كل الصفوف</option></select><select id=curriculumFilter><option value="">كل المناهج</option></select><button onclick="applyFilters()">تطبيق</button></div><div id=cards class=cards></div></div><div class=box><h2>أكثر أسباب عدم الجاهزية</h2><div id=reasons></div></div><div class=box><h2>حسب المادة والصف والمنهج</h2><div id=groups></div></div><script>
let catalog=null;const labels={missing_source:'المصدر/الصفحة',missing_asset:'القصاصة',missing_academic:'التصنيف الأكاديمي',missing_concept:'المفهوم',missing_skill:'المهارة',missing_type:'نوع السؤال',missing_difficulty:'الصعوبة',missing_answer:'الإجابة',missing_answer_source:'مصدر الإجابة'};
async function setup(){catalog=await fetch('/api/academic/catalog').then(r=>r.json());subjectFilter.innerHTML='<option value="">كل المواد</option>'+catalog.subjects.map(x=>'<option value="'+x.id+'">'+x.name_ar+'</option>').join('');gradeFilter.innerHTML='<option value="">كل الصفوف</option>'+catalog.grades.map(x=>'<option value="'+x.id+'">'+x.name_ar+'</option>').join('');subjectFilter.onchange=fillCurricula;gradeFilter.onchange=fillCurricula;fillCurricula();await load()}function fillCurricula(){let s=+subjectFilter.value||0,g=+gradeFilter.value||0;let a=catalog.curricula.filter(x=>(!s||x.subject_id==s)&&(!g||x.grade_level_id==g));curriculumFilter.innerHTML='<option value="">كل المناهج</option>'+a.map(x=>'<option value="'+x.id+'">'+x.subject_name+' — '+x.grade_name+' — '+x.academic_year+'</option>').join('')}function params(){let p=new URLSearchParams();if(subjectFilter.value)p.set('subject_id',subjectFilter.value);if(gradeFilter.value)p.set('grade_level_id',gradeFilter.value);if(curriculumFilter.value)p.set('curriculum_version_id',curriculumFilter.value);return p}function applyFilters(){load()}async function load(){let p=params();let r=await fetch('/api/admin/question-bank-quality?'+p.toString());if(r.status===401){location.href='/admin/login';return}let x=await r.json();cards.innerHTML=[['إجمالي الأسئلة',x.total],['جاهزة',x.ready],['تحتاج استكمال',x.incomplete],['نسبة الجاهزية',x.ready_pct+'%']].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class=n>'+v[1]+'</div></div>').join('');let rs=Object.entries(x.reasons).sort((a,b)=>b[1]-a[1]);reasons.innerHTML=rs.map(v=>'<div class=card style="margin:6px 0"><b>'+labels[v[0]]+'</b>: '+v[1]+' · <a href="/admin/workflow?quality_issue='+encodeURIComponent(v[0])+'">معالجة هذه الأسئلة</a></div>').join('');groups.innerHTML='<table><tr><th>المادة</th><th>الصف</th><th>المنهج</th><th>الإجمالي</th><th>جاهز</th><th>ناقص</th><th>الجودة</th></tr>'+x.groups.map(g=>{let p=g.total?Math.round(g.ready*100/g.total):0;let u='/admin/workflow?quality_issue=any'+(g.subject_id?'&subject_id='+g.subject_id:'')+(g.grade_level_id?'&grade_level_id='+g.grade_level_id:'')+(g.curriculum_version_id?'&curriculum_version_id='+g.curriculum_version_id:'');return '<tr><td>'+(g.subject_name||'غير مصنف')+'</td><td>'+(g.grade_name||'—')+'</td><td>'+(g.academic_year||'—')+'</td><td>'+g.total+'</td><td class=ok>'+g.ready+'</td><td class=bad>'+(g.total-g.ready)+'</td><td>'+p+'% · <a href="'+u+'">معالجة الناقص</a></td></tr>'}).join('')+'</table>'}setup()
</script></main></html>'''

@app.get("/admin/question-bank-quality",response_class=HTMLResponse)
def quality_page(): return PAGE
