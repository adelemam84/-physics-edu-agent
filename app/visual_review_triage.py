from __future__ import annotations

import json
import re

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin


_CANDIDATE_RE = re.compile(r"^\[SOURCE-IMAGE-CANDIDATE\b", re.IGNORECASE)


class VisualReviewDecision(BaseModel):
    decision: str
    reviewed_text: str | None = Field(default=None, max_length=12000)
    reviewer_note: str = Field(min_length=3, max_length=2000)


def _triage_rows(limit: int = 200) -> list[dict]:
    bounded = min(max(int(limit), 1), 250)
    with connect() as con:
        rows = list(con.execute(
            """
            SELECT q.id,q.document_id,coalesce(q.source_page,q.page) source_page,
                   q.text_verbatim,q.approved,q.question_type,q.difficulty,d.filename,
                   qr.severity,qr.details,qr.source_verified,qr.updated_at review_updated_at,
                   s.suggestion,s.confidence,s.model,s.updated_at suggestion_updated_at,
                   EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) has_exact_asset
            FROM question_review_notes qr
            JOIN questions q ON q.id=qr.question_id
            JOIN documents d ON d.id=q.document_id
            LEFT JOIN question_visual_suggestions s ON s.question_id=q.id
            WHERE qr.reason_code='visual_transcription_required'
              AND qr.status='open'
              AND q.curriculum_version_id=(
                SELECT id FROM curriculum_versions
                WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE
                ORDER BY id DESC LIMIT 1
              )
            ORDER BY
              CASE WHEN s.question_id IS NULL THEN 0 ELSE 1 END,
              coalesce(s.confidence,0) ASC,
              q.id ASC
            LIMIT %s
            """,
            (bounded,),
        ).fetchall())
    result=[]
    for row in rows:
        item=dict(row)
        suggestion=item.get("suggestion") or {}
        uncertain=list(suggestion.get("uncertain_parts") or [])
        confidence=float(item.get("confidence") or 0.0)
        if not suggestion:
            band="missing"
        elif uncertain or confidence < 0.65:
            band="high_attention"
        elif confidence < 0.85:
            band="review"
        else:
            band="quick_check"
        item["triage_band"]=band
        item["uncertain_count"]=len(uncertain)
        item["candidate_placeholder"]=bool(_CANDIDATE_RE.match(str(item.get("text_verbatim") or "")))
        item["suggestion"]=suggestion
        result.append(item)
    return result


@app.get("/api/admin/current-corpus/visual-review/triage", dependencies=[Depends(require_admin)])
def visual_review_triage(limit: int = 200):
    items=_triage_rows(limit)
    counts={
        "total":len(items),
        "missing":sum(1 for x in items if x["triage_band"]=="missing"),
        "high_attention":sum(1 for x in items if x["triage_band"]=="high_attention"),
        "review":sum(1 for x in items if x["triage_band"]=="review"),
        "quick_check":sum(1 for x in items if x["triage_band"]=="quick_check"),
    }
    return {
        "items":items,
        "counts":counts,
        "policy":{
            "human_decision_required":True,
            "suggestion_is_advisory":True,
            "auto_approval":False,
            "source_image_is_authoritative":True,
        },
    }


