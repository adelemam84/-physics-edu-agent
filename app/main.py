from __future__ import annotations
import hashlib
from contextlib import asynccontextmanager
from tempfile import NamedTemporaryFile
from pathlib import Path
import fitz
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from psycopg.errors import UniqueViolation
from .db import connect, init_db, STORAGE_BACKEND
from .security import require_admin, admin_configured
from .services.pdf_ingest import extract_pages, detect_verbatim_question_candidates
from .services.storage import BUCKET, storage_configured, put_bytes, get_bytes, presigned_get

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(); yield

app=FastAPI(title="Physics Educational AI Agent",version="0.8.2",lifespan=lifespan)

class QuestionPatch(BaseModel):
    approved: bool|None=None
    lesson_id: int|None=None
    question_type: str|None=None
    accepted_answer: str|None=None

@app.get('/health')
def health(): return {'ok':True,'version':app.version,'content_policy':'pdf_only','storage':STORAGE_BACKEND,'object_storage':'ready' if storage_configured() else 'not_configured'}

@app.get('/api/admin/status')
def admin_status(): return {'configured':admin_configured(),'write_protection':'x-admin-key'}

@app.get('/api/storage/status')
def storage_status(): return {'configured':storage_configured(),'bucket':BUCKET,'mode':'neon_object_storage'}

@app.get('/api/overview')
def overview():
    with connect() as con:
        out={t:con.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ('documents','questions','quizzes','students','attempts')}
        out['approved_questions']=con.execute('SELECT COUNT(*) c FROM questions WHERE approved=TRUE').fetchone()['c']
        return out

@app.get('/api/lessons')
def lessons():
    with connect() as con: return list(con.execute('SELECT * FROM lessons ORDER BY sort_order,id').fetchall())

@app.get('/api/documents')
def documents():
    with connect() as con: return list(con.execute('SELECT d.*,f.page_count,f.file_size_bytes FROM documents d LEFT JOIN document_files f ON f.document_id=d.id ORDER BY d.id DESC').fetchall())

@app.get('/api/questions')
def questions(approved:bool|None=None,lesson_id:int|None=None,limit:int=500):
    sql='SELECT q.*,d.filename source_filename FROM questions q JOIN documents d ON d.id=q.document_id WHERE 1=1'; params=[]
    if approved is not None: sql+=' AND q.approved=%s'; params.append(approved)
    if lesson_id is not None: sql+=' AND q.lesson_id=%s'; params.append(lesson_id)
    sql+=' ORDER BY q.id DESC LIMIT %s'; params.append(min(limit,1000))
    with connect() as con: return list(con.execute(sql,params).fetchall())

@app.patch('/api/questions/{question_id}',dependencies=[Depends(require_admin)])
def patch_question(question_id:int,patch:QuestionPatch):
    values=patch.model_dump(exclude_unset=True); allowed={'approved','lesson_id','question_type','accepted_answer'}; values={k:v for k,v in values.items() if k in allowed}
    if not values: raise HTTPException(400,'No changes')
    sets=', '.join(f'{k}=%s' for k in values); params=list(values.values())+[question_id]
    with connect() as con:
        row=con.execute(f'UPDATE questions SET {sets} WHERE id=%s RETURNING *',params).fetchone()
        if not row: raise HTTPException(404,'Question not found')
        return row

