from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from psycopg.errors import UniqueViolation

from .db import STORAGE_BACKEND, connect, init_db
from .security import admin_configured, admin_session_valid, require_admin
from .services.pdf_ingest import detect_verbatim_question_candidates, extract_pages
from .services.storage import BUCKET, get_bytes, presigned_get, put_bytes, storage_configured
from .release_candidate import source_corpus_benchmark, release_readiness

@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv('DATABASE_URL'):
        init_db()
        from .services.corpus_phase2_runtime import run_phase2_bootstrap
        run_phase2_bootstrap()
    yield

app = FastAPI(title="Science Education Platform", version="1.4.0", lifespan=lifespan)

@app.middleware("http")
async def protect_admin_pages(request: Request, call_next):
    path=request.url.path
    if path.startswith("/admin") and path!="/admin/login" and not admin_session_valid(request):
        return RedirectResponse("/admin/login",status_code=307)
    return await call_next(request)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response=await call_next(request)
    response.headers.setdefault("X-Content-Type-Options","nosniff")
    response.headers.setdefault("X-Frame-Options","DENY")
    response.headers.setdefault("Referrer-Policy","same-origin")
    response.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy",
      "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
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

@app.get('/health')
def health(): return {'ok':True,'version':app.version,'content_policy':'pdf_only','storage':STORAGE_BACKEND,'object_storage':'ready' if storage_configured() else 'not_configured'}
@app.get('/api/release/status')
def release_status():
    r=release_readiness()
    return {'version':r['version'],'status':r['status'],'blockers':r['blockers']}

@app.get('/api/current-curriculum/status')
def current_curriculum_status():
    with connect() as con:
        row=con.execute("""SELECT cv.id,cv.academic_year,cv.version_label,
          (SELECT count(*) FROM documents d WHERE d.curriculum_version_id=cv.id) source_documents,
          (SELECT count(*) FROM document_pages p JOIN documents d ON d.id=p.document_id WHERE d.curriculum_version_id=cv.id) source_pages,
          (SELECT count(*) FROM document_page_reviews r JOIN documents d ON d.id=r.document_id WHERE d.curriculum_version_id=cv.id AND r.page_role='question_candidate') candidate_question_pages,
          (SELECT count(*) FROM document_page_reviews r JOIN documents d ON d.id=r.document_id WHERE d.curriculum_version_id=cv.id AND r.review_status='pending') pending_visual_pages,
          (SELECT count(*) FROM questions q WHERE q.curriculum_version_id=cv.id) total_questions,
          (SELECT count(*) FROM questions q WHERE q.curriculum_version_id=cv.id AND q.approved=TRUE) approved_questions,
          (SELECT count(*) FROM question_review_notes qr JOIN questions q ON q.id=qr.question_id WHERE q.curriculum_version_id=cv.id AND qr.status='open') qa_open,
          (SELECT count(*) FROM question_review_notes qr JOIN questions q ON q.id=qr.question_id WHERE q.curriculum_version_id=cv.id AND qr.status='resolved') qa_resolved,
          (SELECT count(*) FROM quizzes z WHERE z.curriculum_version_id=cv.id AND z.published=TRUE) published_quizzes
          FROM curriculum_versions cv
          WHERE cv.subject_id=1 AND cv.grade_level_id=6 AND cv.active=TRUE
          ORDER BY cv.id DESC LIMIT 1""").fetchone()
        if not row:
            return {'active':False,'status':'not_configured'}
        out=dict(row)
        out['active']=True
        if out['approved_questions']>0 and out['published_quizzes']>0 and out['qa_open']==0:
            out['status']='ready'
        elif out['approved_questions']>0 and out['published_quizzes']>0:
            out['status']='partial_bank_ready'
        else:
            out['status']='source_review_in_progress'
        return out
