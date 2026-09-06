from __future__ import annotations

import base64
import os

import fitz
import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin
from .services.source_asset_runtime import _source_pdf

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_RESEARCH_MODEL', 'gemini-3.8-flash').strip() or 'gemini-3.8-flash'
MAX_PAGES_PER_REQUEST = int(os.getenv('GEMINI_RESEARCH_MAX_PAGES', '12'))
MAX_INLINE_PDF_BYTES = int(os.getenv('GEMINI_RESEARCH_MAX_INLINE_BYTES', str(12 * 1024 * 1024)))

RESEARCH_PROVIDERS = {
    'primary_platform': {
        'role': 'orchestration_and_learning_workflows',
        'status': 'active',
    },
    'gemini_source_engine': {
        'role': 'source_research_and_pdf_understanding',
        'status': 'configured' if GEMINI_API_KEY else 'awaiting_api_key',
        'model': GEMINI_MODEL,
        'auto_publish': False,
        'auto_approve_questions': False,
    },
}


class ResearchRequest(BaseModel):
    document_id: int
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    prompt: str = Field(min_length=3, max_length=5000)
    task: str = 'source_analysis'


def _document_row(document_id: int):
    with connect() as con:
        row = con.execute(
            """SELECT id,filename,storage_url,curriculum_version_id,subject_id,grade_level_id,term_id
               FROM documents WHERE id=%s""",
            (document_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, 'Document not found')
    if not row['storage_url']:
        raise HTTPException(409, 'Document has no source storage URL')
    return row


def _subset_pdf(storage_url: str, page_start: int, page_end: int) -> bytes:
    if page_end < page_start:
        raise HTTPException(400, 'page_end must be greater than or equal to page_start')
    count = page_end - page_start + 1
    if count > MAX_PAGES_PER_REQUEST:
        raise HTTPException(400, f'Maximum page range is {MAX_PAGES_PER_REQUEST} pages')
    raw = _source_pdf(storage_url)
    src = fitz.open(stream=raw, filetype='pdf')
    out = fitz.open()
    try:
        if page_start < 1 or page_end > src.page_count:
            raise HTTPException(400, 'Requested page range is outside the source PDF')
        out.insert_pdf(src, from_page=page_start - 1, to_page=page_end - 1)
        data = out.tobytes(garbage=4, deflate=True, clean=True)
    finally:
        out.close()
        src.close()
    if len(data) > MAX_INLINE_PDF_BYTES:
        raise HTTPException(413, 'Selected source range is too large; use a smaller page range')
    return data


def research_engine_status():
    return {
        'providers': RESEARCH_PROVIDERS,
        'active_secondary_provider': 'gemini_source_engine',
        'configured': bool(GEMINI_API_KEY),
        'model': GEMINI_MODEL,
        'max_pages_per_request': MAX_PAGES_PER_REQUEST,
        'guardrails': {
            'source_only': True,
            'question_bank_auto_write': False,
            'scientific_content_auto_approval': False,
            'requires_existing_approved_source': True,
            'output_role': 'advisory_research_only',
        },
    }


def _gemini_source_query(pdf_bytes: bytes, prompt: str, page_start: int, page_end: int, task: str):
    if not GEMINI_API_KEY:
        raise HTTPException(503, 'Gemini research engine is not configured yet')
    system_instruction = (
        'أنت محرك بحث مساعد داخل منصة تعليم الفيزياء. استخدم ملف PDF المرفق فقط. '
        'لا تضف معلومات من الذاكرة العامة ولا تخمّن. إذا لم يدعم المصدر الإجابة فقل ذلك صراحة. '
        f'الصفحات المرسلة من المصدر الأصلي هي من {page_start} إلى {page_end}. '
        'أشر إلى الصفحة الأصلية بوضوح بصيغة [صفحة N]. '
        'أي نص سؤال يجب نقله حرفيًا من المصدر دون إعادة صياغة. '
        'هذه النتيجة استشارية ولا تعني اعتماد المحتوى في بنك الأسئلة.'
    )
    body = {
        'systemInstruction': {'parts': [{'text': system_instruction}]},
        'contents': [{
            'role': 'user',
            'parts': [
                {'text': f'نوع المهمة: {task}\nالمطلوب: {prompt}'},
                {'inlineData': {'mimeType': 'application/pdf', 'data': base64.b64encode(pdf_bytes).decode('ascii')}},
            ],
        }],
        'generationConfig': {'temperature': 0.1},
    }
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'
    try:
        with httpx.Client(timeout=90) as client:
            response = client.post(url, headers={'x-goog-api-key': GEMINI_API_KEY}, json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Gemini research provider is temporarily unavailable') from exc
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[:500]
        raise HTTPException(502, {'message': 'Gemini provider request failed', 'provider_status': response.status_code, 'provider_detail': detail})
    payload = response.json()
    texts = []
    for candidate in payload.get('candidates', []):
        for part in candidate.get('content', {}).get('parts', []):
            if part.get('text'):
                texts.append(part['text'])
    if not texts:
        raise HTTPException(502, 'Gemini provider returned no grounded text')
    return '\n'.join(texts).strip(), payload.get('usageMetadata', {})


@app.get('/api/research-engine/status')
def public_research_engine_status():
    status = research_engine_status()
    return {
        'active_secondary_provider': status['active_secondary_provider'],
        'configured': status['configured'],
        'model': status['model'],
        'source_only': True,
        'auto_publish': False,
    }


@app.get('/api/admin/research-engine/status', dependencies=[Depends(require_admin)])
def api_research_engine_status():
    return research_engine_status()


@app.post('/api/admin/research-engine/query', dependencies=[Depends(require_admin)])
def api_research_engine_query(req: ResearchRequest):
    if req.task not in {'source_analysis', 'lesson_support', 'question_review', 'visual_review'}:
        raise HTTPException(400, 'Unsupported research task')
    doc = _document_row(req.document_id)
    pdf_bytes = _subset_pdf(str(doc['storage_url']), req.page_start, req.page_end)
    answer, usage = _gemini_source_query(pdf_bytes, req.prompt, req.page_start, req.page_end, req.task)
    return {
        'provider': 'gemini_source_engine',
        'model': GEMINI_MODEL,
        'document': {'id': doc['id'], 'filename': doc['filename']},
        'source_pages': {'start': req.page_start, 'end': req.page_end},
        'task': req.task,
        'answer': answer,
        'usage': usage,
        'integrity': {
            'advisory_only': True,
            'auto_saved_to_question_bank': False,
            'auto_approved': False,
            'requires_human_or_deterministic_review_before_use': True,
        },
    }


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>محرك البحث الذكي للمصادر</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,textarea,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:9px}textarea{width:100%;min-height:110px;box-sizing:border-box}button{cursor:pointer}.ok{color:#067647}.warn{color:#b54708}.muted{color:#667085;white-space:pre-wrap}.answer{white-space:pre-wrap;line-height:1.9;background:#f8fafc;padding:14px;border-radius:12px}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/current-corpus">بنك 2026/2027</a></div>
<div class=box><h1>محرك البحث الذكي للمصادر</h1><p>المشغل الثاني: Gemini لفهم ملفات PDF والرسومات والمقارنة داخل المصدر. النتائج استشارية فقط ولا تدخل بنك الأسئلة تلقائيًا.</p><div id=status class=muted>جارٍ تحميل الحالة...</div></div>
<div class=box><div class=row><input id=doc type=number min=1 placeholder="Document ID"><input id=p1 type=number min=1 placeholder="من صفحة"><input id=p2 type=number min=1 placeholder="إلى صفحة"><select id=task><option value=source_analysis>تحليل المصدر</option><option value=lesson_support>دعم شرح درس</option><option value=question_review>مراجعة سؤال</option><option value=visual_review>مراجعة رسم/شكل</option></select></div><textarea id=prompt placeholder="اكتب المطلوب من المصدر فقط..."></textarea><button id=go onclick=run()>تشغيل المشغل الثاني</button></div>
<div class=box><h2>النتيجة</h2><div id=out class=answer>لا توجد نتيجة بعد.</div></div>
<script>async function load(){let r=await fetch('/api/admin/research-engine/status');if(r.status===401){location.href='/admin/login';return}let x=await r.json();status.innerHTML=x.configured?'<span class=ok>✅ Gemini Source Engine مفعّل — '+x.model+'</span>':'<span class=warn>⚠️ المحرك مضاف للكود لكنه ينتظر GEMINI_API_KEY في بيئة الإنتاج.</span>'}async function run(){go.disabled=true;out.textContent='جارٍ تحليل المصدر...';let body={document_id:Number(doc.value),page_start:Number(p1.value),page_end:Number(p2.value),task:task.value,prompt:prompt.value};let r=await fetch('/api/admin/research-engine/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let x=await r.json().catch(()=>({}));out.textContent=r.ok?x.answer:JSON.stringify(x.detail||x,null,2);go.disabled=false}load()</script></main></html>'''


@app.get('/admin/research-engine', response_class=HTMLResponse)
def research_engine_page():
    return PAGE