@app.post("/api/admin/current-corpus/visual-review/{question_id}/decision", dependencies=[Depends(require_admin)])
def visual_review_decision(question_id: int, payload: VisualReviewDecision):
    decision=payload.decision.strip().lower()
    if decision not in {"accept","needs_correction","reject"}:
        raise HTTPException(400,"decision must be accept, needs_correction or reject")
    reviewed_text=(payload.reviewed_text or "").strip()
    reviewer_note=payload.reviewer_note.strip()

    with connect() as con:
        row=con.execute(
            """
            SELECT q.id,q.text_verbatim,q.approved,s.suggestion,s.confidence,s.model
            FROM questions q
            JOIN question_review_notes qr ON qr.question_id=q.id
            LEFT JOIN question_visual_suggestions s ON s.question_id=q.id
            WHERE q.id=%s
              AND qr.reason_code='visual_transcription_required'
              AND qr.status='open'
            LIMIT 1
            """,
            (question_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404,"Pending visual-review question not found")

        suggestion=row["suggestion"] or {}
        suggested_text=str(suggestion.get("question_text") or "").strip()
        if decision=="accept":
            if not suggestion:
                raise HTTPException(409,"Visual suggestion is missing")
            final_text=reviewed_text or suggested_text
            if not final_text:
                raise HTTPException(409,"Reviewed verbatim text is required")
            if not _CANDIDATE_RE.match(str(row["text_verbatim"] or "")):
                raise HTTPException(409,"Only source-image candidate placeholders can be replaced here")
            con.execute(
                "UPDATE questions SET text_verbatim=%s,approved=FALSE WHERE id=%s",
                (final_text,question_id),
            )
            con.execute(
                """
                UPDATE question_review_notes
                SET status='resolved',source_verified=TRUE,
                    details=coalesce(details,'')||%s,updated_at=now()
                WHERE question_id=%s
                  AND reason_code='visual_transcription_required'
                  AND status='open'
                """,
                (" | Human visual review accepted source transcription. Note: "+reviewer_note,question_id),
            )
        elif decision=="needs_correction":
            con.execute(
                """
                UPDATE question_review_notes
                SET source_verified=FALSE,
                    details=coalesce(details,'')||%s,updated_at=now()
                WHERE question_id=%s
                  AND reason_code='visual_transcription_required'
                  AND status='open'
                """,
                (" | Human review requested correction. Note: "+reviewer_note,question_id),
            )
        else:
            con.execute(
                """
                UPDATE question_review_notes
                SET source_verified=FALSE,
                    details=coalesce(details,'')||%s,updated_at=now()
                WHERE question_id=%s
                  AND reason_code='visual_transcription_required'
                  AND status='open'
                """,
                (" | Human review rejected AI transcription. Note: "+reviewer_note,question_id),
            )
        updated=con.execute(
            "SELECT id,text_verbatim,approved FROM questions WHERE id=%s",
            (question_id,),
        ).fetchone()
    return {
        "question":dict(updated),
        "decision":decision,
        "qa_resolved":decision=="accept",
        "approved":False,
        "auto_approved":False,
    }


PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مراجعة النسخ البصري</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1300px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 3px 14px #0001}.top{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}.card{padding:12px;border:1px solid #e4e7ec;border-radius:12px}.item{border:1px solid #e4e7ec;border-radius:14px;padding:12px;margin:10px 0}.muted{color:#667085;font-size:13px}.warn{color:#b54708}.bad{color:#b42318}.ok{color:#067647}.pill{display:inline-block;padding:5px 9px;border-radius:999px;background:#f2f4f7;margin:2px}textarea{width:100%;min-height:110px;box-sizing:border-box;padding:9px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}input,button,select{padding:9px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}button{cursor:pointer}.actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}.source{white-space:pre-wrap;background:#f8fafc;padding:10px;border-radius:10px}.suggestion{white-space:pre-wrap;background:#eef4ff;padding:10px;border-radius:10px}@media(max-width:720px){main{padding:10px}.actions button{flex:1 1 45%}}</style><main>
<div class="box top"><a href="/admin/dashboard">لوحة التحكم</a><a href="/admin/workflow">مسار مراجعة السؤال</a><span class=muted>لا يوجد اعتماد تلقائي؛ المصدر المرئي هو المرجع النهائي.</span></div>
<h1>Quality Triage — النسخ البصري</h1><div id=summary class="cards"></div><div class="box top"><select id=filter onchange=render()><option value="">الكل</option><option value="missing">بدون اقتراح</option><option value="high_attention">أولوية عالية</option><option value="review">مراجعة عادية</option><option value="quick_check">فحص سريع</option></select><button onclick=load()>تحديث</button><span id=msg class=muted></span></div><div id=list></div>
<script>
let data={items:[],counts:{}};function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function jf(u,o={}){let r=await fetch(u,o),x=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof x.detail==='string'?x.detail:JSON.stringify(x.detail));return x}
function label(b){return {missing:'بدون اقتراح',high_attention:'أولوية عالية',review:'مراجعة',quick_check:'فحص سريع'}[b]||b}
async function load(){msg.textContent='جارٍ التحميل...';try{data=await jf('/api/admin/current-corpus/visual-review/triage?limit=200');let c=data.counts;summary.innerHTML=[['الإجمالي',c.total],['بدون اقتراح',c.missing],['أولوية عالية',c.high_attention],['مراجعة',c.review],['فحص سريع',c.quick_check]].map(x=>'<div class=card><div class=muted>'+x[0]+'</div><b>'+x[1]+'</b></div>').join('');msg.textContent='المقترحات استشارية فقط';render()}catch(err){msg.textContent=err.message}}
function render(){let f=filter.value,items=data.items.filter(x=>!f||x.triage_band===f);list.innerHTML=items.length?items.map(item=>{let s=item.suggestion||{},unc=s.uncertain_parts||[],conf=Math.round(Number(item.confidence||0)*100);return '<div class=item id="q'+item.id+'"><div class=top><b>#'+item.id+' · صفحة '+item.source_page+'</b><span class=pill>'+label(item.triage_band)+'</span><span class=pill>ثقة '+conf+'%</span><span class=pill>'+e(item.model||'لا يوجد نموذج')+'</span></div><div class=muted>'+e(item.filename)+'</div><h4>الحالي</h4><div class=source>'+e(item.text_verbatim)+'</div><h4>اقتراح المصدر المرئي</h4><div class=suggestion>'+(s.question_text?e(s.question_text):'لا يوجد اقتراح حتى الآن')+(unc.length?'<br><span class=warn>غير واضح: '+e(unc.join('، '))+'</span>':'')+'</div><textarea id="text'+item.id+'" placeholder="النص الحرفي بعد المراجعة البشرية">'+e(s.question_text||'')+'</textarea><input id="note'+item.id+'" placeholder="ملاحظة المراجع البشرية"><div class=actions><button '+(!s.question_text?'disabled':'')+' onclick="decide('+item.id+',\'accept\')">قبول النسخ بعد المراجعة</button><button onclick="decide('+item.id+',\'needs_correction\')">يحتاج تصحيح</button><button onclick="decide('+item.id+',\'reject\')">رفض الاقتراح</button><a href="/admin/workflow?quality_issue=visual_transcription_required">فتح Workspace الكامل</a></div></div>'}).join(''):'<div class=box>لا توجد عناصر بهذا الفلتر.</div>'}
async function decide(id,decision){let note=document.getElementById('note'+id).value.trim(),text=document.getElementById('text'+id).value;if(note.length<3){msg.textContent='اكتب ملاحظة مراجعة واضحة أولًا';return}try{let x=await jf('/api/admin/current-corpus/visual-review/'+id+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision,reviewed_text:text,reviewer_note:note})});msg.textContent=decision==='accept'?'تم إغلاق ملاحظة النسخ البصري يدويًا؛ السؤال ما زال غير معتمد.':'تم تسجيل قرار المراجع وبقيت الملاحظة مفتوحة.';await load()}catch(err){msg.textContent=err.message}}
load();
</script></main></html>'''


@app.get("/admin/visual-review-triage", response_class=HTMLResponse)
def visual_review_triage_page():
    return PAGE