@app.get('/api/release/source-benchmark',dependencies=[Depends(require_admin)])
def release_source_benchmark(): return source_corpus_benchmark()
@app.get('/api/release/readiness',dependencies=[Depends(require_admin)])
def release_readiness_api(): return release_readiness()
@app.get('/api/admin/status',dependencies=[Depends(require_admin)])
def admin_status(): return {'configured':admin_configured(),'authentication':'secure_http_only_session','session_protected':True}
@app.get('/api/storage/status')
def storage_status(): return {'configured':storage_configured(),'bucket':BUCKET,'mode':'neon_object_storage'}
@app.get('/api/overview')
def overview():
    with connect() as con:
        out={t:con.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ('documents','questions','quizzes','students','attempts')}; out['approved_questions']=con.execute('SELECT COUNT(*) c FROM questions WHERE approved=TRUE').fetchone()['c']; out['review_documents']=con.execute("SELECT COUNT(*) c FROM documents WHERE status IN ('review_required','extraction_review_required')").fetchone()['c']; out['qa_open']=con.execute("SELECT COUNT(*) c FROM question_review_notes WHERE status='open'").fetchone()['c']; out['qa_critical']=con.execute("SELECT COUNT(*) c FROM question_review_notes WHERE status='open' AND severity='critical'").fetchone()['c']; out['ready_quizzes']=con.execute("SELECT COUNT(*) c FROM quizzes WHERE lifecycle_status='ready' AND published=FALSE").fetchone()['c']; return out
@app.get('/api/lessons')
def lessons(subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None,term_id:int|None=None,unit_id:int|None=None):
    sql='SELECT * FROM lessons WHERE 1=1';params=[]
    if subject_id is not None:sql+=' AND subject_id=%s';params.append(subject_id)
    if grade_level_id is not None:sql+=' AND grade_level_id=%s';params.append(grade_level_id)
    if curriculum_version_id is not None:sql+=' AND curriculum_version_id=%s';params.append(curriculum_version_id)
    if term_id is not None:sql+=' AND term_id=%s';params.append(term_id)
    if unit_id is not None:sql+=' AND unit_id=%s';params.append(unit_id)
    sql+=' ORDER BY sort_order,id'
    with connect() as con:return list(con.execute(sql,params).fetchall())
@app.get('/api/documents',dependencies=[Depends(require_admin)])
def documents():
    with connect() as con:return list(con.execute("""SELECT d.*,
        coalesce(f.page_count,(SELECT count(*) FROM document_pages p WHERE p.document_id=d.id)) page_count,
        f.file_size_bytes,
        (SELECT COUNT(*) FROM questions q WHERE q.document_id=d.id) question_count
        FROM documents d LEFT JOIN document_files f ON f.document_id=d.id ORDER BY d.id DESC""").fetchall())
@app.patch('/api/documents/{document_id}/academic-context',dependencies=[Depends(require_admin)])
def patch_document_context(document_id:int,p:DocumentContextPatch):
    with connect() as con:
        doc=con.execute("SELECT id,filename FROM documents WHERE id=%s",(document_id,)).fetchone()
        if not doc: raise HTTPException(404,"Document not found")
        sub=con.execute("SELECT id,name_ar FROM subjects WHERE id=%s AND active=TRUE",(p.subject_id,)).fetchone()
        grade=con.execute("SELECT id,name_ar FROM grade_levels WHERE id=%s AND active=TRUE",(p.grade_level_id,)).fetchone()
        cv=con.execute("""SELECT id,subject_id,grade_level_id,academic_year FROM curriculum_versions
          WHERE id=%s AND active=TRUE""",(p.curriculum_version_id,)).fetchone()
        term=con.execute("SELECT id,curriculum_version_id,name_ar FROM academic_terms WHERE id=%s",(p.term_id,)).fetchone()
        if not all((sub,grade,cv,term)): raise HTTPException(400,"السياق الأكاديمي غير مكتمل")
        if cv["subject_id"]!=p.subject_id or cv["grade_level_id"]!=p.grade_level_id:
            raise HTTPException(400,"المنهج لا يطابق المادة والصف المختارين")
        if term["curriculum_version_id"]!=p.curriculum_version_id:
            raise HTTPException(400,"الترم لا يطابق إصدار المنهج")
        row=con.execute("""UPDATE documents SET subject_id=%s,grade_level_id=%s,curriculum_version_id=%s,
          term_id=%s,subject=%s WHERE id=%s RETURNING *""",
          (p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id,sub["name_ar"],document_id)).fetchone()
        con.execute("""UPDATE questions SET subject_id=%s,grade_level_id=%s,curriculum_version_id=%s,term_id=%s
          WHERE document_id=%s AND approved=FALSE""",
          (p.subject_id,p.grade_level_id,p.curriculum_version_id,p.term_id,document_id))
        return {"document":row,"propagated_to_unapproved_questions":True}

