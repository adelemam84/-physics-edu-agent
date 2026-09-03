from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from psycopg.errors import UniqueViolation

from .db import STORAGE_BACKEND, connect, init_db
from .security import admin_configured, require_admin
from .services.pdf_ingest import detect_verbatim_question_candidates, extract_pages
from .services.storage import BUCKET, get_bytes, presigned_get, put_bytes, storage_configured


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Physics Educational AI Agent", version="0.9.0", lifespan=lifespan)


class QuestionPatch(BaseModel):
    approved: bool | None = None
    lesson_id: int | None = None
    question_type: str | None = None
    accepted_answer: str | None = None


class ManualQuestionCreate(BaseModel):
    page: int
    text_verbatim: str
    question_type: str = "unknown"


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": app.version,
        "content_policy": "pdf_only",
        "storage": STORAGE_BACKEND,
        "object_storage": "ready" if storage_configured() else "not_configured",
    }


@app.get("/api/admin/status")
def admin_status():
    return {"configured": admin_configured(), "write_protection": "x-admin-key"}


@app.get("/api/storage/status")
def storage_status():
    return {"configured": storage_configured(), "bucket": BUCKET, "mode": "neon_object_storage"}


@app.get("/api/overview")
def overview():
    with connect() as con:
        out = {t: con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in ("documents", "questions", "quizzes", "students", "attempts")}
        out["approved_questions"] = con.execute("SELECT COUNT(*) c FROM questions WHERE approved=TRUE").fetchone()["c"]
        out["review_documents"] = con.execute("SELECT COUNT(*) c FROM documents WHERE status IN ('review_required','extraction_review_required')").fetchone()["c"]
        return out


@app.get("/api/lessons")
def lessons():
    with connect() as con:
        return list(con.execute("SELECT * FROM lessons ORDER BY sort_order,id").fetchall())


@app.get("/api/documents")
def documents():
    with connect() as con:
        return list(
            con.execute(
                """
                SELECT d.*, f.page_count, f.file_size_bytes,
                       (SELECT COUNT(*) FROM questions q WHERE q.document_id=d.id) AS question_count
                FROM documents d
                LEFT JOIN document_files f ON f.document_id=d.id
                ORDER BY d.id DESC
                """
            ).fetchall()
        )