@app.post('/api/documents/upload',dependencies=[Depends(require_admin)])
async def upload_document(file:UploadFile=File(...),subject:str=Form('physics'),kind:str=Form('questions')):
    if not storage_configured(): raise HTTPException(503,'Object storage is not configured')
    if not file.filename or not file.filename.lower().endswith('.pdf'): raise HTTPException(400,'Only PDF files are accepted')
    if kind not in {'questions','answers','reference'}: raise HTTPException(400,'Invalid document kind')
    raw=await file.read()
    if not raw or len(raw)>75*1024*1024: raise HTTPException(413,'Invalid PDF size')
    try:
        pdf=fitz.open(stream=raw,filetype='pdf'); page_count=pdf.page_count; pdf.close()
    except Exception: raise HTTPException(400,'Invalid PDF')

    digest=hashlib.sha256(raw).hexdigest(); doc_id=None; pdf_key=None

    # Fast duplicate check for a clear user-facing response.
    with connect() as con:
        existing=con.execute(
            'SELECT f.document_id,d.filename,d.status FROM document_files f JOIN documents d ON d.id=f.document_id WHERE f.file_sha256=%s LIMIT 1',
            (digest,)
        ).fetchone()
    if existing:
        raise HTTPException(409,f'هذا الملف مرفوع بالفعل كمستند رقم {existing["document_id"]}: {existing["filename"]}')

    # Reserve the SHA-256 and document row atomically. The DB unique index is the
    # final protection against two requests racing at the same moment.
    try:
        with connect() as con:
            doc_id=con.execute(
                'INSERT INTO documents(filename,subject,kind,status) VALUES (%s,%s,%s,%s) RETURNING id',
                (file.filename,subject,kind,'processing')
            ).fetchone()['id']
            pdf_key=f'documents/{doc_id}/{digest}.pdf'
            con.execute(
                'INSERT INTO document_files(document_id,bucket_name,object_key,content_type,file_sha256,file_size_bytes,page_count) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (doc_id,BUCKET,pdf_key,'application/pdf',digest,len(raw),page_count)
            )
    except UniqueViolation:
        raise HTTPException(409,'هذا الملف مرفوع بالفعل. تم منع إنشاء نسخة مكررة تلقائيًا.')

    with NamedTemporaryFile(suffix='.pdf',delete=False) as tmp: tmp.write(raw); path=Path(tmp.name)
    try:
        try:
            put_bytes(pdf_key,raw,'application/pdf')
        except Exception:
            # Release the reservation so a failed storage upload can be retried safely.
            with connect() as con:
                con.execute('DELETE FROM documents WHERE id=%s',(doc_id,))
            raise HTTPException(502,'تعذر حفظ الملف في التخزين. لم يتم تسجيل نسخة ناقصة ويمكن إعادة المحاولة.')

        added=0
        page_rows=extract_pages(path)
        with connect() as con:
            preview_doc=fitz.open(stream=raw,filetype='pdf') if kind=='questions' else None
            try:
                for page_no,text in page_rows:
                    candidates=detect_verbatim_question_candidates(text) if kind=='questions' else []
                    preview_key=None
                    if candidates and preview_doc:
                        pix=preview_doc.load_page(page_no-1).get_pixmap(matrix=fitz.Matrix(1.35,1.35),alpha=False); preview=pix.tobytes('jpeg',jpg_quality=72); preview_key=f'documents/{doc_id}/pages/{page_no:04d}.jpg'; put_bytes(preview_key,preview,'image/jpeg')
                    text_hash=hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None
                    con.execute('INSERT INTO document_pages(document_id,page_number,extracted_text,text_sha256,preview_object_key) VALUES (%s,%s,%s,%s,%s)',(doc_id,page_no,text,text_hash,preview_key))
                    for candidate in candidates:
                        con.execute('INSERT INTO questions(document_id,page,text_verbatim,approved) VALUES (%s,%s,%s,FALSE)',(doc_id,page_no,candidate)); added+=1
            finally:
                if preview_doc: preview_doc.close()
            status='review_required' if kind=='questions' else 'uploaded'; con.execute('UPDATE documents SET status=%s WHERE id=%s',(status,doc_id))
        return {'document_id':doc_id,'candidate_questions_added':added,'status':status,'page_count':page_count,'sha256':digest}
    finally:
        path.unlink(missing_ok=True)

@app.get('/api/documents/{document_id}/page/{page}/preview',dependencies=[Depends(require_admin)])
def page_preview(document_id:int,page:int):
    with connect() as con: row=con.execute('SELECT preview_object_key FROM document_pages WHERE document_id=%s AND page_number=%s',(document_id,page)).fetchone()
    if not row or not row['preview_object_key']: raise HTTPException(404,'Preview unavailable')
    return Response(get_bytes(row['preview_object_key']),media_type='image/jpeg')

@app.get('/api/documents/{document_id}/pdf-url',dependencies=[Depends(require_admin)])
def pdf_url(document_id:int):
    with connect() as con: row=con.execute('SELECT object_key FROM document_files WHERE document_id=%s',(document_id,)).fetchone()
    if not row: raise HTTPException(404,'PDF unavailable')
    return {'url':presigned_get(row['object_key'],900),'expires_seconds':900}

