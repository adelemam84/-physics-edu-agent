from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .db import connect
from .main import app
from .security import require_admin

ROLES={"front_matter","question_candidate","index_or_divider","answer_solution","unknown"}
STATUSES={"pending","classified","reviewing","done","skipped"}

class PageReviewPatch(BaseModel):
    page_role:str|None=None
    review_status:str|None=None
    notes:str|None=None
    question_count:int|None=None

@app.get("/api/admin/source-review",dependencies=[Depends(require_admin)])
def source_review(document_id:int|None=None,review_status:str|None=None):
    sql="""SELECT r.*,d.filename,d.storage_url,d.status document_status,cv.academic_year,
      (SELECT count(*) FROM questions q WHERE q.document_id=r.document_id AND coalesce(q.source_page,q.page)=r.page_number) extracted_questions
      FROM document_page_reviews r JOIN documents d ON d.id=r.document_id
      LEFT JOIN curriculum_versions cv ON cv.id=d.curriculum_version_id WHERE 1=1"""
    params=[]
    if document_id is not None:
        sql+=" AND r.document_id=%s";params.append(document_id)
    if review_status is not None:
        sql+=" AND r.review_status=%s";params.append(review_status)
    sql+=" ORDER BY r.document_id,r.page_number"
    with connect() as con:
        return list(con.execute(sql,params).fetchall())

@app.get("/api/admin/source-review/summary",dependencies=[Depends(require_admin)])
def source_review_summary(document_id:int|None=None):
    where=" WHERE 1=1";params=[]
    if document_id is not None:
        where+=" AND r.document_id=%s";params.append(document_id)
    with connect() as con:
        totals=con.execute("""SELECT count(*) total,
          count(*) FILTER(WHERE review_status='pending') pending,
          count(*) FILTER(WHERE review_status='done') done,
          count(*) FILTER(WHERE page_role='question_candidate') question_candidate,
          count(*) FILTER(WHERE page_role='answer_solution') answer_solution
          FROM document_page_reviews r"""+where,params).fetchone()
        docs=list(con.execute("""SELECT d.id,d.filename,d.status,cv.academic_year,
          count(r.page_number) pages,
          count(*) FILTER(WHERE r.review_status='pending') pending_pages,
          count(*) FILTER(WHERE r.page_role='question_candidate') question_pages
          FROM documents d JOIN document_page_reviews r ON r.document_id=d.id
          LEFT JOIN curriculum_versions cv ON cv.id=d.curriculum_version_id
          GROUP BY d.id,d.filename,d.status,cv.academic_year ORDER BY d.id DESC""").fetchall())
        return {**totals,"documents":docs}

@app.patch("/api/admin/source-review/{document_id}/{page_number}",dependencies=[Depends(require_admin)])
def patch_source_review(document_id:int,page_number:int,p:PageReviewPatch):
    if p.page_role is not None and p.page_role not in ROLES:
        raise HTTPException(400,"Invalid page role")
    if p.review_status is not None and p.review_status not in STATUSES:
        raise HTTPException(400,"Invalid review status")
    if p.question_count is not None and p.question_count<0:
        raise HTTPException(400,"question_count must be >= 0")
    with connect() as con:
        row=con.execute("""UPDATE document_page_reviews SET
          page_role=coalesce(%s,page_role),review_status=coalesce(%s,review_status),
          notes=coalesce(%s,notes),question_count=coalesce(%s,question_count),updated_at=now()
          WHERE document_id=%s AND page_number=%s RETURNING *""",
          (p.page_role,p.review_status,p.notes,p.question_count,document_id,page_number)).fetchone()
        if not row: raise HTTPException(404,"Page review not found")
        return row

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>مراجعة المصدر المرئي</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1150px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:15px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.muted{color:#667085;font-size:13px}.ok{color:#067647}.warn{color:#b54708}select,input,button{padding:9px;border:1px solid #ccd2dd;border-radius:8px;font:inherit;margin:3px}button{cursor:pointer}.row{display:flex;gap:6px;flex-wrap:wrap;align-items:center}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/workflow">الأسئلة</a> · <a href="/admin/assets">الرسومات</a></div>
<div class=box><h1>مراجعة صفحات المصادر المصورة</h1><div id=summary class=muted>جارٍ التحميل...</div></div>
<div class=box><div class=row><select id=doc onchange=loadPages()></select><select id=status onchange=loadPages()><option value="">كل الحالات</option><option value=pending>معلق</option><option value=classified>مصنف</option><option value=reviewing>تحت المراجعة</option><option value=done>مكتمل</option><option value=skipped>متخطى</option></select><button onclick=openPdf()>فتح PDF الأصلي</button></div></div>
<div id=pages class=grid></div>
<script>
let docs=[],rows=[];const H=()=>({});function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function jf(u,o={}){let r=await fetch(u,o),x=await r.json();if(!r.ok)throw new Error(typeof x.detail==='string'?x.detail:JSON.stringify(x.detail));return x}
async function init(){let s=await jf('/api/admin/source-review/summary');docs=s.documents||[];doc.innerHTML=docs.map(d=>'<option value="'+d.id+'">#'+d.id+' · '+e(d.filename)+' · '+e(d.academic_year||'')+'</option>').join('');summary.textContent='إجمالي '+s.total+' صفحة · مرشح أسئلة '+s.question_candidate+' · معلق '+s.pending+' · مكتمل '+s.done;loadPages()}
async function loadPages(){if(!doc.value)return;let u='/api/admin/source-review?document_id='+doc.value+(status.value?'&review_status='+status.value:'');rows=await jf(u);pages.innerHTML=rows.map(r=>'<div class=card><b>صفحة '+r.page_number+'</b><div class=muted>'+e(r.academic_year||'')+' · أسئلة مدخلة: '+r.extracted_questions+'</div><select id="role'+r.page_number+'"><option value=question_candidate>مرشح أسئلة</option><option value=answer_solution>حل/إجابة</option><option value=front_matter>غلاف/مقدمة</option><option value=index_or_divider>فهرس/فاصل</option><option value=unknown>غير محدد</option></select><select id="st'+r.page_number+'"><option value=pending>معلق</option><option value=reviewing>تحت المراجعة</option><option value=classified>مصنف</option><option value=done>مكتمل</option><option value=skipped>متخطى</option></select><input id="cnt'+r.page_number+'" type=number min=0 placeholder="عدد الأسئلة" value="'+(r.question_count??'')+'"><button onclick="save('+r.page_number+')">حفظ</button><div class=muted>'+e(r.notes||'')+'</div></div>').join('');rows.forEach(r=>{document.getElementById('role'+r.page_number).value=r.page_role;document.getElementById('st'+r.page_number).value=r.review_status})}
async function save(p){let body={page_role:document.getElementById('role'+p).value,review_status:document.getElementById('st'+p).value};let v=document.getElementById('cnt'+p).value;if(v!=='')body.question_count=Number(v);await jf('/api/admin/source-review/'+doc.value+'/'+p,{method:'PATCH',headers:{...H(),'Content-Type':'application/json'},body:JSON.stringify(body)});loadPages()}
async function openPdf(){let x=await jf('/api/documents/'+doc.value+'/pdf-url');window.open(x.url,'_blank','noopener')}
init()
</script></main></html>'''

@app.get("/admin/source-review",response_class=HTMLResponse)
def source_review_page(): return PAGE