@app.get('/api/documents/{document_id}/pages',dependencies=[Depends(require_admin)])
def document_pages(document_id:int):
    with connect() as con:
        if not con.execute('SELECT id FROM documents WHERE id=%s',(document_id,)).fetchone():raise HTTPException(404,'Document not found')
        return list(con.execute("SELECT p.page_number,length(coalesce(p.extracted_text,'')) text_length,(p.preview_object_key IS NOT NULL) preview_cached,(SELECT COUNT(*) FROM questions q WHERE q.document_id=p.document_id AND coalesce(q.source_page,q.page)=p.page_number) question_count FROM document_pages p WHERE p.document_id=%s ORDER BY p.page_number",(document_id,)).fetchall())
@app.get('/api/documents/{document_id}/page/{page}/text',dependencies=[Depends(require_admin)])
def page_text(document_id:int,page:int):
    with connect() as con:row=con.execute('SELECT extracted_text,text_sha256 FROM document_pages WHERE document_id=%s AND page_number=%s',(document_id,page)).fetchone()
    if not row:raise HTTPException(404,'Page not found')
    return {'page':page,'extracted_text':row['extracted_text'] or '','text_sha256':row['text_sha256']}
@app.get('/api/questions',dependencies=[Depends(require_admin)])
def questions(approved:bool|None=None,lesson_id:int|None=None,subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None,term_id:int|None=None,unit_id:int|None=None,difficulty:str|None=None,question_type:str|None=None,workflow_state:str|None=None,chapter:str|None=None,limit:int=500):
    sql="""SELECT q.*,d.filename source_filename,ad.filename answer_source_filename,l.chapter,l.title lesson_title,
           qr.reason_code review_reason,qr.severity review_severity,qr.details review_details,qr.status review_status,
           CASE WHEN q.answer_document_id IS NOT NULL AND q.answer_page IS NOT NULL THEN 'pdf_source' ELSE 'manual_review' END AS answer_source_type,
           EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) AS has_asset,
           CASE
             WHEN q.approved=TRUE THEN 'approved'
             WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
                  AND q.document_id IS NOT NULL
                  AND coalesce(q.source_page,q.page) IS NOT NULL
                  AND q.subject_id IS NOT NULL
                  AND q.grade_level_id IS NOT NULL
                  AND q.curriculum_version_id IS NOT NULL
                  AND q.term_id IS NOT NULL
                  AND q.unit_id IS NOT NULL
                  AND q.lesson_id IS NOT NULL
                  AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
                  AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
                  AND q.question_type <> 'unknown'
                  AND q.difficulty <> 'unclassified'
                  AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>'' THEN 'reviewed'
             WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) THEN 'cropped'
             ELSE 'draft'
           END AS workflow_state
           FROM questions q JOIN documents d ON d.id=q.document_id
           LEFT JOIN documents ad ON ad.id=q.answer_document_id
           LEFT JOIN lessons l ON l.id=q.lesson_id WHERE 1=1""";params=[]
    if subject_id is not None:sql+=' AND q.subject_id=%s';params.append(subject_id)
    if grade_level_id is not None:sql+=' AND q.grade_level_id=%s';params.append(grade_level_id)
    if curriculum_version_id is not None:sql+=' AND q.curriculum_version_id=%s';params.append(curriculum_version_id)
    if term_id is not None:sql+=' AND q.term_id=%s';params.append(term_id)
    if unit_id is not None:sql+=' AND q.unit_id=%s';params.append(unit_id)
    if approved is not None:sql+=' AND q.approved=%s';params.append(approved)
    if lesson_id is not None:sql+=' AND q.lesson_id=%s';params.append(lesson_id)
    if difficulty is not None:
        if difficulty not in {'unclassified','easy','medium','hard'}: raise HTTPException(400,'Invalid difficulty')
        sql+=' AND q.difficulty=%s';params.append(difficulty)
    if question_type is not None:
        sql+=' AND q.question_type=%s';params.append(question_type)
    if chapter is not None:
        sql+=' AND l.chapter=%s';params.append(chapter)
    if workflow_state is not None:
        if workflow_state not in {'draft','cropped','reviewed','approved'}: raise HTTPException(400,'Invalid workflow_state')
        state_sql="""CASE
             WHEN q.approved=TRUE THEN 'approved'
             WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
                  AND q.document_id IS NOT NULL
                  AND coalesce(q.source_page,q.page) IS NOT NULL
                  AND q.lesson_id IS NOT NULL
                  AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
                  AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
                  AND q.question_type <> 'unknown'
                  AND q.difficulty <> 'unclassified'
                  AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>'' THEN 'reviewed'
             WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) THEN 'cropped'
             ELSE 'draft' END"""
        sql+=f' AND ({state_sql})=%s';params.append(workflow_state)
    sql+=' ORDER BY q.id DESC LIMIT %s';params.append(min(limit,1000))
    with connect() as con:return list(con.execute(sql,params).fetchall())

