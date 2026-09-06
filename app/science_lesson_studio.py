from __future__ import annotations

import base64
import html
import json
import os
import re
import uuid

import fitz
import httpx
from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from .db import connect
from .main import app
from .security import require_admin
from .services.storage import get_bytes, put_bytes, storage_configured

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('LESSON_STUDIO_GEMINI_MODEL', os.getenv('GEMINI_RESEARCH_MODEL', 'gemini-3.8-flash')).strip()
MATHPIX_APP_ID = os.getenv('MATHPIX_APP_ID', '').strip()
MATHPIX_APP_KEY = os.getenv('MATHPIX_APP_KEY', '').strip()
MAX_FILE_BYTES = int(os.getenv('LESSON_STUDIO_MAX_FILE_BYTES', str(12 * 1024 * 1024)))
ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}
OUTPUT_MODES = {'student_simple', 'teacher_notes', 'quick_revision'}
SUBJECTS = {'physics', 'chemistry', 'science'}


def _schema() -> None:
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_jobs(
          id uuid PRIMARY KEY,
          title text NOT NULL,
          subject text NOT NULL,
          grade_label text,
          output_mode text NOT NULL,
          status text NOT NULL DEFAULT 'uploaded',
          ocr_provider text,
          source_count integer NOT NULL DEFAULT 0,
          raw_transcript text,
          structured_json jsonb,
          review_notes text,
          pdf_object_key text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )''')
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_sources(
          id bigserial PRIMARY KEY,
          job_id uuid NOT NULL REFERENCES science_lesson_jobs(id) ON DELETE CASCADE,
          position integer NOT NULL,
          filename text NOT NULL,
          content_type text NOT NULL,
          object_key text NOT NULL,
          extracted_text text,
          confidence numeric,
          created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE(job_id,position)
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_science_lesson_jobs_status ON science_lesson_jobs(status,created_at DESC)')


def _provider() -> str:
    if MATHPIX_APP_ID and MATHPIX_APP_KEY:
        return 'mathpix_stem_ocr'
    if GEMINI_API_KEY:
        return 'gemini_multimodal'
    return 'unconfigured'


def _gemini_text(parts: list[dict], system: str, *, json_mode: bool = False) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(503, 'GEMINI_API_KEY is not configured')
    body = {
        'systemInstruction': {'parts': [{'text': system}]},
        'contents': [{'role': 'user', 'parts': parts}],
        'generationConfig': {'temperature': 0.1},
    }
    if json_mode:
        body['generationConfig']['responseMimeType'] = 'application/json'
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'
    try:
        r = httpx.post(url, headers={'x-goog-api-key': GEMINI_API_KEY}, json=body, timeout=90)
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Gemini is temporarily unavailable') from exc
    if r.status_code >= 400:
        raise HTTPException(502, {'message': 'Gemini request failed', 'status': r.status_code, 'detail': r.text[:500]})
    payload = r.json()
    texts = [p.get('text', '') for c in payload.get('candidates', []) for p in c.get('content', {}).get('parts', []) if p.get('text')]
    if not texts:
        raise HTTPException(502, 'Gemini returned no content')
    return '\n'.join(texts).strip()


def _mathpix_ocr(data: bytes, content_type: str) -> tuple[str, float | None]:
    if content_type == 'application/pdf':
        # Keep PDF handling on Gemini for phase 1; Mathpix PDF is asynchronous and will be added as a worker path.
        raise HTTPException(409, 'Mathpix PDF OCR requires asynchronous worker mode; use image pages or Gemini for now')
    payload = {
        'src': 'data:' + content_type + ';base64,' + base64.b64encode(data).decode('ascii'),
        'formats': ['text'],
        'enable_document_layout': True,
        'metadata': {'improve_mathpix': False},
    }
    try:
        r = httpx.post('https://api.mathpix.com/v3/text', headers={'app_id': MATHPIX_APP_ID, 'app_key': MATHPIX_APP_KEY}, json=payload, timeout=60)
    except httpx.HTTPError as exc:
        raise HTTPException(502, 'Mathpix is temporarily unavailable') from exc
    if r.status_code >= 400:
        raise HTTPException(502, {'message': 'Mathpix OCR failed', 'status': r.status_code, 'detail': r.text[:500]})
    x = r.json()
    return (x.get('text') or '').strip(), x.get('confidence')


def _gemini_ocr(data: bytes, content_type: str, position: int) -> tuple[str, None]:
    prompt = (
        f'هذه الصفحة رقم {position} من ملاحظات مدرس مكتوبة يدويًا. انقل كل المحتوى كما هو دون تحسين أو تصحيح علمي. '
        'حافظ على ترتيب السطور والعناوين والمعادلات والرموز ووحدات القياس. إذا كان جزء غير مقروء فاكتب [غير واضح] بدل التخمين.'
    )
    text = _gemini_text([
        {'text': prompt},
        {'inlineData': {'mimeType': content_type, 'data': base64.b64encode(data).decode('ascii')}},
    ], 'أنت محرك نسخ أمين للملاحظات العلمية المكتوبة يدويًا. لا تضف معلومات من عندك.')
    return text, None


def _organize(transcript: str, subject: str, grade_label: str, title: str, output_mode: str) -> dict:
    schema = {
        'title': 'string', 'subject': subject, 'grade_label': grade_label, 'mode': output_mode,
        'learning_objectives': ['string'],
        'sections': [{'heading': 'string', 'body': 'string', 'source_only': True}],
        'key_terms': [{'term': 'string', 'definition': 'string'}],
        'equations_or_rules': [{'label': 'string', 'expression': 'string', 'notes': 'string'}],
        'diagram_specs': [{'kind': 'circuit|graph|apparatus|process|molecule|comparison|anatomy|other', 'title': 'string', 'description': 'string', 'scientific_labels': ['string'], 'deterministic_required': True}],
        'teacher_warnings': ['string'],
        'uncertain_items': ['string'],
        'summary': 'string'
    }
    instruction = (
        'نظم النص فقط ولا تغيّر المعنى العلمي ولا تضف معلومة علمية جديدة غير موجودة في النص. '
        'يمكنك تحسين ترتيب العناوين وتقسيم الفقرات فقط. أي جزء محتمل الخطأ أو غير الواضح ضعه في uncertain_items. '
        'حدد الرسومات التي ستوضح الشرح في diagram_specs، لكن لا تعتبر وصف الرسم حقيقة علمية إضافية. '
        'أخرج JSON صالحًا فقط يطابق القالب المرفق.'
    )
    raw = _gemini_text([{'text': f'العنوان: {title}\nالمادة: {subject}\nالصف: {grade_label}\nنمط الإخراج: {output_mode}\nقالب JSON: {json.dumps(schema, ensure_ascii=False)}\n\nالنص الأصلي:\n{transcript}'}], instruction, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, 'Lesson organizer returned invalid JSON') from exc


def _job(job_id: str):
    _schema()
    with connect() as con:
        row = con.execute('SELECT * FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson studio job not found')
        sources = list(con.execute('SELECT id,position,filename,content_type,object_key,extracted_text,confidence FROM science_lesson_sources WHERE job_id=%s ORDER BY position', (job_id,)).fetchall())
    return row, sources


def _safe_filename(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name or 'source')[:120]


def _render_pdf(structured: dict) -> bytes:
    title = html.escape(str(structured.get('title') or 'درس علوم'))
    sections = structured.get('sections') or []
    summary = html.escape(str(structured.get('summary') or ''))
    blocks = []
    for s in sections:
        blocks.append(f"<h2>{html.escape(str(s.get('heading') or ''))}</h2><p>{html.escape(str(s.get('body') or '')).replace(chr(10), '<br>')}</p>")
    diagrams = structured.get('diagram_specs') or []
    if diagrams:
        blocks.append('<h2>الرسومات التوضيحية المخططة</h2>')
        for d in diagrams:
            labels = '، '.join(html.escape(str(x)) for x in (d.get('scientific_labels') or []))
            blocks.append(f"<div class='diagram'><b>{html.escape(str(d.get('title') or 'رسم توضيحي'))}</b><br>{html.escape(str(d.get('description') or ''))}<br><small>{labels}</small></div>")
    html_doc = f"<div dir='rtl'><h1>{title}</h1>{''.join(blocks)}<h2>الملخص</h2><p>{summary}</p></div>"
    css = "body{font-family:sans-serif;font-size:13px;line-height:1.7;color:#182230} h1{font-size:24px} h2{font-size:17px;margin-top:18px} .diagram{border:1px solid #bbb;padding:10px;margin:8px 0;background:#f8f8f8}"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(42, 42, 553, 800)
    page.insert_htmlbox(rect, html_doc, css=css, scale_low=0.7)
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return data


@app.get('/api/admin/lesson-studio/status', dependencies=[Depends(require_admin)])
def lesson_studio_status():
    return {
        'module': 'Smart Science Lesson Studio',
        'subjects': sorted(SUBJECTS),
        'output_modes': sorted(OUTPUT_MODES),
        'ocr_provider': _provider(),
        'gemini_configured': bool(GEMINI_API_KEY),
        'mathpix_configured': bool(MATHPIX_APP_ID and MATHPIX_APP_KEY),
        'storage_configured': storage_configured(),
        'policy': {'preserve_original': True, 'no_silent_scientific_correction': True, 'uncertain_items_require_review': True, 'deterministic_science_diagrams': True},
    }


@app.post('/api/admin/lesson-studio/jobs', dependencies=[Depends(require_admin)])
async def create_lesson_job(
    title: str = Form(...), subject: str = Form(...), grade_label: str = Form(''), output_mode: str = Form('teacher_notes'), files: list[UploadFile] = File(...)
):
    _schema()
    if subject not in SUBJECTS:
        raise HTTPException(400, 'subject must be physics, chemistry, or science')
    if output_mode not in OUTPUT_MODES:
        raise HTTPException(400, 'Invalid output mode')
    if not files or len(files) > 20:
        raise HTTPException(400, 'Upload between 1 and 20 source files')
    if not storage_configured():
        raise HTTPException(503, 'Object storage is not configured')
    job_id = str(uuid.uuid4())
    staged = []
    for i, f in enumerate(files, 1):
        ctype = (f.content_type or '').lower()
        if ctype not in ALLOWED_TYPES:
            raise HTTPException(415, f'Unsupported source type: {ctype}')
        data = await f.read()
        if not data or len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f'{f.filename}: file is empty or exceeds limit')
        key = f'lesson-studio/{job_id}/source-{i}-{_safe_filename(f.filename or "source")}'
        put_bytes(key, data, ctype)
        staged.append((i, f.filename or f'source-{i}', ctype, key))
    with connect() as con:
        con.execute('''INSERT INTO science_lesson_jobs(id,title,subject,grade_label,output_mode,source_count,status)
                       VALUES(%s,%s,%s,%s,%s,%s,'uploaded')''', (job_id, title.strip(), subject, grade_label.strip(), output_mode, len(staged)))
        for pos, filename, ctype, key in staged:
            con.execute('INSERT INTO science_lesson_sources(job_id,position,filename,content_type,object_key) VALUES(%s,%s,%s,%s,%s)', (job_id, pos, filename, ctype, key))
    return {'id': job_id, 'status': 'uploaded', 'source_count': len(staged)}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/process', dependencies=[Depends(require_admin)])
def process_lesson_job(job_id: str):
    row, sources = _job(job_id)
    provider = _provider()
    if provider == 'unconfigured':
        raise HTTPException(503, 'No OCR provider configured')
    transcripts = []
    with connect() as con:
        con.execute("UPDATE science_lesson_jobs SET status='transcribing',ocr_provider=%s,updated_at=now() WHERE id=%s", (provider, job_id))
    for s in sources:
        data = get_bytes(s['object_key'])
        if provider == 'mathpix_stem_ocr' and s['content_type'] != 'application/pdf':
            text, confidence = _mathpix_ocr(data, s['content_type'])
        else:
            text, confidence = _gemini_ocr(data, s['content_type'], s['position'])
        transcripts.append(f"[مصدر {s['position']}: {s['filename']}]\n{text}")
        with connect() as con:
            con.execute('UPDATE science_lesson_sources SET extracted_text=%s,confidence=%s WHERE id=%s', (text, confidence, s['id']))
    transcript = '\n\n'.join(transcripts)
    structured = _organize(transcript, row['subject'], row['grade_label'] or '', row['title'], row['output_mode'])
    with connect() as con:
        con.execute("UPDATE science_lesson_jobs SET status='review_required',raw_transcript=%s,structured_json=%s::jsonb,updated_at=now() WHERE id=%s", (transcript, json.dumps(structured, ensure_ascii=False), job_id))
    return {'id': job_id, 'status': 'review_required', 'ocr_provider': provider, 'structured': structured}


@app.get('/api/admin/lesson-studio/jobs/{job_id}', dependencies=[Depends(require_admin)])
def get_lesson_job(job_id: str):
    row, sources = _job(job_id)
    out = dict(row)
    out['sources'] = [dict(x) for x in sources]
    return out


@app.post('/api/admin/lesson-studio/jobs/{job_id}/export-pdf', dependencies=[Depends(require_admin)])
def export_lesson_pdf(job_id: str):
    row, _ = _job(job_id)
    structured = row['structured_json']
    if not structured:
        raise HTTPException(409, 'Process the lesson before PDF export')
    data = _render_pdf(structured)
    key = f'lesson-studio/{job_id}/lesson.pdf'
    if storage_configured():
        put_bytes(key, data, 'application/pdf')
        with connect() as con:
            con.execute("UPDATE science_lesson_jobs SET pdf_object_key=%s,status='pdf_ready',updated_at=now() WHERE id=%s", (key, job_id))
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="lesson-{job_id}.pdf"'})


PAGE = '''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Smart Science Lesson Studio</title><style>body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:900px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:9px}input[type=text]{flex:1;min-width:180px}button{cursor:pointer}.muted{color:#667085;white-space:pre-wrap}</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a></div><div class=box><h1>Smart Science Lesson Studio</h1><p>حوّل صور الشرح المكتوب بخط اليد إلى درس منظم للفيزياء أو الكيمياء أو العلوم، مع الحفاظ على النص الأصلي وفصل أي عناصر تحتاج مراجعة.</p><div id=status class=muted>جارٍ تحميل الحالة...</div></div><form class=box id=f><div class=row><input name=title type=text placeholder="عنوان الدرس" required><select name=subject><option value=science>علوم</option><option value=physics>فيزياء</option><option value=chemistry>كيمياء</option></select><input name=grade_label type=text placeholder="الصف"><select name=output_mode><option value=teacher_notes>مذكرة مدرس</option><option value=student_simple>شرح مبسط</option><option value=quick_revision>مراجعة سريعة</option></select></div><p><input name=files type=file accept="image/*,.pdf" multiple required></p><button>رفع وإنشاء مشروع الدرس</button></form><div class=box><div id=out class=muted>لا توجد عملية بعد.</div></div><script>async function boot(){let r=await fetch('/api/admin/lesson-studio/status');if(r.status===401){location.href='/admin/login';return}let x=await r.json();status.textContent='OCR: '+x.ocr_provider+' · Gemini: '+(x.gemini_configured?'جاهز':'غير مهيأ')+' · Mathpix: '+(x.mathpix_configured?'جاهز':'اختياري')+' · التخزين: '+(x.storage_configured?'جاهز':'غير مهيأ')}f.addEventListener('submit',async e=>{e.preventDefault();out.textContent='جارٍ الرفع...';let r=await fetch('/api/admin/lesson-studio/jobs',{method:'POST',body:new FormData(f)});let x=await r.json();if(!r.ok){out.textContent=JSON.stringify(x.detail||x);return}out.textContent='تم إنشاء المشروع '+x.id+' — جارٍ النسخ والتنظيم...';let p=await fetch('/api/admin/lesson-studio/jobs/'+x.id+'/process',{method:'POST'});let y=await p.json();out.textContent=p.ok?'تم التنظيم. الحالة: '+y.status+'\nرقم المشروع: '+x.id+'\nيمكن تصدير PDF بعد المراجعة.':JSON.stringify(y.detail||y)});boot()</script></main></html>'''


@app.get('/admin/lesson-studio', response_class=HTMLResponse)
def lesson_studio_page():
    return PAGE
