from __future__ import annotations

from contextlib import nullcontext

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .db import connect
from .main import app
from .security import require_admin

ROLES={"front_matter","question_candidate","index_or_divider","answer_solution","unknown"}
STATUSES={"pending","classified","reviewing","done","skipped"}
CLOSED_NONQUESTION_ROLES={"front_matter","index_or_divider","answer_solution"}

class PageReviewPatch(BaseModel):
    page_role:str|None=None
    review_status:str|None=None
    notes:str|None=None
    question_count:int|None=None


def _coverage_state(extracted:int,role:str,status:str,reviewed_count:int|None) -> str:
    extracted=max(int(extracted or 0),0)
    if extracted>0:
        if role=="question_candidate" and status=="done":
            if reviewed_count is None or int(reviewed_count)!=extracted:
                return "question_count_mismatch"
        return "question_page"
    if role in CLOSED_NONQUESTION_ROLES and status=="done":
        return "reviewed_nonquestion"
    if role=="question_candidate":
        return "unresolved_question_candidate"
    return "unreviewed_zero_question"


def _validate_page_closure(*,role:str,status:str,reviewed_count:int|None,extracted:int) -> None:
    if status!="done":
        return
    extracted=max(int(extracted or 0),0)
    if role=="unknown":
        raise HTTPException(409,"لا يمكن إغلاق صفحة قبل تصنيف دورها")
    if role=="question_candidate":
        if reviewed_count is None or int(reviewed_count)<1:
            raise HTTPException(409,"صفحة مرشح الأسئلة تحتاج عدد أسئلة مراجَع أكبر من صفر")
        if int(reviewed_count)!=extracted:
            raise HTTPException(409,{
              "message":"لا يمكن إغلاق الصفحة قبل تطابق عدد الأسئلة مع المصدر",
              "reviewed_question_count":int(reviewed_count),
              "extracted_questions":extracted,
            })
    elif role in CLOSED_NONQUESTION_ROLES and extracted!=0:
        raise HTTPException(409,{
          "message":"لا يمكن إغلاق الصفحة كصفحة غير أسئلة بينما توجد أسئلة مرتبطة بها",
          "extracted_questions":extracted,
        })


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

def _source_page_coverage_snapshot(document_id:int|None=None, *, con=None) -> dict:
    """Read physical-page coverage without creating, approving, or modifying questions."""
    where=["d.kind='questions'"]
    params=[]
    if document_id is not None:
        where.append("d.id=%s");params.append(document_id)
    else:
        where.append("""d.curriculum_version_id=(
          SELECT id FROM curriculum_versions
          WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE
          ORDER BY id DESC LIMIT 1
        )""")
    sql="""WITH source_docs AS (
      SELECT d.*,
        greatest(
          coalesce((SELECT max(f.page_count) FROM document_files f WHERE f.document_id=d.id),0),
          coalesce((SELECT max(p.page_number) FROM document_pages p WHERE p.document_id=d.id),0),
          coalesce((SELECT max(coalesce(q.source_page,q.page)) FROM questions q WHERE q.document_id=d.id),0)
        ) physical_page_count
      FROM documents d
      WHERE """+" AND ".join(where)+"""
    )
    SELECT d.id document_id,d.filename,cv.academic_year,g.page_number,
      coalesce(r.page_role,'unknown') page_role,
      coalesce(r.review_status,'pending') review_status,
      r.question_count reviewed_question_count,
      (SELECT count(*) FROM questions q
       WHERE q.document_id=d.id AND coalesce(q.source_page,q.page)=g.page_number) extracted_questions
      FROM source_docs d
      JOIN LATERAL generate_series(1,d.physical_page_count) g(page_number) ON TRUE
      LEFT JOIN document_page_reviews r
        ON r.document_id=d.id AND r.page_number=g.page_number
      LEFT JOIN curriculum_versions cv ON cv.id=d.curriculum_version_id
      ORDER BY d.id,g.page_number"""
    with (connect() if con is None else nullcontext(con)) as con:
        rows=[dict(r) for r in con.execute(sql,params).fetchall()]

    items=[]
    for row in rows:
        extracted=int(row.get("extracted_questions") or 0)
        reviewed=row.get("reviewed_question_count")
        role=str(row.get("page_role") or "unknown")
        status=str(row.get("review_status") or "pending")
        row["coverage_state"]=_coverage_state(extracted,role,status,reviewed)
        items.append(row)

    summary={
        "physical_pages":len(items),
        "question_pages":sum(1 for r in items if int(r["extracted_questions"] or 0)>0),
        "zero_question_pages":sum(1 for r in items if int(r["extracted_questions"] or 0)==0),
        "reviewed_nonquestion_pages":sum(1 for r in items if r["coverage_state"]=="reviewed_nonquestion"),
        "open_zero_question_pages":sum(1 for r in items if r["coverage_state"] in {"unreviewed_zero_question","unresolved_question_candidate"}),
        "count_mismatch_pages":sum(1 for r in items if r["coverage_state"]=="question_count_mismatch"),
    }
    summary["coverage_ready"]=bool(
        summary["physical_pages"]>0
        and summary["open_zero_question_pages"]==0
        and summary["count_mismatch_pages"]==0
    )
    return {"summary":summary,"items":items}


@app.get("/api/admin/source-review/page-coverage",dependencies=[Depends(require_admin)])
def source_page_coverage(document_id:int|None=None):
    return _source_page_coverage_snapshot(document_id)