@app.get('/api/admin/corpus/qa',dependencies=[Depends(require_admin)])
def corpus_qa(status:str|None='open',reason_code:str|None=None):
    sql="""SELECT qr.question_id,qr.reason_code,qr.severity,qr.details,qr.source_verified,qr.status,qr.updated_at,
      q.approved,q.source_page,q.text_verbatim,q.accepted_answer,d.filename source_filename,l.title lesson_title
      FROM question_review_notes qr JOIN questions q ON q.id=qr.question_id
      LEFT JOIN documents d ON d.id=q.document_id LEFT JOIN lessons l ON l.id=q.lesson_id WHERE 1=1"""
    params=[]
    if status is not None: sql+=' AND qr.status=%s';params.append(status)
    if reason_code is not None: sql+=' AND qr.reason_code=%s';params.append(reason_code)
    sql+=' ORDER BY CASE qr.severity WHEN \'critical\' THEN 0 ELSE 1 END,qr.question_id'
    with connect() as con:return list(con.execute(sql,params).fetchall())

@app.get('/api/admin/corpus/qa/summary',dependencies=[Depends(require_admin)])
def corpus_qa_summary():
    with connect() as con:
        totals=con.execute("""SELECT count(*) total,
          count(*) FILTER(WHERE status='open') open,
          count(*) FILTER(WHERE status='open' AND severity='critical') critical,
          count(*) FILTER(WHERE status='resolved') resolved
          FROM question_review_notes""").fetchone()
        reasons=list(con.execute("""SELECT reason_code,count(*) c
          FROM question_review_notes WHERE status='open' GROUP BY reason_code ORDER BY c DESC,reason_code""").fetchall())
        return {**totals,'by_reason':reasons}

@app.patch('/api/admin/corpus/qa/{question_id}',dependencies=[Depends(require_admin)])
def patch_corpus_qa(question_id:int,p:ReviewNotePatch):
    if p.status not in {'open','resolved','dismissed'}: raise HTTPException(400,'Invalid QA status')
    with connect() as con:
        note=con.execute("SELECT * FROM question_review_notes WHERE question_id=%s",(question_id,)).fetchone()
        if not note: raise HTTPException(404,'QA note not found')
        row=con.execute("""UPDATE question_review_notes SET status=%s,
          details=coalesce(%s,details),updated_at=now() WHERE question_id=%s RETURNING *""",
          (p.status,p.details,question_id)).fetchone()
        return row

@app.get('/api/question-stats',dependencies=[Depends(require_admin)])
def question_stats():
    with connect() as con:
        totals=con.execute("""SELECT count(*) total,
          count(*) FILTER(WHERE approved) approved,
          count(*) FILTER(WHERE NOT approved) unapproved,
          count(*) FILTER(WHERE difficulty='easy') easy,
          count(*) FILTER(WHERE difficulty='medium') medium,
          count(*) FILTER(WHERE difficulty='hard') hard,
          count(*) FILTER(WHERE difficulty='unclassified') unclassified
          FROM questions""").fetchone()
        by_lesson=list(con.execute("""SELECT l.chapter,l.title, count(q.id) total,
          count(q.id) FILTER(WHERE q.approved) approved
          FROM lessons l LEFT JOIN questions q ON q.lesson_id=l.id
          GROUP BY l.id,l.chapter,l.title,l.sort_order ORDER BY l.sort_order,l.id""").fetchall())
        by_type=list(con.execute("""SELECT question_type,count(*) total FROM questions GROUP BY question_type ORDER BY total DESC""").fetchall())
        by_state=list(con.execute("""SELECT state,count(*) total FROM (
          SELECT CASE WHEN q.approved THEN 'approved'
            WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
             AND q.lesson_id IS NOT NULL AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) AND q.question_type<>'unknown' AND q.difficulty<>'unclassified' AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>'' THEN 'reviewed'
            WHEN EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) THEN 'cropped'
            ELSE 'draft' END state FROM questions q) s GROUP BY state ORDER BY state""").fetchall())
        return {'totals':totals,'by_lesson':by_lesson,'by_type':by_type,'by_state':by_state}

