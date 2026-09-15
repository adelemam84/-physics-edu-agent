from __future__ import annotations

import base64
import os
import time

import fitz
import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin
from .services.ai_orchestrator import build_orchestration_plan, integrity_envelope, plan_dict
from .services.source_asset_runtime import _source_pdf
from .services.ai_telemetry import record_ai_usage
from .services.ai_budget import enforce_ai_budget
from .services.rate_limit import enforce_request_policy
from .services.provider_http import request_with_retries

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_RESEARCH_MODEL', 'gemini-3.8-flash').strip() or 'gemini-3.8-flash'
GEMINI_FILE_SEARCH_STORE = os.getenv('GEMINI_FILE_SEARCH_STORE', '').strip()
MAX_PAGES_PER_REQUEST = int(os.getenv('GEMINI_RESEARCH_MAX_PAGES', '12'))
MAX_INLINE_PDF_BYTES = int(os.getenv('GEMINI_RESEARCH_MAX_INLINE_BYTES', str(12 * 1024 * 1024)))


class ResearchRequest(BaseModel):
    document_id: int
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    prompt: str = Field(min_length=3, max_length=5000)
    task: str = 'source_analysis'


def _document_row(document_id: int):
    with connect() as con:
        row = con.execute(
            """SELECT id,filename,storage_url,curriculum_version_id,subject_id,grade_level_id,term_id,status
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
    configured = bool(GEMINI_API_KEY)
    return {
        'providers': {
            'primary_platform': {
                'role': 'workflow_owner_and_final_gate',
                'status': 'active',
            },
            'gemini_source_engine': {
                'role': 'source_research_and_pdf_understanding',
                'status': 'configured' if configured else 'awaiting_api_key',
                'model': GEMINI_MODEL,
                'file_search_store_configured': bool(GEMINI_FILE_SEARCH_STORE),
                'auto_publish': False,
                'auto_approve_questions': False,
            },
        },
        'orchestrator': {
            'status': 'active',
            'primary_owns_final_decision': True,
            'visual_and_question_review_mode': 'exact_pdf_pages',
            'broad_research_mode': 'file_search_when_configured_else_exact_pdf_pages',
        },
        'active_secondary_provider': 'gemini_source_engine',
        'configured': configured,
        'model': GEMINI_MODEL,
        'file_search_store_configured': bool(GEMINI_FILE_SEARCH_STORE),
        'max_pages_per_request': MAX_PAGES_PER_REQUEST,
        'guardrails': {
            'source_only': True,
            'question_bank_auto_write': False,
            'scientific_content_auto_approval': False,
            'requires_existing_source': True,
            'output_role': 'advisory_research_only',
        },
    }


def _system_instruction(page_start: int, page_end: int) -> str:
    return (
        'أنت محرك بحث مساعد داخل منصة تعليم الفيزياء. استخدم المصدر المرفق/المفهرس فقط. '
        'لا تضف معلومات من الذاكرة العامة ولا تخمّن. إذا لم يدعم المصدر الإجابة فقل ذلك صراحة. '
        f'عند استخدام الصفحات المباشرة فهي من الصفحة الأصلية {page_start} إلى {page_end}. '
        'أشر إلى الصفحة الأصلية بوضوح بصيغة [صفحة N] متى كان ذلك متاحًا. '
        'أي نص سؤال يجب نقله حرفيًا من المصدر دون إعادة صياغة. '
        'هذه النتيجة استشارية ولا تعني اعتماد المحتوى في بنك الأسئلة.'
    )


def _gemini_exact_pdf_query(pdf_bytes: bytes, prompt: str, page_start: int, page_end: int, task: str):
    enforce_ai_budget(provider='gemini', task=task, model=GEMINI_MODEL)
    body = {
        'systemInstruction': {'parts': [{'text': _system_instruction(page_start, page_end)}]},
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
    return _post_generate_content(url, body)


def _gemini_file_search_query(prompt: str, task: str):
    if not GEMINI_FILE_SEARCH_STORE:
        raise HTTPException(503, 'Gemini File Search store is not configured')
    enforce_ai_budget(provider='gemini', task=task, model=GEMINI_MODEL)
    body = {
        'model': GEMINI_MODEL,
        'input': f'{_system_instruction(1, 1)}\nنوع المهمة: {task}\nالمطلوب: {prompt}',
        'tools': [{
            'type': 'file_search',
            'file_search_store_names': [GEMINI_FILE_SEARCH_STORE],
        }],
    }
    url = 'https://generativelanguage.googleapis.com/v1beta/interactions'
    try:
        response = request_with_retries(
            'POST',
            url,
            headers={'x-goog-api-key': GEMINI_API_KEY},
            json=body,
            timeout=90,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Gemini File Search provider is temporarily unavailable') from exc
    if response.status_code >= 400:
        raise HTTPException(502, {
            'message': 'Gemini File Search request failed',
            'provider_status': response.status_code,
        })
    payload = response.json()
    texts=[];citations=[]
    for step in payload.get('steps', []):
        if step.get('type') != 'model_output':
            continue
        for block in step.get('content', []):
            if block.get('text'):
                texts.append(block['text'])
            for annotation in block.get('annotations') or []:
                citations.append(annotation)
    output_text = payload.get('output_text') or '\n'.join(texts).strip()
    if not output_text:
        raise HTTPException(502, 'Gemini File Search returned no grounded text')
    return output_text, payload.get('usage', {}), citations


def _post_generate_content(url: str, body: dict):
    try:
        response = request_with_retries(
            'POST',
            url,
            headers={'x-goog-api-key': GEMINI_API_KEY},
            json=body,
            timeout=90,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Gemini research provider is temporarily unavailable') from exc
    if response.status_code >= 400:
        raise HTTPException(502, {
            'message': 'Gemini provider request failed',
            'provider_status': response.status_code,
        })
    payload = response.json()
    texts=[]
    for candidate in payload.get('candidates', []):
        for part in candidate.get('content', {}).get('parts', []):
            if part.get('text'):
                texts.append(part['text'])
    if not texts:
        raise HTTPException(502, 'Gemini provider returned no grounded text')
    return '\n'.join(texts).strip(), payload.get('usageMetadata', {}), []


def _execute_orchestrated(req: ResearchRequest):
    if req.task not in {'source_analysis', 'lesson_support', 'question_review', 'visual_review'}:
        raise HTTPException(400, 'Unsupported research task')
    if not GEMINI_API_KEY:
        raise HTTPException(503, 'Gemini research engine is not configured yet')
    doc = _document_row(req.document_id)
    page_count=req.page_end-req.page_start+1
    plan=build_orchestration_plan(
        req.task,
        provider_configured=True,
        file_search_configured=bool(GEMINI_FILE_SEARCH_STORE),
        page_count=page_count,
    )
    started = time.perf_counter()
    try:
        if plan.source_mode == 'file_search':
            answer, usage, citations = _gemini_file_search_query(
                f'المستند المطلوب: {doc["filename"]}. {req.prompt}', req.task
            )
        else:
            pdf_bytes = _subset_pdf(str(doc['storage_url']), req.page_start, req.page_end)
            answer, usage, citations = _gemini_exact_pdf_query(
                pdf_bytes, req.prompt, req.page_start, req.page_end, req.task
            )
    except HTTPException as exc:
        record_ai_usage(
            provider='gemini',
            task=req.task,
            model=GEMINI_MODEL,
            status='error',
            latency_ms=round((time.perf_counter()-started)*1000),
            error_code=str(exc.status_code),
            metadata={
                'source_mode': plan.source_mode,
                'document_id': int(doc['id']),
                'page_count': page_count,
            },
        )
        raise
    record_ai_usage(
        provider='gemini',
        task=req.task,
        model=GEMINI_MODEL,
        status='success',
        latency_ms=round((time.perf_counter()-started)*1000),
        usage=usage,
        metadata={
            'source_mode': plan.source_mode,
            'document_id': int(doc['id']),
            'page_count': page_count,
        },
    )
    return {
        'provider': 'gemini_source_engine',
        'model': GEMINI_MODEL,
        'orchestration': plan_dict(plan),
        'document': {'id': doc['id'], 'filename': doc['filename']},
        'source_pages': {'start': req.page_start, 'end': req.page_end},
        'task': req.task,
        'answer': answer,
        'citations': citations,
        'usage': usage,
        'integrity': integrity_envelope(
            provider='gemini_source_engine',
            document_id=int(doc['id']),
            page_start=req.page_start,
            page_end=req.page_end,
        ),
    }


@app.get('/api/research-engine/status')
def public_research_engine_status():
    status = research_engine_status()
    return {
        'active_secondary_provider': status['active_secondary_provider'],
        'configured': status['configured'],
        'model': status['model'],
        'orchestrator_active': True,
        'source_only': True,
        'auto_publish': False,
    }


@app.get('/api/admin/research-engine/status', dependencies=[Depends(require_admin)])
def api_research_engine_status():
    return research_engine_status()


@app.post('/api/admin/research-engine/query', dependencies=[Depends(require_admin)])
def api_research_engine_query(req: ResearchRequest, request: Request):
    enforce_request_policy(
        request,
        name="admin_ai_research",
        default_limit=30,
        default_window_seconds=3600,
    )
    return _execute_orchestrated(req)


@app.post('/api/admin/research-engine/orchestrate', dependencies=[Depends(require_admin)])
def api_research_engine_orchestrate(req: ResearchRequest, request: Request):
    enforce_request_policy(
        request,
        name="admin_ai_research",
        default_limit=30,
        default_window_seconds=3600,
    )
    return _execute_orchestrated(req)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>محرك البحث الذكي للمصادر</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,textarea,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:9px}textarea{width:100%;min-height:110px;box-sizing:border-box}button{cursor:pointer}.ok{color:#067647}.warn{color:#b54708}.muted{color:#667085;white-space:pre-wrap}.answer{white-space:pre-wrap;line-height:1.9;background:#f8fafc;padding:14px;border-radius:12px}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/current-corpus">بنك 2026/2027</a></div>
<div class=box><h1>محرك البحث الذكي للمصادر</h1><p>المحرك الأساسي يملك القرار النهائي، وGemini يعمل كمشغل ثانٍ لفهم PDF والرسومات والبحث داخل المصادر. لا توجد كتابة أو موافقة تلقائية في بنك الأسئلة.</p><div id=status class=muted>جارٍ تحميل الحالة...</div></div>
<div class=box><div class=row><input id=doc type=number min=1 placeholder="Document ID"><input id=p1 type=number min=1 placeholder="من صفحة"><input id=p2 type=number min=1 placeholder="إلى صفحة"><select id=task><option value=source_analysis>تحليل المصدر</option><option value=lesson_support>دعم شرح درس</option><option value=question_review>مراجعة سؤال</option><option value=visual_review>مراجعة رسم/شكل</option></select></div><textarea id=prompt placeholder="اكتب المطلوب من المصدر فقط..."></textarea><button id=go onclick=run()>تشغيل المنظومة</button></div>
<div class=box><h2>النتيجة</h2><div id=mode class=muted></div><div id=out class=answer>لا توجد نتيجة بعد.</div></div>
<script>async function load(){let r=await fetch('/api/admin/research-engine/status');if(r.status===401){location.href='/admin/login';return}let x=await r.json();status.innerHTML=x.configured?'<span class=ok>✅ Orchestrator مفعّل · Gemini '+x.model+(x.file_search_store_configured?' · File Search جاهز':' · PDF direct mode')+'</span>':'<span class=warn>⚠️ Orchestrator جاهز، وGemini ينتظر GEMINI_API_KEY في بيئة الإنتاج.</span>'}async function run(){go.disabled=true;out.textContent='جارٍ تحليل المصدر...';mode.textContent='';let body={document_id:Number(doc.value),page_start:Number(p1.value),page_end:Number(p2.value),task:task.value,prompt:prompt.value};let r=await fetch('/api/admin/research-engine/orchestrate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let x=await r.json().catch(()=>({}));if(r.ok){mode.textContent='المسار المختار: '+x.orchestration.source_mode+' · النتيجة استشارية فقط';out.textContent=x.answer}else{out.textContent=JSON.stringify(x.detail||x,null,2)}go.disabled=false}load()</script></main></html>'''


@app.get('/admin/research-engine', response_class=HTMLResponse)
def research_engine_page():
    return PAGE