@app.get("/api/admin/source-review/summary",dependencies=[Depends(require_admin)])
def source_review_summary(document_id:int|None=None):
    coverage=_source_page_coverage_snapshot(document_id)["summary"]
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
        gate=con.execute("""SELECT
          count(*) FILTER(WHERE r.page_role='question_candidate') candidate_pages,
          count(*) FILTER(WHERE r.page_role='question_candidate' AND r.review_status='done') reviewed_candidate_pages,
          count(*) FILTER(WHERE r.page_role='question_candidate' AND r.review_status IN ('pending','reviewing')) open_candidate_pages
          FROM document_page_reviews r JOIN documents d ON d.id=r.document_id
          LEFT JOIN curriculum_versions cv ON cv.id=d.curriculum_version_id
          WHERE cv.active=TRUE""").fetchone()
        return {**totals,"documents":docs,"current_corpus_gate":gate,
          "current_corpus_ready":bool(gate and gate["candidate_pages"]>0 and gate["open_candidate_pages"]==0),
          "page_coverage":coverage}

@app.patch("/api/admin/source-review/{document_id}/{page_number}",dependencies=[Depends(require_admin)])
def patch_source_review(document_id:int,page_number:int,p:PageReviewPatch):
    if p.page_role is not None and p.page_role not in ROLES:
        raise HTTPException(400,"Invalid page role")
    if p.review_status is not None and p.review_status not in STATUSES:
        raise HTTPException(400,"Invalid review status")
    if p.question_count is not None and p.question_count<0:
        raise HTTPException(400,"question_count must be >= 0")
    with connect() as con:
        current=con.execute("""SELECT r.*,
          (SELECT count(*) FROM questions q
           WHERE q.document_id=r.document_id
             AND coalesce(q.source_page,q.page)=r.page_number) extracted_questions
          FROM document_page_reviews r
          WHERE r.document_id=%s AND r.page_number=%s""",
          (document_id,page_number)).fetchone()
        if not current: raise HTTPException(404,"Page review not found")

        effective_role=p.page_role if p.page_role is not None else current["page_role"]
        effective_status=p.review_status if p.review_status is not None else current["review_status"]
        effective_count=p.question_count if p.question_count is not None else current["question_count"]
        extracted=int(current["extracted_questions"] or 0)

        _validate_page_closure(
          role=effective_role,status=effective_status,
          reviewed_count=effective_count,extracted=extracted,
        )

        row=con.execute("""UPDATE document_page_reviews SET
          page_role=coalesce(%s,page_role),review_status=coalesce(%s,review_status),
          notes=coalesce(%s,notes),question_count=coalesce(%s,question_count),updated_at=now()
          WHERE document_id=%s AND page_number=%s RETURNING *""",
          (p.page_role,p.review_status,p.notes,p.question_count,document_id,page_number)).fetchone()
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
async function init(){let s=await jf('/api/admin/source-review/summary');docs=s.documents||[];doc.innerHTML=docs.map(d=>'<option value="'+d.id+'">#'+d.id+' · '+e(d.filename)+' · '+e(d.academic_year||'')+'</option>').join('');let pc=s.page_coverage||{};summary.textContent='إجمالي '+s.total+' صفحة · مرشح أسئلة '+s.question_candidate+' · معلق '+s.pending+' · مكتمل '+s.done+(s.current_corpus_gate?' · بوابة المنهج الحالي: '+s.current_corpus_gate.reviewed_candidate_pages+'/'+s.current_corpus_gate.candidate_pages+' صفحة مكتملة':'')+' · تغطية الصفحات الفعلية: '+(pc.coverage_ready?'مكتملة':'تحتاج مراجعة')+' · صفر سؤال مفتوح: '+(pc.open_zero_question_pages??0)+' · عدم تطابق العد: '+(pc.count_mismatch_pages??0);loadPages()}
async function loadPages(){if(!doc.value)return;let u='/api/admin/source-review?document_id='+doc.value+(status.value?'&review_status='+status.value:'');rows=await jf(u);pages.innerHTML=rows.map(r=>'<div class=card><b>صفحة '+r.page_number+'</b><div class=muted>'+e(r.academic_year||'')+' · أسئلة مدخلة: '+r.extracted_questions+'</div><select id="role'+r.page_number+'"><option value=question_candidate>مرشح أسئلة</option><option value=answer_solution>حل/إجابة</option><option value=front_matter>غلاف/مقدمة</option><option value=index_or_divider>فهرس/فاصل</option><option value=unknown>غير محدد</option></select><select id="st'+r.page_number+'"><option value=pending>معلق</option><option value=reviewing>تحت المراجعة</option><option value=classified>مصنف</option><option value=done>مكتمل</option><option value=skipped>متخطى</option></select><input id="cnt'+r.page_number+'" type=number min=0 placeholder="عدد الأسئلة" value="'+(r.question_count??'')+'"><button onclick="save('+r.page_number+')">حفظ</button><div class=muted>'+e(r.notes||'')+'</div></div>').join('');rows.forEach(r=>{document.getElementById('role'+r.page_number).value=r.page_role;document.getElementById('st'+r.page_number).value=r.review_status})}
async function save(p){let body={page_role:document.getElementById('role'+p).value,review_status:document.getElementById('st'+p).value};let v=document.getElementById('cnt'+p).value;if(v!=='')body.question_count=Number(v);await jf('/api/admin/source-review/'+doc.value+'/'+p,{method:'PATCH',headers:{...H(),'Content-Type':'application/json'},body:JSON.stringify(body)});loadPages()}
async function openPdf(){let x=await jf('/api/documents/'+doc.value+'/pdf-url');window.open(x.url,'_blank','noopener')}
init()
</script></main></html>'''

@app.get("/admin/source-review",response_class=HTMLResponse)
def source_review_page(): return PAGE