@app.get('/api/questions/{question_id}/readiness',dependencies=[Depends(require_admin)])
def question_readiness(question_id:int):
    with connect() as con:
        row=con.execute("""SELECT q.id,q.document_id,coalesce(q.source_page,q.page) page_number,q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id,q.unit_id,q.lesson_id,q.question_type,q.difficulty,q.accepted_answer,q.approved,
          EXISTS(SELECT 1 FROM document_pages p WHERE p.document_id=q.document_id AND p.page_number=coalesce(q.source_page,q.page)) source_page_exists,
          EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id AND a.document_id=q.document_id AND a.page_number=coalesce(q.source_page,q.page)) asset_valid,
          EXISTS(SELECT 1 FROM documents d WHERE d.id=q.document_id AND d.storage_url IS NOT NULL) external_source,
          (q.text_verbatim ~ '(بالشكل|بالرسم|الرسم|الشكل)') diagram_required,
          EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
          EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
          EXISTS(SELECT 1 FROM lessons l WHERE l.id=q.lesson_id
            AND l.subject_id=q.subject_id AND l.grade_level_id=q.grade_level_id
            AND l.curriculum_version_id=q.curriculum_version_id AND l.term_id=q.term_id AND l.unit_id=q.unit_id) academic_consistent,
          NOT EXISTS(SELECT 1 FROM question_concepts qc JOIN concepts c ON c.id=qc.concept_id
            WHERE qc.question_id=q.id AND c.lesson_id IS DISTINCT FROM q.lesson_id) concept_consistent
          FROM questions q WHERE q.id=%s""",(question_id,)).fetchone()
    if not row: raise HTTPException(404,'Question not found')
    visual_ready=bool(row['asset_valid'] or (row['external_source'] and not row['diagram_required']))
    source_ready=bool(row['document_id'] and row['page_number'] and row['source_page_exists'] and visual_ready)
    classified=bool(row['subject_id'] and row['grade_level_id'] and row['curriculum_version_id'] and row['term_id'] and row['unit_id'] and row['lesson_id'] and row['has_concept'] and row['has_skill'] and row['academic_consistent'] and row['concept_consistent'] and row['question_type']!='unknown' and row['difficulty']!='unclassified' and row['accepted_answer'] and str(row['accepted_answer']).strip())
    ready=source_ready and classified
    state='approved' if row['approved'] else ('reviewed' if ready else ('cropped' if row['asset_valid'] else 'draft'))
    return {**row,'ready_for_approval':ready,'workflow_state':state}

@app.get('/api/admin/questions/{question_id}/quality-check',dependencies=[Depends(require_admin)])
def question_quality_check(question_id:int):
    with connect() as con:
        q=con.execute("""SELECT q.*,
          EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) has_asset,
          EXISTS(SELECT 1 FROM documents d WHERE d.id=q.document_id AND d.storage_url IS NOT NULL) external_source,
          (q.text_verbatim ~ '(بالشكل|بالرسم|الرسم|الشكل)') diagram_required,
          EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
          EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
          EXISTS(SELECT 1 FROM lessons l WHERE l.id=q.lesson_id AND l.subject_id=q.subject_id
            AND l.grade_level_id=q.grade_level_id AND l.curriculum_version_id=q.curriculum_version_id
            AND l.term_id=q.term_id AND l.unit_id=q.unit_id) academic_consistent,
          NOT EXISTS(SELECT 1 FROM question_concepts qc JOIN concepts c ON c.id=qc.concept_id
            WHERE qc.question_id=q.id AND c.lesson_id IS DISTINCT FROM q.lesson_id) concept_consistent
          FROM questions q WHERE q.id=%s""",(question_id,)).fetchone()
        if not q: raise HTTPException(404,'Question not found')
        checks=[
          {'id':'source','label':'مرتبط بمصدر PDF وصفحة','ok':bool(q['document_id'] and (q['source_page'] or q['page']))},
          {'id':'asset','label':'له قصاصة/رسم معتمد','ok':bool(q['has_asset'] or (q['external_source'] and not q['diagram_required']))},
          {'id':'academic_scope','label':'السياق الأكاديمي مكتمل ومتسق','ok':bool(q['subject_id'] and q['grade_level_id'] and q['curriculum_version_id'] and q['term_id'] and q['unit_id'] and q['lesson_id'] and q['academic_consistent'])},
          {'id':'concept','label':'مرتبط بمفهوم من نفس الدرس','ok':bool(q['has_concept'] and q['concept_consistent'])},
          {'id':'skill','label':'مرتبط بمهارة','ok':bool(q['has_skill'])},
          {'id':'classification','label':'النوع والصعوبة مصنفان','ok':q['question_type']!='unknown' and q['difficulty']!='unclassified'},
          {'id':'answer','label':'له إجابة معتمدة','ok':bool(q['accepted_answer'] and str(q['accepted_answer']).strip())}]
        return {'question_id':question_id,'ready':all(c['ok'] for c in checks),'checks':checks}

