from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from psycopg.errors import UniqueViolation

from .db import STORAGE_BACKEND, connect, init_db, startup_migration_lock
from .security import admin_configured, admin_session_valid, require_admin
from .services.pdf_ingest import detect_verbatim_question_candidates, extract_pages
from .services.storage import BUCKET, get_bytes, presigned_get, put_bytes, storage_configured
from .release_candidate import source_corpus_benchmark, release_readiness

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Production/serverless releases apply idempotent migrations explicitly in the
    # gated release workflow. Repeating DDL and provider bootstrap on every new
    # function instance serializes cold starts and creates multi-second tail latency.
    if os.getenv("DATABASE_URL") and startup_bootstrap_enabled():
        apply_startup_bootstrap()
    yield

app = FastAPI(title="Science Education Platform", version="1.8.1", lifespan=lifespan)

SENSITIVE_CACHE_PREFIXES = (
    "/admin",
    "/api/admin",
    "/student",
    "/api/student",
    "/api/practice",
    "/api/attempts",
    "/api/integrations/canva/oauth",
)


def _production_runtime() -> bool:
    return os.getenv("VERCEL_ENV", "").strip().lower() == "production"


def _sensitive_cache_path(path: str) -> bool:
    value = str(path or "")
    return any(
        value == prefix or value.startswith(prefix + "/")
        for prefix in SENSITIVE_CACHE_PREFIXES
    )