@app.get("/api/documents/{document_id}/pages", dependencies=[Depends(require_admin)])
def document_pages(document_id: int):
    with connect() as con:
        exists = con.execute("SELECT id FROM documents WHERE id=%s", (document_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Document not found")
        return list(
            con.execute(
                """
                SELECT p.page_number,
                       length(coalesce(p.extracted_text,'')) AS text_length,
                       (p.preview_object_key IS NOT NULL) AS preview_cached,
                       (SELECT COUNT(*) FROM questions q WHERE q.document_id=p.document_id AND coalesce(q.source_page,q.page)=p.page_number) AS question_count
                FROM document_pages p
                WHERE p.document_id=%s
                ORDER BY p.page_number
                """,
                (document_id,),
            ).fetchall()
        )


@app.get("/api/documents/{document_id}/page/{page}/text", dependencies=[Depends(require_admin)])
def page_text(document_id: int, page: int):
    with connect() as con:
        row = con.execute(
            "SELECT extracted_text, text_sha256 FROM document_pages WHERE document_id=%s AND page_number=%s",
            (document_id, page),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Page not found")
    return {"page": page, "extracted_text": row["extracted_text"] or "", "text_sha256": row["text_sha256"]}


@app.get("/api/questions")
def questions(approved: bool | None = None, lesson_id: int | None = None, limit: int = 500):
    sql = "SELECT q.*,d.filename source_filename FROM questions q JOIN documents d ON d.id=q.document_id WHERE 1=1"
    params: list[object] = []
    if approved is not None:
        sql += " AND q.approved=%s"
        params.append(approved)
    if lesson_id is not None:
        sql += " AND q.lesson_id=%s"
        params.append(lesson_id)
    sql += " ORDER BY q.id DESC LIMIT %s"
    params.append(min(limit, 1000))
    with connect() as con:
        return list(con.execute(sql, params).fetchall())


@app.patch("/api/questions/{question_id}", dependencies=[Depends(require_admin)])
def patch_question(question_id: int, patch: QuestionPatch):
    values = patch.model_dump(exclude_unset=True)
    allowed = {"approved", "lesson_id", "question_type", "accepted_answer"}
    values = {k: v for k, v in values.items() if k in allowed}
    if not values:
        raise HTTPException(400, "No changes")
    sets = ", ".join(f"{k}=%s" for k in values)
    params = list(values.values()) + [question_id]
    with connect() as con:
        row = con.execute(f"UPDATE questions SET {sets} WHERE id=%s RETURNING *", params).fetchone()
        if not row:
            raise HTTPException(404, "Question not found")
        return row


@app.post("/api/documents/{document_id}/questions/manual", dependencies=[Depends(require_admin)])
def create_manual_question(document_id: int, payload: ManualQuestionCreate):
    if payload.page < 1:
        raise HTTPException(400, "Invalid page")
    if not payload.text_verbatim.strip():
        raise HTTPException(400, "Question text is required")
    if len(payload.text_verbatim) > 50000:
        raise HTTPException(413, "Question text is too large")

    with connect() as con:
        page_row = con.execute(
            "SELECT 1 FROM document_pages WHERE document_id=%s AND page_number=%s",
            (document_id, payload.page),
        ).fetchone()
        if not page_row:
            raise HTTPException(404, "Source page not found")

        duplicate = con.execute(
            "SELECT id FROM questions WHERE document_id=%s AND coalesce(source_page,page)=%s AND text_verbatim=%s LIMIT 1",
            (document_id, payload.page, payload.text_verbatim),
        ).fetchone()
        if duplicate:
            raise HTTPException(409, f"هذا السؤال مسجل بالفعل برقم {duplicate['id']}")

        row = con.execute(
            """
            INSERT INTO questions(document_id,page,source_page,text_verbatim,approved,question_type)
            VALUES (%s,%s,%s,%s,FALSE,%s)
            RETURNING *
            """,
            (document_id, payload.page, payload.page, payload.text_verbatim, payload.question_type or "unknown"),
        ).fetchone()
        con.execute("UPDATE documents SET status='review_required' WHERE id=%s", (document_id,))
        return row


@app.post("/api/documents/upload", dependencies=[Depends(require_admin)])
async def upload_document(file: UploadFile = File(...), subject: str = Form("physics"), kind: str = Form("questions")):
    if not storage_configured():
        raise HTTPException(503, "Object storage is not configured")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")
    if kind not in {"questions", "answers", "reference"}:
        raise HTTPException(400, "Invalid document kind")

    raw = await file.read()
    if not raw or len(raw) > 75 * 1024 * 1024:
        raise HTTPException(413, "Invalid PDF size")
    try:
        pdf = fitz.open(stream=raw, filetype="pdf")
        page_count = pdf.page_count
        pdf.close()
    except Exception:
        raise HTTPException(400, "Invalid PDF")

    digest = hashlib.sha256(raw).hexdigest()
    with connect() as con:
        existing = con.execute(
            "SELECT f.document_id,d.filename FROM document_files f JOIN documents d ON d.id=f.document_id WHERE f.file_sha256=%s LIMIT 1",
            (digest,),
        ).fetchone()
    if existing:
        raise HTTPException(409, f"هذا الملف مرفوع بالفعل كمستند رقم {existing['document_id']}: {existing['filename']}")

    doc_id = None
    pdf_key = None
    try:
        with connect() as con:
            doc_id = con.execute(
                "INSERT INTO documents(filename,subject,kind,status) VALUES (%s,%s,%s,'processing') RETURNING id",
                (file.filename, subject, kind),
            ).fetchone()["id"]
            pdf_key = f"documents/{doc_id}/{digest}.pdf"
            con.execute(
                "INSERT INTO document_files(document_id,bucket_name,object_key,content_type,file_sha256,file_size_bytes,page_count) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (doc_id, BUCKET, pdf_key, "application/pdf", digest, len(raw), page_count),
            )
    except UniqueViolation:
        raise HTTPException(409, "هذا الملف مرفوع بالفعل. تم منع إنشاء نسخة مكررة تلقائيًا.")

    with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(raw)
        path = Path(tmp.name)

    try:
        try:
            put_bytes(pdf_key, raw, "application/pdf")
        except Exception:
            with connect() as con:
                con.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
            raise HTTPException(502, "تعذر حفظ الملف في التخزين. لم يتم تسجيل نسخة ناقصة ويمكن إعادة المحاولة.")

        added = 0
        page_rows = extract_pages(path)
        with connect() as con:
            for page_no, text in page_rows:
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
                con.execute(
                    "INSERT INTO document_pages(document_id,page_number,extracted_text,text_sha256,preview_object_key) VALUES (%s,%s,%s,%s,NULL)",
                    (doc_id, page_no, text, text_hash),
                )
                candidates = detect_verbatim_question_candidates(text) if kind == "questions" else []
                for candidate in candidates:
                    con.execute(
                        "INSERT INTO questions(document_id,page,source_page,text_verbatim,approved) VALUES (%s,%s,%s,%s,FALSE)",
                        (doc_id, page_no, page_no, candidate),
                    )
                    added += 1
            status = "review_required" if added else ("extraction_review_required" if kind == "questions" else "uploaded")
            con.execute("UPDATE documents SET status=%s WHERE id=%s", (status, doc_id))

        return {"document_id": doc_id, "candidate_questions_added": added, "status": status, "page_count": page_count, "sha256": digest}
    finally:
        path.unlink(missing_ok=True)


@app.get("/api/documents/{document_id}/page/{page}/preview", dependencies=[Depends(require_admin)])
def page_preview(document_id: int, page: int):
    with connect() as con:
        row = con.execute(
            """
            SELECT p.preview_object_key, f.object_key, f.page_count
            FROM document_pages p
            JOIN document_files f ON f.document_id=p.document_id
            WHERE p.document_id=%s AND p.page_number=%s
            """,
            (document_id, page),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Page not found")

    if row["preview_object_key"]:
        return Response(get_bytes(row["preview_object_key"]), media_type="image/jpeg")

    raw = get_bytes(row["object_key"])
    try:
        pdf = fitz.open(stream=raw, filetype="pdf")
        if page < 1 or page > pdf.page_count:
            pdf.close()
            raise HTTPException(404, "Page not found")
        pix = pdf.load_page(page - 1).get_pixmap(matrix=fitz.Matrix(1.45, 1.45), alpha=False)
        preview = pix.tobytes("jpeg", jpg_quality=82)
        pdf.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Unable to render page preview")

    preview_key = f"documents/{document_id}/pages/{page:04d}.jpg"
    put_bytes(preview_key, preview, "image/jpeg")
    with connect() as con:
        con.execute(
            "UPDATE document_pages SET preview_object_key=%s WHERE document_id=%s AND page_number=%s",
            (preview_key, document_id, page),
        )
    return Response(preview, media_type="image/jpeg")


@app.get("/api/documents/{document_id}/pdf-url", dependencies=[Depends(require_admin)])
def pdf_url(document_id: int):
    with connect() as con:
        row = con.execute("SELECT object_key FROM document_files WHERE document_id=%s", (document_id,)).fetchone()
    if not row:
        raise HTTPException(404, "PDF unavailable")
    return {"url": presigned_get(row["object_key"], 900), "expires_seconds": 900}


DASH = '''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>وكيل الفيزياء</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1100px;margin:auto;padding:24px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card{background:white;padding:18px;border-radius:16px;box-shadow:0 4px 20px #0001}a{color:#175cd3}</style><main><h1>وكيل الفيزياء التعليمي</h1><p>منصة مبنية على مصادر PDF مع تتبع المصدر والصفحة.</p><div class="cards" id="cards"></div><p><a href="/admin">فتح لوحة الإدارة والمراجعة</a> · <a href="/docs">API Docs</a></p></main><script>fetch('/api/overview').then(r=>r.json()).then(x=>cards.innerHTML=Object.entries(x).map(([k,v])=>`<div class=card><b>${k}</b><h2>${v}</h2></div>`).join(''))</script></html>'''


ADMIN = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>إدارة بنك الأسئلة</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1300px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:15px;margin:12px 0;box-shadow:0 3px 14px #0000000a}.top{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.audit{display:grid;grid-template-columns:260px minmax(0,1fr) 360px;gap:12px}.qgrid{display:grid;grid-template-columns:360px 1fr;gap:12px}input,select,button,textarea{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.55}textarea{width:100%;min-height:190px;box-sizing:border-box;resize:vertical}.doc,.q{padding:10px;border-bottom:1px solid #eee;cursor:pointer}.doc:hover,.q:hover,.active{background:#eef4ff}.pagebar{display:flex;gap:8px;align-items:center;justify-content:center;margin:8px}.preview{width:100%;max-height:72vh;object-fit:contain;background:#eee;border-radius:10px}.raw{white-space:pre-wrap;direction:rtl;max-height:250px;overflow:auto;background:#f7f8fa;padding:10px;border-radius:8px;font-size:13px}#msg,#auditMsg{font-weight:600;margin:6px}.muted{color:#667085;font-size:13px}@media(max-width:900px){.audit,.qgrid{grid-template-columns:1fr}.preview{max-height:none}}
</style><main><h1>لوحة إدارة الفيزياء</h1>
<div class="box top"><input id="key" type="password" placeholder="ADMIN_API_KEY"><button onclick="saveKey()">حفظ المفتاح</button><input id="pdf" type="file" accept="application/pdf"><button id="uploadBtn" onclick="upload()">رفع PDF أسئلة</button><span id="msg"></span></div>
<div class="box"><h2>مراجعة المصدر بصريًا</h2><p class="muted">الصفحة الأصلية هي المرجع. لا يتم تعديل نص السؤال علميًا؛ أي سؤال يُضاف يظل غير معتمد حتى مراجعته.</p><div class="audit"><div><h3>المستندات</h3><div id="docs"></div></div><div><div class="pagebar"><button onclick="movePage(-1)">السابق</button><b id="pageLabel">—</b><button onclick="movePage(1)">التالي</button></div><img id="pageImg" class="preview"><details><summary>النص الخام المستخرج من الصفحة</summary><pre id="rawText" class="raw"></pre></details></div><div><h3>إضافة سؤال من الصفحة</h3><div class="muted">انسخ السؤال كما هو من المصدر، مع الاختيارات إن وجدت. لا تعِد صياغته.</div><textarea id="manualText" placeholder="نص السؤال حرفيًا..."></textarea><select id="qtype"><option value="unknown">غير مصنف</option><option value="mcq">اختيار من متعدد</option><option value="numeric">مسألة حسابية</option><option value="essay">مقالي</option></select><button onclick="saveManual()">حفظ كمرشح للمراجعة</button><div id="auditMsg"></div></div></div></div>
<div class="qgrid"><div class="box"><h3>الأسئلة المرشحة</h3><div id="list"></div></div><div class="box" id="review">اختر سؤالًا للمراجعة</div></div>
</main><script>
let qs=[],documents=[],pages=[],selectedDoc=null,pageIndex=0,sel=null;key.value=localStorage.pk||'';
function h(){return {'X-Admin-Key':localStorage.pk||''}}function saveKey(){localStorage.pk=key.value;msg.textContent='تم حفظ المفتاح';loadAll()}
async function loadAll(){await Promise.all([loadDocs(),loadQuestions()])}
async function loadDocs(){documents=await fetch('/api/documents').then(r=>r.json());docs.innerHTML=documents.map(d=>`<div class="doc ${selectedDoc==d.id?'active':''}" onclick="pickDoc(${d.id})"><b>#${d.id} ${d.filename}</b><br><span class=muted>${d.page_count||0} صفحة · ${d.question_count||0} سؤال · ${d.status}</span></div>`).join('');if(!selectedDoc&&documents.length)pickDoc(documents[0].id)}
async function pickDoc(id){selectedDoc=id;pageIndex=0;pages=await fetch(`/api/documents/${id}/pages`,{headers:h()}).then(r=>r.ok?r.json():[]);await showPage();loadDocs()}
async function showPage(){if(!selectedDoc||!pages.length){pageLabel.textContent='لا توجد صفحات';pageImg.removeAttribute('src');rawText.textContent='';return}pageIndex=Math.max(0,Math.min(pageIndex,pages.length-1));let p=pages[pageIndex].page_number;pageLabel.textContent=`صفحة ${p} من ${pages.length}`;pageImg.src=`/api/documents/${selectedDoc}/page/${p}/preview?t=${Date.now()}`;fetch(`/api/documents/${selectedDoc}/page/${p}/text`,{headers:h()}).then(r=>r.json()).then(x=>rawText.textContent=x.extracted_text||'').catch(()=>rawText.textContent='تعذر تحميل النص الخام')}
function movePage(n){pageIndex+=n;showPage()}
async function saveManual(){if(!selectedDoc||!pages.length)return;let text=manualText.value;if(!text.trim()){auditMsg.textContent='أدخل نص السؤال أولًا';return}let p=pages[pageIndex].page_number;let r=await fetch(`/api/documents/${selectedDoc}/questions/manual`,{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({page:p,text_verbatim:text,question_type:qtype.value})});let x=await r.json();auditMsg.textContent=r.ok?`تم حفظ السؤال #${x.id} كمرشح غير معتمد`:(x.detail||'حدث خطأ');if(r.ok){manualText.value='';await loadQuestions();await loadDocs()}}
async function loadQuestions(){qs=await fetch('/api/questions?limit=500').then(r=>r.json());list.innerHTML=qs.length?qs.map(q=>`<div class=q onclick="pickQ(${q.id})">#${q.id} · ${q.source_filename} · صفحة ${q.source_page||q.page}<br>${q.text_verbatim.slice(0,140)}</div>`).join(''):'لا توجد أسئلة مرشحة حاليًا'}
function pickQ(id){sel=qs.find(x=>x.id==id);let p=sel.source_page||sel.page;review.innerHTML=`<h3>${sel.source_filename} — صفحة ${p}</h3><img id=qimg class=preview><pre class=raw>${escapeHtml(sel.text_verbatim)}</pre><input id=ans placeholder="الإجابة المعتمدة" value="${escapeHtml(sel.accepted_answer||'')}"><button onclick="patchQ(true)">اعتماد</button><button onclick="patchQ(false)">إلغاء الاعتماد</button><button onclick="openPdf()">فتح PDF</button>`;qimg.src=`/api/documents/${sel.document_id}/page/${p}/preview?t=${Date.now()}`}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function patchQ(v){await fetch('/api/questions/'+sel.id,{method:'PATCH',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({approved:v,accepted_answer:ans.value||null})});loadQuestions()}
async function openPdf(){let x=await fetch(`/api/documents/${sel.document_id}/pdf-url`,{headers:h()}).then(r=>r.json());window.open(x.url,'_blank')}
async function upload(){let f=pdf.files[0];if(!f){msg.textContent='اختر ملف PDF أولًا';return}let b=uploadBtn,old=b.textContent;b.disabled=true;b.textContent='جارٍ الرفع...';msg.textContent='جارٍ فحص الملف ورفعه...';try{let d=new FormData();d.append('file',f);d.append('kind','questions');let r=await fetch('/api/documents/upload',{method:'POST',headers:h(),body:d});let x=await r.json();msg.textContent=r.ok?`تم الرفع: ${x.candidate_questions_added} سؤال مرشح · الحالة ${x.status}`:(x.detail||'حدث خطأ أثناء الرفع');if(r.ok){pdf.value='';selectedDoc=x.document_id;await loadAll()}}catch(e){msg.textContent='تعذر الاتصال بالخادم'}finally{b.disabled=false;b.textContent=old}}
loadAll();
</script></html>'''


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASH


@app.get("/admin", response_class=HTMLResponse)
def admin():
    return ADMIN