@app.patch('/api/questions/{question_id}',dependencies=[Depends(require_admin)])
def patch_question(question_id:int,p:QuestionPatch):
    with connect() as con:
        q=con.execute('SELECT * FROM questions WHERE id=%s',(question_id,)).fetchone()
        if not q:raise HTTPException(404,'Question not found')
        vals=p.model_dump(exclude_none=True)
        if p.approved is True:
            readiness=question_quality_check(question_id)
            if not readiness['ready']:
                raise HTTPException(409,{'message':'السؤال لم يجتز بوابة الجودة','checks':readiness['checks']})
            qa=con.execute("SELECT reason_code,severity,details FROM question_review_notes WHERE question_id=%s AND status='open'",(question_id,)).fetchone()
            if qa: raise HTTPException(409,{'message':'السؤال عليه ملاحظة QA مفتوحة','qa':qa})
        if not vals:return q
        sets=[];params=[]
        for k,v in vals.items():sets.append(f'{k}=%s');params.append(v)
        params.append(question_id)
        return con.execute('UPDATE questions SET '+','.join(sets)+' WHERE id=%s RETURNING *',params).fetchone()

@app.post('/api/documents/{document_id}/questions/manual',dependencies=[Depends(require_admin)])
def create_manual_question(document_id:int,p:ManualQuestionCreate):
    with connect() as con:
        doc=con.execute('SELECT id,subject_id,grade_level_id,curriculum_version_id,term_id FROM documents WHERE id=%s',(document_id,)).fetchone()
        if not doc:raise HTTPException(404,'Document not found')
        if not con.execute('SELECT 1 FROM document_pages WHERE document_id=%s AND page_number=%s',(document_id,p.page)).fetchone():raise HTTPException(400,'Page not found in document')
        vals={'subject_id':p.subject_id or doc['subject_id'],'grade_level_id':p.grade_level_id or doc['grade_level_id'],'curriculum_version_id':p.curriculum_version_id or doc['curriculum_version_id'],'term_id':p.term_id or doc['term_id']}
        return con.execute("""INSERT INTO questions(document_id,page,source_page,text_verbatim,question_type,difficulty,lesson_id,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id,approved)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE) RETURNING *""",(document_id,p.page,p.page,p.text_verbatim,p.question_type,p.difficulty,p.lesson_id,vals['subject_id'],vals['grade_level_id'],vals['curriculum_version_id'],vals['term_id'],p.unit_id)).fetchone()

@app.post('/api/documents/{document_id}/detect-questions',dependencies=[Depends(require_admin)])
def detect_questions(document_id:int):
    with connect() as con:
        doc=con.execute('SELECT id FROM documents WHERE id=%s',(document_id,)).fetchone()
        if not doc:raise HTTPException(404,'Document not found')
        pages=list(con.execute('SELECT page_number,extracted_text FROM document_pages WHERE document_id=%s ORDER BY page_number',(document_id,)).fetchall())
        count=0
        for p in pages:
            for text in detect_verbatim_question_candidates(p['extracted_text'] or ''):
                try:
                    con.execute("""INSERT INTO questions(document_id,page,source_page,text_verbatim,approved)
                      VALUES(%s,%s,%s,%s,FALSE)""",(document_id,p['page_number'],p['page_number'],text));count+=1
                except UniqueViolation: con.rollback()
        return {'detected':count}