DASH='''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>وكيل الفيزياء</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1100px;margin:auto;padding:24px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card{background:white;padding:18px;border-radius:16px;box-shadow:0 4px 20px #0001}a{color:#175cd3}</style><main><h1>وكيل الفيزياء التعليمي</h1><p>منصة مبنية على مصادر PDF مع تتبع المصدر والصفحة.</p><div class="cards" id="cards"></div><p><a href="/admin">فتح لوحة الإدارة والمراجعة</a> · <a href="/docs">API Docs</a></p></main><script>fetch('/api/overview').then(r=>r.json()).then(x=>cards.innerHTML=Object.entries(x).map(([k,v])=>`<div class=card><b>${k}</b><h2>${v}</h2></div>`).join(''))</script></html>'''

ADMIN='''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>إدارة بنك الأسئلة</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1200px;margin:auto;padding:20px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:360px 1fr;gap:14px}input,select,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.55}.q{padding:10px;border-bottom:1px solid #eee;cursor:pointer}.q:hover{background:#f7f9fc}pre{white-space:pre-wrap;font-family:inherit}#msg{display:inline-block;margin:8px;font-weight:600}@media(max-width:760px){.grid{grid-template-columns:1fr}}</style><main><h1>لوحة إدارة الفيزياء</h1><div class=box><input id=key type=password placeholder="ADMIN_API_KEY"><button onclick="save()">حفظ المفتاح على هذا الجهاز</button><input id=pdf type=file accept="application/pdf"><button id=uploadBtn onclick="upload()">رفع PDF أسئلة</button><span id=msg></span></div><div class=grid><div class=box><h3>الأسئلة</h3><div id=list></div></div><div class=box id=review>اختر سؤالًا للمراجعة</div></div></main><script>let qs=[],sel=null;key.value=localStorage.pk||'';function save(){localStorage.pk=key.value;msg.textContent='تم حفظ مفتاح الإدارة على هذا الجهاز';load()}function h(){return {'X-Admin-Key':localStorage.pk||''}}async function load(){qs=await fetch('/api/questions?limit=500').then(r=>r.json());list.innerHTML=qs.map(q=>`<div class=q onclick="pick(${q.id})">#${q.id} · ${q.source_filename} · صفحة ${q.page}<br>${q.text_verbatim.slice(0,140)}</div>`).join('')}function pick(id){sel=qs.find(x=>x.id==id);review.innerHTML=`<h3>${sel.source_filename} — صفحة ${sel.page}</h3><img id=img style="max-width:100%;border-radius:10px"><pre>${sel.text_verbatim}</pre><input id=ans placeholder="الإجابة المعتمدة" value="${sel.accepted_answer||''}"><button onclick="patch(true)">اعتماد</button><button onclick="patch(false)">إلغاء الاعتماد</button><button onclick="openPdf()">فتح PDF</button>`;fetch(`/api/documents/${sel.document_id}/page/${sel.page}/preview`,{headers:h()}).then(r=>r.blob()).then(b=>img.src=URL.createObjectURL(b))}async function patch(v){await fetch('/api/questions/'+sel.id,{method:'PATCH',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({approved:v,accepted_answer:ans.value||null})});load()}async function openPdf(){let x=await fetch(`/api/documents/${sel.document_id}/pdf-url`,{headers:h()}).then(r=>r.json());window.open(x.url,'_blank')}async function upload(){let f=pdf.files[0];if(!f){msg.textContent='اختر ملف PDF أولاً';return}let b=document.getElementById('uploadBtn');let old=b.textContent;b.disabled=true;b.textContent='جارٍ الرفع...';msg.textContent='جارٍ فحص الملف ورفعه...';try{let d=new FormData();d.append('file',f);d.append('kind','questions');let r=await fetch('/api/documents/upload',{method:'POST',headers:h(),body:d});let x=await r.json();if(r.ok){msg.textContent=`تم الرفع: ${x.candidate_questions_added} سؤال مرشح`;pdf.value='';await load()}else{msg.textContent=typeof x.detail==='string'?x.detail:'حدث خطأ أثناء الرفع'}}catch(e){msg.textContent='تعذر الاتصال بالخادم. حاول مرة أخرى.'}finally{b.disabled=false;b.textContent=old}}load()</script></html>'''

@app.get('/',response_class=HTMLResponse)
def dashboard(): return DASH
@app.get('/admin',response_class=HTMLResponse)
def admin(): return ADMIN