@app.middleware("http")
async def protect_admin_pages(request: Request, call_next):
    path=request.url.path
    if path.startswith("/admin") and path!="/admin/login" and not admin_session_valid(request):
        return RedirectResponse("/admin/login",status_code=307)
    return await call_next(request)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    response=await call_next(request)
    response.headers.setdefault("X-Request-ID",request_id)
    response.headers.setdefault("X-Content-Type-Options","nosniff")
    response.headers.setdefault("X-Frame-Options","DENY")
    response.headers.setdefault("Referrer-Policy","same-origin")
    response.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies","none")
    response.headers.setdefault("Content-Security-Policy",
      "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    if _sensitive_cache_path(request.url.path):
        response.headers["Cache-Control"]="no-store, max-age=0"
        response.headers["Pragma"]="no-cache"
    if _production_runtime():
        response.headers.setdefault("Strict-Transport-Security","max-age=31536000; includeSubDomains")
    return response

class QuestionPatch(BaseModel):
    approved: bool | None = None
    lesson_id: int | None = None
    subject_id: int | None = None
    grade_level_id: int | None = None
    curriculum_version_id: int | None = None
    term_id: int | None = None
    unit_id: int | None = None
    question_type: str | None = None
    difficulty: str | None = None
    accepted_answer: str | None = None
    answer_verbatim: str | None = None
    answer_document_id: int | None = None
    answer_page: int | None = None

class DocumentContextPatch(BaseModel):
    subject_id:int
    grade_level_id:int
    curriculum_version_id:int
    term_id:int

class ReviewNotePatch(BaseModel):
    status: str
    details: str | None = None

class ManualQuestionCreate(BaseModel):
    page: int
    text_verbatim: str
    question_type: str = "unknown"
    lesson_id: int | None = None
    subject_id: int | None = None
    grade_level_id: int | None = None
    curriculum_version_id: int | None = None
    term_id: int | None = None
    unit_id: int | None = None
    difficulty: str = "unclassified"
    accepted_answer: str | None = None

class StudentCreate(BaseModel):
    student_code:str
    full_name:str
    grade_level_id:int
    subject_id:int|None=None
    curriculum_version_id:int|None=None
    active:bool=True

class EnrollmentPatch(BaseModel):
    subject_id:int
    curriculum_version_id:int
    active:bool=True

class AttemptAnswer(BaseModel):
    question_id:int
    answer:str

class AttemptSubmit(BaseModel):
    student_code:str
    quiz_id:int
    answers:list[AttemptAnswer]

@app.get("/health")
def health():
    return {"status":"ok","service":"science-education-platform","version":app.version,"storage_backend":STORAGE_BACKEND}

@app.get("/")
def root():
    return RedirectResponse("/student")

@app.get('/admin')
def admin_root():
    return RedirectResponse('/admin/dashboard')

@app.get('/api/admin/config',dependencies=[Depends(require_admin)])
def admin_config():
    return {'admin_configured':admin_configured(),'storage_configured':storage_configured(),'bucket':BUCKET,'storage_backend':STORAGE_BACKEND}

@app.get('/api/admin/release-readiness',dependencies=[Depends(require_admin)])
def admin_release_readiness():
    return release_readiness()

@app.get('/api/admin/source-corpus-benchmark',dependencies=[Depends(require_admin)])
def admin_source_corpus_benchmark():
    return source_corpus_benchmark()

@app.get('/api/admin/documents',dependencies=[Depends(require_admin)])
def list_documents():
    with connect() as con:
        rows=con.execute("SELECT id,filename,sha256,page_count,object_key,created_at FROM documents ORDER BY id DESC").fetchall()
    return {'documents':[dict(x) for x in rows]}

@app.post('/api/admin/documents',dependencies=[Depends(require_admin)])
async def upload_document(file:UploadFile=File(...)):
    data=await file.read()
    if not data.startswith(b'%PDF'):
        raise HTTPException(415,'PDF only')
    digest=hashlib.sha256(data).hexdigest()
    with fitz.open(stream=data,filetype='pdf') as doc:
        page_count=doc.page_count
    key=f"sources/{digest}.pdf" if storage_configured() else None
    if key: put_bytes(key,data,'application/pdf')
    with connect() as con:
        try:
            row=con.execute("INSERT INTO documents(filename,sha256,page_count,object_key) VALUES(%s,%s,%s,%s) RETURNING id,filename,sha256,page_count,object_key,created_at",
              (file.filename or 'source.pdf',digest,page_count,key)).fetchone()
        except UniqueViolation:
            row=con.execute("SELECT id,filename,sha256,page_count,object_key,created_at FROM documents WHERE sha256=%s",(digest,)).fetchone()
    return dict(row)

@app.get('/api/admin/documents/{document_id}/pdf',dependencies=[Depends(require_admin)])
def document_pdf(document_id:int):
    with connect() as con:
        row=con.execute("SELECT filename,object_key FROM documents WHERE id=%s",(document_id,)).fetchone()
    if not row: raise HTTPException(404,'Document not found')
    if not row['object_key']: raise HTTPException(409,'PDF bytes unavailable')
    return Response(get_bytes(row['object_key']),media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="document-{document_id}.pdf"'})

@app.post('/api/admin/documents/{document_id}/extract',dependencies=[Depends(require_admin)])
def extract_document(document_id:int):
    with connect() as con:
        row=con.execute("SELECT object_key FROM documents WHERE id=%s",(document_id,)).fetchone()
    if not row or not row['object_key']: raise HTTPException(404,'Document not found')
    data=get_bytes(row['object_key'])
    pages=extract_pages(data)
    with connect() as con:
        for p in pages:
            con.execute("INSERT INTO document_pages(document_id,page_number,text_content) VALUES(%s,%s,%s) ON CONFLICT(document_id,page_number) DO UPDATE SET text_content=excluded.text_content",
              (document_id,p['page'],p['text']))
    return {'document_id':document_id,'pages':len(pages)}

@app.post('/api/admin/documents/{document_id}/detect-questions',dependencies=[Depends(require_admin)])
def detect_questions(document_id:int):
    with connect() as con:
        pages=con.execute("SELECT page_number,text_content FROM document_pages WHERE document_id=%s ORDER BY page_number",(document_id,)).fetchall()
    if not pages: raise HTTPException(409,'Extract pages first')
    candidates=detect_verbatim_question_candidates([{'page':x['page_number'],'text':x['text_content']} for x in pages])
    inserted=0
    with connect() as con:
        for c in candidates:
            con.execute("INSERT INTO questions(document_id,page_number,text_verbatim,question_type) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
              (document_id,c['page'],c['text'],c.get('question_type') or 'unknown'))
            inserted+=1
    return {'document_id':document_id,'candidates':len(candidates),'attempted_inserts':inserted}

@app.patch('/api/admin/questions/{question_id}',dependencies=[Depends(require_admin)])
def patch_question(question_id:int,p:QuestionPatch):
    from .services.question_admin_runtime import patch_question_record
    return patch_question_record(question_id,p.model_dump(exclude_unset=True))

@app.post('/api/admin/questions',dependencies=[Depends(require_admin)],deprecated=True)
def create_manual_question(p:ManualQuestionCreate):
    raise HTTPException(
        409,
        {
            'message':'لا يمكن إنشاء سؤال بلا مصدر PDF',
            'use':'POST /api/documents/{document_id}/questions/manual',
            'policy':'pdf_only_verbatim_questions',
        },
    )

@app.post('/api/admin/students',dependencies=[Depends(require_admin)])
def create_student(p:StudentCreate):
    with connect() as con:
        row=con.execute("INSERT INTO students(student_code,full_name,grade_level_id,active) VALUES(%s,%s,%s,%s) ON CONFLICT(student_code) DO UPDATE SET full_name=excluded.full_name,grade_level_id=excluded.grade_level_id,active=excluded.active RETURNING id,student_code,full_name,grade_level_id,active",
          (p.student_code,p.full_name,p.grade_level_id,p.active)).fetchone()
        if p.subject_id and p.curriculum_version_id:
            con.execute("INSERT INTO student_enrollments(student_id,subject_id,curriculum_version_id,active) VALUES(%s,%s,%s,TRUE) ON CONFLICT(student_id,subject_id,curriculum_version_id) DO UPDATE SET active=TRUE",
              (row['id'],p.subject_id,p.curriculum_version_id))
    return dict(row)

@app.patch('/api/admin/students/{student_id}/enrollments',dependencies=[Depends(require_admin)])
def patch_enrollment(student_id:int,p:EnrollmentPatch):
    with connect() as con:
        con.execute("INSERT INTO student_enrollments(student_id,subject_id,curriculum_version_id,active) VALUES(%s,%s,%s,%s) ON CONFLICT(student_id,subject_id,curriculum_version_id) DO UPDATE SET active=excluded.active",
          (student_id,p.subject_id,p.curriculum_version_id,p.active))
    return {'updated':True}

@app.post('/api/attempts/submit')
def submit_attempt(p:AttemptSubmit):
    with connect() as con:
        student=con.execute("SELECT id FROM students WHERE student_code=%s AND active=TRUE",(p.student_code,)).fetchone()
        if not student: raise HTTPException(404,'Student not found')
        attempt=con.execute("INSERT INTO quiz_attempts(student_id,quiz_id) VALUES(%s,%s) RETURNING id",(student['id'],p.quiz_id)).fetchone()
        for a in p.answers:
            con.execute("INSERT INTO student_answers(attempt_id,question_id,student_answer) VALUES(%s,%s,%s)",(attempt['id'],a.question_id,a.answer))
    return {'attempt_id':attempt['id'],'status':'submitted'}