@app.get('/api/documents/{document_id}/file',dependencies=[Depends(require_admin)])
def document_file(document_id:int):
    with connect() as con:
        r=con.execute('SELECT f.object_key,d.filename FROM document_files f JOIN documents d ON d.id=f.document_id WHERE f.document_id=%s',(document_id,)).fetchone()
    if not r:raise HTTPException(404,'File not found')
    return Response(get_bytes(r['object_key']),media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="source.pdf"'})

@app.get('/api/documents/{document_id}/page/{page}/preview',dependencies=[Depends(require_admin)])
def page_preview(document_id:int,page:int):
    with connect() as con:
        r=con.execute('SELECT preview_object_key FROM document_pages WHERE document_id=%s AND page_number=%s',(document_id,page)).fetchone()
        if not r:raise HTTPException(404,'Page not found')
        if r['preview_object_key']:
            return Response(get_bytes(r['preview_object_key']),media_type='image/jpeg',headers={'Cache-Control':'private,max-age=300'})
        f=con.execute('SELECT object_key FROM document_files WHERE document_id=%s',(document_id,)).fetchone()
    if not f:raise HTTPException(404,'PDF file not found')
    raw=get_bytes(f['object_key']);pdf=fitz.open(stream=raw,filetype='pdf')
    if page<1 or page>pdf.page_count:pdf.close();raise HTTPException(404,'Page out of range')
    pix=pdf.load_page(page-1).get_pixmap(matrix=fitz.Matrix(1.4,1.4),alpha=False);image=pix.tobytes('jpeg',jpg_quality=78);pdf.close()
    key=f'previews/{document_id}/page-{page}.jpg';put_bytes(key,image,'image/jpeg')
    with connect() as con:con.execute('UPDATE document_pages SET preview_object_key=%s WHERE document_id=%s AND page_number=%s',(key,document_id,page))
    return Response(image,media_type='image/jpeg',headers={'Cache-Control':'private,max-age=300'})

@app.get('/api/documents/{document_id}/file-url',dependencies=[Depends(require_admin)])
def document_file_url(document_id:int):
    with connect() as con:r=con.execute('SELECT object_key FROM document_files WHERE document_id=%s',(document_id,)).fetchone()
    if not r:raise HTTPException(404,'File not found')
    return {'url':presigned_get(r['object_key'],900)}

@app.post('/api/documents/upload',dependencies=[Depends(require_admin)])
async def upload_document(file:UploadFile=File(...),source_kind:str=Form('questions'),notes:str|None=Form(None),subject_id:int|None=Form(None),grade_level_id:int|None=Form(None),curriculum_version_id:int|None=Form(None),term_id:int|None=Form(None)):
    raw=await file.read()
    if not raw:raise HTTPException(400,'Empty file')
    if len(raw)>30*1024*1024:raise HTTPException(413,'PDF too large (30 MB max)')
    if not raw.startswith(b'%PDF'):raise HTTPException(415,'PDF only')
    allowed={'questions','answers','lesson','explanation','textbook','notes','mixed'}
    if source_kind not in allowed:raise HTTPException(400,'Invalid source_kind')
    fn=(file.filename or 'source.pdf').strip()[:250]
    sha=hashlib.sha256(raw).hexdigest()
    with connect() as con:
        ex=con.execute('SELECT id FROM documents WHERE sha256=%s',(sha,)).fetchone()
        if ex:return {'document_id':ex['id'],'duplicate':True}
    try: pages=extract_pages(raw)
    except Exception as e:raise HTTPException(400,'Cannot parse PDF') from e
    key=f'documents/{sha}.pdf';put_bytes(key,raw,'application/pdf')
    with connect() as con:
        d=con.execute("""INSERT INTO documents(filename,sha256,status,notes,source_kind,subject_id,grade_level_id,curriculum_version_id,term_id)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(fn,sha,'uploaded',notes,source_kind,subject_id,grade_level_id,curriculum_version_id,term_id)).fetchone()
        con.execute('INSERT INTO document_files(document_id,object_key,file_size_bytes,page_count) VALUES(%s,%s,%s,%s)',(d['id'],key,len(raw),len(pages)))
        for pno,text in pages:
            con.execute('INSERT INTO document_pages(document_id,page_number,extracted_text,text_sha256) VALUES(%s,%s,%s,%s)',(d['id'],pno,text,hashlib.sha256(text.encode()).hexdigest()))
        return {'document_id':d['id'],'pages':len(pages),'duplicate':False}

@app.post('/api/documents/register-external',dependencies=[Depends(require_admin)])
def register_external_document(filename:str,storage_url:str,sha256:str,source_kind:str='questions',notes:str|None=None,subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None,term_id:int|None=None):
    allowed={'questions','answers','lesson','explanation','textbook','notes','mixed'}
    if source_kind not in allowed: raise HTTPException(400,'Invalid source_kind')
    if not (storage_url.startswith('https://') or storage_url.startswith('s3://')): raise HTTPException(400,'Use HTTPS or s3 URL')
    with connect() as con:
        ex=con.execute('SELECT id FROM documents WHERE sha256=%s',(sha256,)).fetchone()
        if ex:return {'document_id':ex['id'],'duplicate':True}
        d=con.execute("""INSERT INTO documents(filename,sha256,status,notes,source_kind,storage_url,subject_id,grade_level_id,curriculum_version_id,term_id)
          VALUES(%s,%s,'external_registered',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",(filename[:250],sha256,notes,source_kind,storage_url,subject_id,grade_level_id,curriculum_version_id,term_id)).fetchone()
        return {'document_id':d['id'],'duplicate':False,'storage_url':storage_url}

@app.post('/api/documents/{document_id}/ingest-external',dependencies=[Depends(require_admin)])
def ingest_external(document_id:int):
    with connect() as con:doc=con.execute('SELECT id,storage_url FROM documents WHERE id=%s',(document_id,)).fetchone()
    if not doc:raise HTTPException(404,'Document not found')
    if not doc['storage_url']:raise HTTPException(400,'Document has no external URL')
    import urllib.request
    try:
        req=urllib.request.Request(doc['storage_url'],headers={'User-Agent':'PhysicsEduAgent/1.0'})
        raw=urllib.request.urlopen(req,timeout=25).read(30*1024*1024+1)
    except Exception as e:raise HTTPException(502,'Cannot download external PDF') from e
    if len(raw)>30*1024*1024:raise HTTPException(413,'External PDF too large')
    if not raw.startswith(b'%PDF'):raise HTTPException(415,'External source is not PDF')
    pages=extract_pages(raw);key=f'documents/{hashlib.sha256(raw).hexdigest()}.pdf';put_bytes(key,raw,'application/pdf')
    with connect() as con:
        con.execute('INSERT INTO document_files(document_id,object_key,file_size_bytes,page_count) VALUES(%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE SET object_key=excluded.object_key,file_size_bytes=excluded.file_size_bytes,page_count=excluded.page_count',(document_id,key,len(raw),len(pages)))
        con.execute('DELETE FROM document_pages WHERE document_id=%s',(document_id,))
        for pno,text in pages:con.execute('INSERT INTO document_pages(document_id,page_number,extracted_text,text_sha256) VALUES(%s,%s,%s,%s)',(document_id,pno,text,hashlib.sha256(text.encode()).hexdigest()))
        con.execute("UPDATE documents SET status='ingested' WHERE id=%s",(document_id,))
    return {'document_id':document_id,'pages':len(pages),'stored':True}

@app.get('/api/documents/{document_id}/download',dependencies=[Depends(require_admin)])
def download_document(document_id:int):
    with connect() as con:r=con.execute('SELECT f.object_key,d.filename FROM document_files f JOIN documents d ON d.id=f.document_id WHERE f.document_id=%s',(document_id,)).fetchone()
    if not r:raise HTTPException(404,'File not found')
    return Response(get_bytes(r['object_key']),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{r["filename"]}"'})

@app.get('/api/settings',dependencies=[Depends(require_admin)])
def settings():
    with connect() as con:return list(con.execute('SELECT key,value FROM settings ORDER BY key').fetchall())

@app.get('/api/health/db')
def db_health():
    with connect() as con:return {'ok':bool(con.execute('SELECT 1').fetchone())}

@app.get('/api/admin/session')
def admin_session(request:Request):return {'authenticated':admin_session_valid(request)}

@app.get('/api/student/subjects')
def student_subjects():
    with connect() as con:return list(con.execute('SELECT id,name_ar,code FROM subjects WHERE active=TRUE ORDER BY sort_order,id').fetchall())
