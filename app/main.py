from __future__ import annotations

import hashlib
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
    init_db(); yield

app = FastAPI(title="Science Education Platform", version="0.13.0", lifespan=lifespan)

@app.middleware("http")
async def protect_admin_pages(request: Request, call_next):
    path=request.url.path
    if path.startswith("/admin") and path!="/admin/login" and not admin_session_valid(request):
        return RedirectResponse("/admin/login",status_code=307)
    return await call_next(request)

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
        out={t:con.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c'] for t in ('documents','questions','quizzes','students','attempts')}; out['approved_questions']=con.execute('SELECT COUNT(*) c FROM questions WHERE approved=TRUE').fetchone()['c']; out['review_documents']=con.execute("SELECT COUNT(*) c FROM documents WHERE status IN ('review_required','extraction_review_required')").fetchone()['c']; return out
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
    with connect() as con:return list(con.execute("SELECT d.*,f.page_count,f.file_size_bytes,(SELECT COUNT(*) FROM questions q WHERE q.document_id=d.id) question_count FROM documents d LEFT JOIN document_files f ON f.document_id=d.id ORDER BY d.id DESC").fetchall())
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
          EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
          EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
          EXISTS(SELECT 1 FROM lessons l WHERE l.id=q.lesson_id
            AND l.subject_id=q.subject_id AND l.grade_level_id=q.grade_level_id
            AND l.curriculum_version_id=q.curriculum_version_id AND l.term_id=q.term_id AND l.unit_id=q.unit_id) academic_consistent,
          NOT EXISTS(SELECT 1 FROM question_concepts qc JOIN concepts c ON c.id=qc.concept_id
            WHERE qc.question_id=q.id AND c.lesson_id IS DISTINCT FROM q.lesson_id) concept_consistent
          FROM questions q WHERE q.id=%s""",(question_id,)).fetchone()
    if not row: raise HTTPException(404,'Question not found')
    source_ready=bool(row['document_id'] and row['page_number'] and row['source_page_exists'] and row['asset_valid'])
    classified=bool(row['subject_id'] and row['grade_level_id'] and row['curriculum_version_id'] and row['term_id'] and row['unit_id'] and row['lesson_id'] and row['has_concept'] and row['has_skill'] and row['academic_consistent'] and row['concept_consistent'] and row['question_type']!='unknown' and row['difficulty']!='unclassified' and row['accepted_answer'] and str(row['accepted_answer']).strip())
    ready=source_ready and classified
    state='approved' if row['approved'] else ('reviewed' if ready else ('cropped' if row['asset_valid'] else 'draft'))
    return {**row,'ready_for_approval':ready,'workflow_state':state}

@app.get('/api/admin/questions/{question_id}/quality-check',dependencies=[Depends(require_admin)])
def question_quality_check(question_id:int):
    with connect() as con:
        q=con.execute("""SELECT q.*,
          EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) has_asset,
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
          ('source',q['document_id'] is not None and (q['source_page'] or q['page']) is not None,'المصدر والصفحة'),
          ('asset',bool(q['has_asset']),'القصاصة'),
          ('academic',all(q[k] is not None for k in ('subject_id','grade_level_id','curriculum_version_id','term_id','unit_id','lesson_id')) and bool(q['academic_consistent']),'التصنيف الأكاديمي'),
          ('concept',bool(q['has_concept']) and bool(q['concept_consistent']),'المفهوم'),
          ('skill',bool(q['has_skill']),'المهارة'),
          ('type',q['question_type'] not in (None,'unknown'),'نوع السؤال'),
          ('difficulty',q['difficulty'] not in (None,'unclassified'),'مستوى الصعوبة'),
          ('answer',bool(q['accepted_answer'] and str(q['accepted_answer']).strip()),'الإجابة المعتمدة'),
          ('answer_source',q['answer_document_id'] is None or q['answer_page'] is not None,'مصدر الإجابة'),
        ]
        items=[{'id':k,'label':label,'ok':bool(ok)} for k,ok,label in checks]
        passed=sum(1 for x in items if x['ok']); total=len(items)
        return {'question_id':question_id,'ready':passed==total,'score':passed,'total':total,
                'percent':round(passed*100/total),'checks':items,
                'approval_allowed':passed==total,'student_visible':False}

@app.get('/api/admin/questions/{question_id}/answer-provenance',dependencies=[Depends(require_admin)])
def answer_provenance(question_id:int):
    with connect() as con:
        row=con.execute("""SELECT q.id,q.accepted_answer,q.answer_verbatim,q.answer_document_id,q.answer_page,
          d.filename answer_source_filename,d.kind answer_source_kind
          FROM questions q LEFT JOIN documents d ON d.id=q.answer_document_id WHERE q.id=%s""",(question_id,)).fetchone()
        if not row: raise HTTPException(404,'Question not found')
        out=dict(row)
        out['answer_source_type']='pdf_source' if row['answer_document_id'] is not None and row['answer_page'] is not None else 'manual_review'
        out['student_visible']=False
        return out

@app.patch('/api/questions/{question_id}',dependencies=[Depends(require_admin)])
def patch_question(question_id:int,patch:QuestionPatch):
    values={k:v for k,v in patch.model_dump(exclude_unset=True).items() if k in {'approved','lesson_id','subject_id','grade_level_id','curriculum_version_id','term_id','unit_id','question_type','difficulty','accepted_answer','answer_verbatim','answer_document_id','answer_page'}}
    if not values:raise HTTPException(400,'No changes')
    if 'difficulty' in values and values['difficulty'] not in {'unclassified','easy','medium','hard'}: raise HTTPException(400,'Invalid difficulty')
    with connect() as con:
        current=con.execute("""SELECT id,document_id,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id,lesson_id
          FROM questions WHERE id=%s""",(question_id,)).fetchone()
        if not current: raise HTTPException(404,'Question not found')
        academic_keys={'subject_id','grade_level_id','curriculum_version_id','term_id','unit_id','lesson_id'}
        answer_source_keys={'answer_document_id','answer_page','answer_verbatim'}
        if answer_source_keys.intersection(values):
            aid=values.get('answer_document_id')
            apage=values.get('answer_page')
            if (aid is None) != (apage is None):
                raise HTTPException(400,'مصدر الإجابة يحتاج ملفًا ورقم صفحة معًا')
            if aid is not None:
                adoc=con.execute("""SELECT d.id,d.kind,d.subject_id,d.grade_level_id,d.curriculum_version_id,d.term_id
                  FROM documents d WHERE d.id=%s""",(aid,)).fetchone()
                if not adoc: raise HTTPException(400,'ملف مصدر الإجابة غير موجود')
                if adoc['kind'] not in ('answers','reference'):
                    raise HTTPException(400,'مصدر الإجابة يجب أن يكون مفتاح إجابة أو مرجعًا')
                if not con.execute("SELECT 1 FROM document_pages WHERE document_id=%s AND page_number=%s",(aid,apage)).fetchone():
                    raise HTTPException(400,'صفحة مصدر الإجابة غير موجودة')
                eff_ctx={k:values.get(k,current[k]) for k in ('subject_id','grade_level_id','curriculum_version_id','term_id')}
                bad=[k for k in eff_ctx if adoc[k] is not None and eff_ctx[k] is not None and adoc[k]!=eff_ctx[k]]
                if bad: raise HTTPException(400,{'message':'مصدر الإجابة لا يطابق سياق السؤال','fields':bad})
            if values.get('answer_verbatim') is not None and not str(values.get('answer_verbatim') or '').strip():
                values['answer_verbatim']=None
        if academic_keys.intersection(values):
            eff={k:values.get(k,current[k]) for k in academic_keys}
            if eff['curriculum_version_id']:
                cv=con.execute("SELECT subject_id,grade_level_id FROM curriculum_versions WHERE id=%s AND active=TRUE",(eff['curriculum_version_id'],)).fetchone()
                if not cv or (eff['subject_id'] and cv['subject_id']!=eff['subject_id']) or (eff['grade_level_id'] and cv['grade_level_id']!=eff['grade_level_id']):
                    raise HTTPException(400,'إصدار المنهج لا يطابق المادة والصف')
            if eff['term_id']:
                term=con.execute("SELECT curriculum_version_id FROM academic_terms WHERE id=%s",(eff['term_id'],)).fetchone()
                if not term or (eff['curriculum_version_id'] and term['curriculum_version_id']!=eff['curriculum_version_id']):
                    raise HTTPException(400,'الترم لا يطابق إصدار المنهج')
            if eff['unit_id']:
                unit=con.execute("SELECT term_id FROM units WHERE id=%s",(eff['unit_id'],)).fetchone()
                if not unit or (eff['term_id'] and unit['term_id']!=eff['term_id']):
                    raise HTTPException(400,'الوحدة لا تطابق الترم')
            if eff['lesson_id']:
                lesson=con.execute("""SELECT subject_id,grade_level_id,curriculum_version_id,term_id,unit_id
                  FROM lessons WHERE id=%s""",(eff['lesson_id'],)).fetchone()
                if not lesson: raise HTTPException(400,'الدرس غير موجود')
                mismatched=[k for k in ('subject_id','grade_level_id','curriculum_version_id','term_id','unit_id')
                            if eff[k] and lesson[k]!=eff[k]]
                if mismatched: raise HTTPException(400,{'message':'الدرس لا يطابق السياق الأكاديمي المختار','fields':mismatched})
            if current['document_id']:
                doc=con.execute("""SELECT subject_id,grade_level_id,curriculum_version_id,term_id
                  FROM documents WHERE id=%s""",(current['document_id'],)).fetchone()
                if doc:
                    mismatched=[k for k in ('subject_id','grade_level_id','curriculum_version_id','term_id')
                                if doc[k] is not None and eff[k] is not None and doc[k]!=eff[k]]
                    if mismatched: raise HTTPException(400,{'message':'تصنيف السؤال لا يطابق ملف المصدر','fields':mismatched})
        if values.get('approved') is True:
            gate=con.execute("""SELECT q.id,q.document_id,coalesce(q.source_page,q.page) page_number,q.subject_id,q.grade_level_id,q.curriculum_version_id,q.term_id,q.unit_id,q.lesson_id,q.question_type,q.difficulty,q.accepted_answer,
              EXISTS(SELECT 1 FROM document_pages p WHERE p.document_id=q.document_id AND p.page_number=coalesce(q.source_page,q.page)) source_page_exists,
              EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id AND a.document_id=q.document_id AND a.page_number=coalesce(q.source_page,q.page)) asset_valid,
              EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
              EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
              EXISTS(SELECT 1 FROM lessons l WHERE l.id=q.lesson_id
                AND l.subject_id=q.subject_id AND l.grade_level_id=q.grade_level_id
                AND l.curriculum_version_id=q.curriculum_version_id AND l.term_id=q.term_id AND l.unit_id=q.unit_id) academic_consistent,
              NOT EXISTS(SELECT 1 FROM question_concepts qc JOIN concepts c ON c.id=qc.concept_id
                WHERE qc.question_id=q.id AND c.lesson_id IS DISTINCT FROM q.lesson_id) concept_consistent
              FROM questions q WHERE q.id=%s""",(question_id,)).fetchone()
            if not gate: raise HTTPException(404,'Question not found')
            effective_subject=values.get('subject_id',gate['subject_id'])
            effective_grade=values.get('grade_level_id',gate['grade_level_id'])
            effective_curriculum=values.get('curriculum_version_id',gate['curriculum_version_id'])
            effective_term=values.get('term_id',gate['term_id'])
            effective_unit=values.get('unit_id',gate['unit_id'])
            effective_lesson=values.get('lesson_id',gate['lesson_id'])
            effective_type=values.get('question_type',gate['question_type'])
            effective_difficulty=values.get('difficulty',gate['difficulty'])
            effective_answer=values.get('accepted_answer',gate['accepted_answer'])
            effective_answer_doc=values.get('answer_document_id')
            effective_answer_page=values.get('answer_page')
            if effective_answer_doc is None and 'answer_document_id' not in values:
                src=con.execute("SELECT answer_document_id,answer_page FROM questions WHERE id=%s",(question_id,)).fetchone()
                effective_answer_doc=src['answer_document_id'];effective_answer_page=src['answer_page']
            missing=[]
            if not gate['document_id']: missing.append('document')
            if not gate['page_number']: missing.append('source_page')
            if not gate['source_page_exists']: missing.append('valid_source_page')
            if not gate['asset_valid']: missing.append('question_asset')
            if not effective_subject: missing.append('subject')
            if not effective_grade: missing.append('grade_level')
            if not effective_curriculum: missing.append('curriculum_version')
            if not effective_term: missing.append('term')
            if not effective_unit: missing.append('unit')
            if not effective_lesson: missing.append('lesson')
            if not gate['has_concept']: missing.append('concept')
            if not gate['has_skill']: missing.append('skill')
            if not gate['academic_consistent']: missing.append('academic_consistency')
            if not gate['concept_consistent']: missing.append('concept_consistency')
            if not effective_type or effective_type=='unknown': missing.append('question_type')
            if not effective_difficulty or effective_difficulty=='unclassified': missing.append('difficulty')
            if not effective_answer or not str(effective_answer).strip(): missing.append('accepted_answer')
            # Manual reviewer answers remain allowed, but sourced answers must be complete.
            if effective_answer_doc is not None and not effective_answer_page: missing.append('answer_source_page')
            if missing: raise HTTPException(409,{'message':'لا يمكن اعتماد السؤال قبل اكتمال المصدر والتصنيف','missing':missing})
        row=con.execute(f"UPDATE questions SET {', '.join(f'{k}=%s' for k in values)} WHERE id=%s RETURNING *",list(values.values())+[question_id]).fetchone()
        if not row:raise HTTPException(404,'Question not found')
        return row
@app.post('/api/documents/{document_id}/questions/manual',dependencies=[Depends(require_admin)])
def create_manual_question(document_id:int,payload:ManualQuestionCreate):
    text=payload.text_verbatim.strip()
    if payload.page<1 or not text:raise HTTPException(400,'Invalid page or empty question')
    if len(text)>50000:raise HTTPException(413,'Question text is too large')
    if payload.difficulty not in {'unclassified','easy','medium','hard'}: raise HTTPException(400,'Invalid difficulty')
    with connect() as con:
        doc=con.execute("""SELECT subject_id,grade_level_id,curriculum_version_id,term_id FROM documents WHERE id=%s""",(document_id,)).fetchone()
        if not doc: raise HTTPException(404,'Document not found')
        if not con.execute('SELECT 1 FROM document_pages WHERE document_id=%s AND page_number=%s',(document_id,payload.page)).fetchone():raise HTTPException(404,'Source page not found')
        supplied={"subject_id":payload.subject_id,"grade_level_id":payload.grade_level_id,
                  "curriculum_version_id":payload.curriculum_version_id,"term_id":payload.term_id}
        for k,v in supplied.items():
            if v is not None and doc[k] is not None and v!=doc[k]:
                raise HTTPException(400,{"message":"تصنيف السؤال اليدوي لا يطابق ملف المصدر","field":k})
        subject_id=payload.subject_id or doc["subject_id"]
        grade_level_id=payload.grade_level_id or doc["grade_level_id"]
        curriculum_version_id=payload.curriculum_version_id or doc["curriculum_version_id"]
        term_id=payload.term_id or doc["term_id"]
        unit_id=payload.unit_id
        lesson_id=payload.lesson_id
        if unit_id:
            unit=con.execute("""SELECT u.term_id,t.curriculum_version_id,c.subject_id,c.grade_level_id
              FROM units u JOIN academic_terms t ON t.id=u.term_id
              JOIN curriculum_versions c ON c.id=t.curriculum_version_id WHERE u.id=%s""",(unit_id,)).fetchone()
            if not unit or unit["term_id"]!=term_id or unit["curriculum_version_id"]!=curriculum_version_id or unit["subject_id"]!=subject_id or unit["grade_level_id"]!=grade_level_id:
                raise HTTPException(400,'الوحدة لا تطابق ملف المصدر والسياق الأكاديمي')
        if lesson_id:
            lesson=con.execute("""SELECT subject_id,grade_level_id,curriculum_version_id,term_id,unit_id
              FROM lessons WHERE id=%s""",(lesson_id,)).fetchone()
            if not lesson: raise HTTPException(400,'الدرس غير موجود')
            expected={"subject_id":subject_id,"grade_level_id":grade_level_id,"curriculum_version_id":curriculum_version_id,"term_id":term_id}
            bad=[k for k,v in expected.items() if v is not None and lesson[k]!=v]
            if unit_id is not None and lesson["unit_id"]!=unit_id: bad.append("unit_id")
            if bad: raise HTTPException(400,{"message":"الدرس لا يطابق السياق الأكاديمي لملف المصدر","fields":bad})
            if unit_id is None: unit_id=lesson["unit_id"]
        dup=con.execute('SELECT id FROM questions WHERE document_id=%s AND coalesce(source_page,page)=%s AND text_verbatim=%s LIMIT 1',(document_id,payload.page,payload.text_verbatim)).fetchone()
        if dup:raise HTTPException(409,f"هذا السؤال مسجل بالفعل برقم {dup['id']}")
        row=con.execute('INSERT INTO questions(document_id,page,source_page,text_verbatim,approved,question_type,lesson_id,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id,difficulty) VALUES (%s,%s,%s,%s,FALSE,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',(document_id,payload.page,payload.page,payload.text_verbatim,payload.question_type or 'unknown',lesson_id,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id,payload.difficulty)).fetchone();con.execute("UPDATE documents SET status='review_required' WHERE id=%s",(document_id,));return row
@app.post('/api/documents/upload',dependencies=[Depends(require_admin)])
async def upload_document(file:UploadFile=File(...),subject:str=Form(...),kind:str=Form('questions'),
    subject_id:int=Form(...),grade_level_id:int=Form(...),curriculum_version_id:int=Form(...),term_id:int=Form(...),
    unit_id:int|None=Form(None),lesson_id:int|None=Form(None)):
    if not storage_configured():raise HTTPException(503,'Object storage is not configured')
    if not file.filename or not file.filename.lower().endswith('.pdf'):raise HTTPException(400,'Only PDF files are accepted')
    if kind not in {'questions','answers','reference','lesson','explanation','textbook','notes'}:raise HTTPException(400,'Invalid document kind')
    with connect() as con:
        sub=con.execute("SELECT id,name_ar FROM subjects WHERE id=%s AND active=TRUE",(subject_id,)).fetchone()
        grade=con.execute("SELECT id,name_ar FROM grade_levels WHERE id=%s AND active=TRUE",(grade_level_id,)).fetchone()
        curriculum=con.execute("SELECT id,academic_year,subject_id,grade_level_id FROM curriculum_versions WHERE id=%s AND active=TRUE",(curriculum_version_id,)).fetchone()
        term=con.execute("SELECT id,name_ar FROM academic_terms WHERE id=%s",(term_id,)).fetchone()
        if not all((sub,grade,curriculum,term)): raise HTTPException(400,'Academic classification is incomplete or invalid')
        if curriculum["subject_id"]!=subject_id or curriculum["grade_level_id"]!=grade_level_id:
            raise HTTPException(400,'Curriculum does not match selected subject and grade')
        term_ctx=con.execute("SELECT curriculum_version_id FROM academic_terms WHERE id=%s",(term_id,)).fetchone()
        if not term_ctx or term_ctx["curriculum_version_id"]!=curriculum_version_id:
            raise HTTPException(400,'Term does not match selected curriculum')
        if unit_id and not con.execute("SELECT 1 FROM units WHERE id=%s AND term_id=%s",(unit_id,term_id)).fetchone():
            raise HTTPException(400,'Unit does not match selected academic context')
        if lesson_id and not con.execute("SELECT 1 FROM lessons WHERE id=%s AND subject_id=%s AND grade_level_id=%s AND curriculum_version_id=%s AND term_id=%s",(lesson_id,subject_id,grade_level_id,curriculum_version_id,term_id)).fetchone():
            raise HTTPException(400,'Lesson does not match selected academic context')
    raw=await file.read()
    if not raw or len(raw)>75*1024*1024:raise HTTPException(413,'Invalid PDF size')
    try:pdf=fitz.open(stream=raw,filetype='pdf');page_count=pdf.page_count;pdf.close()
    except Exception:raise HTTPException(400,'Invalid PDF')
    digest=hashlib.sha256(raw).hexdigest()
    with connect() as con:existing=con.execute('SELECT f.document_id,d.filename FROM document_files f JOIN documents d ON d.id=f.document_id WHERE f.file_sha256=%s LIMIT 1',(digest,)).fetchone()
    if existing:raise HTTPException(409,f"هذا الملف مرفوع بالفعل كمستند رقم {existing['document_id']}: {existing['filename']}")
    try:
        with connect() as con:
            doc_id=con.execute("""INSERT INTO documents(filename,subject,kind,status,subject_id,grade_level_id,curriculum_version_id,term_id)
              VALUES (%s,%s,%s,'processing',%s,%s,%s,%s) RETURNING id""",
              (file.filename,subject,kind,subject_id,grade_level_id,curriculum_version_id,term_id)).fetchone()['id'];pdf_key=f'documents/{doc_id}/{digest}.pdf';con.execute('INSERT INTO document_files(document_id,bucket_name,object_key,content_type,file_sha256,file_size_bytes,page_count) VALUES (%s,%s,%s,%s,%s,%s,%s)',(doc_id,BUCKET,pdf_key,'application/pdf',digest,len(raw),page_count))
    except UniqueViolation:raise HTTPException(409,'هذا الملف مرفوع بالفعل. تم منع إنشاء نسخة مكررة تلقائيًا.')
    with NamedTemporaryFile(suffix='.pdf',delete=False) as tmp:tmp.write(raw);path=Path(tmp.name)
    try:
        try:put_bytes(pdf_key,raw,'application/pdf')
        except Exception:
            with connect() as con:con.execute('DELETE FROM documents WHERE id=%s',(doc_id,))
            raise HTTPException(502,'تعذر حفظ الملف في التخزين. لم يتم تسجيل نسخة ناقصة ويمكن إعادة المحاولة.')
        added=0;page_rows=extract_pages(path)
        with connect() as con:
            for page_no,text in page_rows:
                th=hashlib.sha256(text.encode()).hexdigest() if text else None;con.execute('INSERT INTO document_pages(document_id,page_number,extracted_text,text_sha256,preview_object_key) VALUES (%s,%s,%s,%s,NULL)',(doc_id,page_no,text,th));cands=detect_verbatim_question_candidates(text) if kind=='questions' else []
                for c in cands:con.execute('INSERT INTO questions(document_id,page,source_page,text_verbatim,approved,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id,lesson_id) VALUES (%s,%s,%s,%s,FALSE,%s,%s,%s,%s,%s,%s)',(doc_id,page_no,page_no,c,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id,lesson_id));added+=1
            status='review_required' if added else ('extraction_review_required' if kind=='questions' else ('source_review_required' if kind in {'lesson','explanation','textbook','notes'} else 'uploaded'));con.execute('UPDATE documents SET status=%s WHERE id=%s',(status,doc_id))
        return {'document_id':doc_id,'candidate_questions_added':added,'status':status,'page_count':page_count,'sha256':digest,
                'academic_context':{'subject_id':subject_id,'grade_level_id':grade_level_id,'curriculum_version_id':curriculum_version_id,'term_id':term_id,'unit_id':unit_id,'lesson_id':lesson_id}}
    finally:path.unlink(missing_ok=True)
@app.post('/api/documents/{document_id}/reextract-questions',dependencies=[Depends(require_admin)])
def reextract_document_questions(document_id:int):
    with connect() as con:
        doc=con.execute("""SELECT d.id,d.kind,d.subject_id,d.grade_level_id,d.curriculum_version_id,d.term_id
          FROM documents d
          JOIN curriculum_versions cv ON cv.id=d.curriculum_version_id AND cv.active=TRUE
          JOIN academic_terms t ON t.id=d.term_id
          WHERE d.id=%s AND cv.subject_id=d.subject_id AND cv.grade_level_id=d.grade_level_id
            AND t.curriculum_version_id=d.curriculum_version_id""",(document_id,)).fetchone()
        if not doc:
            exists=con.execute("SELECT 1 FROM documents WHERE id=%s",(document_id,)).fetchone()
            if not exists: raise HTTPException(404,"Document not found")
            raise HTTPException(409,"سياق ملف المصدر غير متسق أكاديميًا؛ أصلح التصنيف قبل إعادة الاستخراج")
        if doc["kind"]!="questions": raise HTTPException(400,"هذا الملف ليس بنك أسئلة")
        missing=[k for k in ("subject_id","grade_level_id","curriculum_version_id","term_id") if not doc[k]]
        if missing: raise HTTPException(409,{"message":"اربط الملف بالمنهج أولًا","missing":missing})
        pages=list(con.execute("""SELECT page_number,extracted_text FROM document_pages
          WHERE document_id=%s ORDER BY page_number""",(document_id,)).fetchall())
        if not pages: raise HTTPException(409,"لا توجد صفحات مفهرسة لهذا الملف")
        added=0;duplicates=0;empty_pages=0
        for p in pages:
            text=p["extracted_text"] or ""
            if not text.strip():
                empty_pages+=1
                continue
            for candidate in detect_verbatim_question_candidates(text):
                dup=con.execute("""SELECT 1 FROM questions WHERE document_id=%s
                  AND coalesce(source_page,page)=%s AND text_verbatim=%s LIMIT 1""",
                  (document_id,p["page_number"],candidate)).fetchone()
                if dup:
                    duplicates+=1
                    continue
                con.execute("""INSERT INTO questions(document_id,page,source_page,text_verbatim,approved,
                  subject_id,grade_level_id,curriculum_version_id,term_id,question_type,difficulty)
                  VALUES(%s,%s,%s,%s,FALSE,%s,%s,%s,%s,'unknown','unclassified')""",
                  (document_id,p["page_number"],p["page_number"],candidate,
                   doc["subject_id"],doc["grade_level_id"],doc["curriculum_version_id"],doc["term_id"]))
                added+=1
        status="review_required" if added or con.execute("SELECT 1 FROM questions WHERE document_id=%s LIMIT 1",(document_id,)).fetchone() else "extraction_review_required"
        con.execute("UPDATE documents SET status=%s WHERE id=%s",(status,document_id))
        return {"document_id":document_id,"added":added,"duplicates_skipped":duplicates,
                "empty_pages":empty_pages,"status":status,"approval_state":"review_required",
                "source_context":{"subject_id":doc["subject_id"],"grade_level_id":doc["grade_level_id"],
                  "curriculum_version_id":doc["curriculum_version_id"],"term_id":doc["term_id"]}}

@app.get('/api/documents/{document_id}/page/{page}/preview',dependencies=[Depends(require_admin)])
def page_preview(document_id:int,page:int):
    with connect() as con:row=con.execute('SELECT p.preview_object_key,f.object_key FROM document_pages p JOIN document_files f ON f.document_id=p.document_id WHERE p.document_id=%s AND p.page_number=%s',(document_id,page)).fetchone()
    if not row:raise HTTPException(404,'Page not found')
    if row['preview_object_key']:return Response(get_bytes(row['preview_object_key']),media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})
    raw=get_bytes(row['object_key'])
    try:
        pdf=fitz.open(stream=raw,filetype='pdf');pix=pdf.load_page(page-1).get_pixmap(matrix=fitz.Matrix(1.45,1.45),alpha=False);preview=pix.tobytes('jpeg',jpg_quality=82);pdf.close()
    except Exception:raise HTTPException(500,'Unable to render page preview')
    pk=f'documents/{document_id}/pages/{page:04d}.jpg';put_bytes(pk,preview,'image/jpeg')
    with connect() as con:con.execute('UPDATE document_pages SET preview_object_key=%s WHERE document_id=%s AND page_number=%s',(pk,document_id,page))
    return Response(preview,media_type='image/jpeg',headers={'Cache-Control':'private, max-age=300'})
@app.get('/api/documents/{document_id}/pdf-url',dependencies=[Depends(require_admin)])
def pdf_url(document_id:int):
    with connect() as con:row=con.execute('SELECT object_key FROM document_files WHERE document_id=%s',(document_id,)).fetchone()
    if not row:raise HTTPException(404,'PDF unavailable')
    return {'url':presigned_get(row['object_key'],900),'expires_seconds':900}

DASH='''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>منصة العلوم التعليمية</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1100px;margin:auto;padding:24px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card{background:white;padding:18px;border-radius:16px;box-shadow:0 4px 20px #0001}a{color:#175cd3}</style><main><h1>منصة العلوم التعليمية</h1><p>منصة مبنية على مصادر PDF مع تتبع المصدر والصفحة.</p><div class="cards" id="cards"></div><p><a href="/admin">فتح لوحة الإدارة والمراجعة</a></p></main><script>fetch('/api/overview').then(r=>r.json()).then(x=>cards.innerHTML=Object.entries(x).map(([k,v])=>`<div class=card><b>${k}</b><h2>${v}</h2></div>`).join(''))</script></html>'''
ADMIN=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>إدارة بنك الأسئلة</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1300px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:15px;margin:12px 0;box-shadow:0 3px 14px #0000000a}.top{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.audit{display:grid;grid-template-columns:260px minmax(0,1fr) 360px;gap:12px}.qgrid{display:grid;grid-template-columns:360px 1fr;gap:12px}input,select,button,textarea{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}button{cursor:pointer}textarea{width:100%;min-height:190px;box-sizing:border-box}.doc,.q{padding:10px;border-bottom:1px solid #eee;cursor:pointer}.active{background:#eef4ff}.pagebar{display:flex;gap:8px;align-items:center;justify-content:center;margin:8px}.preview{width:100%;max-height:72vh;object-fit:contain;background:#eee;border-radius:10px}.raw{white-space:pre-wrap;direction:rtl;max-height:250px;overflow:auto;background:#f7f8fa;padding:10px;border-radius:8px}.muted{color:#667085;font-size:13px}@media(max-width:900px){.audit,.qgrid{grid-template-columns:1fr}.preview{max-height:none}}</style><main><h1>لوحة إدارة الفيزياء</h1><div class="box top"><input id=key type=password placeholder="ADMIN_API_KEY"><button onclick=saveKey()>حفظ المفتاح</button><select id=upSubject><option value="">المادة</option></select><select id=upGrade><option value="">الصف</option></select><select id=upCurriculum><option value="">المنهج</option></select><select id=upTerm><option value="">الترم</option></select><select id=upUnit><option value="">الوحدة (اختياري)</option></select><select id=upLesson><option value="">الدرس (اختياري)</option></select><select id=upKind><option value="questions">بنك أسئلة</option><option value="answers">مفتاح إجابة</option><option value="reference">شرح/مرجع</option></select><input id=pdf type=file accept="application/pdf"><button id=uploadBtn onclick=upload()>رفع PDF</button><span id=msg></span></div><div class=box><h2>مراجعة المصدر بصريًا</h2><p class=muted>الصفحة الأصلية هي المرجع. لا يتم تعديل نص السؤال علميًا؛ أي سؤال يُضاف يظل غير معتمد حتى مراجعته.</p><div class=audit><div><h3>المستندات</h3><div id=docs></div></div><div><div class=pagebar><button onclick="movePage(-1)">السابق</button><b id=pageLabel>—</b><button onclick="movePage(1)">التالي</button></div><img id=pageImg class=preview><div id=imgMsg class=muted></div><details><summary>النص الخام المستخرج من الصفحة</summary><pre id=rawText class=raw></pre></details></div><div><h3>إضافة سؤال من الصفحة</h3><textarea id=manualText placeholder="نص السؤال حرفيًا..."></textarea><select id=qtype><option value=unknown>غير مصنف</option><option value=mcq>اختيار من متعدد</option><option value=numeric>مسألة حسابية</option><option value=essay>مقالي</option></select><button onclick=saveManual()>حفظ كمرشح للمراجعة</button><div id=auditMsg></div></div></div></div><div class=qgrid><div class=box><h3>الأسئلة المرشحة</h3><div id=list></div></div><div class=box id=review>اختر سؤالًا للمراجعة</div></div></main><script>
let qs=[],documents=[],pages=[],selectedDoc=null,pageIndex=0,sel=null,academic=null;key.value=localStorage.pk||'';function h(){return {'X-Admin-Key':localStorage.pk||''}}function saveKey(){localStorage.pk=key.value;msg.textContent='تم حفظ المفتاح';loadAll()}function opts(el,rows,label,empty){el.innerHTML='<option value="">'+empty+'</option>'+rows.map(x=>'<option value="'+x.id+'">'+(x[label]||x.name||x.title)+'</option>').join('')}async function loadAcademic(){let r=await fetch('/api/academic/catalog');if(!r.ok){msg.textContent='تعذر تحميل الهيكل الأكاديمي';return}academic=await r.json();opts(upSubject,academic.subjects||[],'name_ar','المادة');opts(upGrade,academic.grades||[],'name_ar','الصف');filterCurricula()}function filterCurricula(){if(!academic)return;let sid=+upSubject.value||0,gid=+upGrade.value||0;let cs=(academic.curricula||[]).filter(x=>(!sid||x.subject_id==sid)&&(!gid||x.grade_level_id==gid));opts(upCurriculum,cs,'academic_year','المنهج');filterTerms()}function filterTerms(){if(!academic)return;let cid=+upCurriculum.value||0;let ts=(academic.terms||[]).filter(x=>!cid||x.curriculum_version_id==cid);opts(upTerm,ts,'name_ar','الترم');filterUnits()}function filterUnits(){if(!academic)return;let tid=+upTerm.value||0;let us=(academic.units||[]).filter(x=>!tid||x.term_id==tid);opts(upUnit,us,'title','الوحدة (اختياري)');loadUploadLessons()}async function loadUploadLessons(){let p=new URLSearchParams();if(upSubject.value)p.set('subject_id',upSubject.value);if(upGrade.value)p.set('grade_level_id',upGrade.value);if(upCurriculum.value)p.set('curriculum_version_id',upCurriculum.value);if(upTerm.value)p.set('term_id',upTerm.value);if(upUnit.value)p.set('unit_id',upUnit.value);let r=await fetch('/api/lessons?'+p.toString());let ls=r.ok?await r.json():[];opts(upLesson,ls,'title','الدرس (اختياري)')}upSubject.onchange=()=>{filterCurricula()};upGrade.onchange=()=>{filterCurricula()};upCurriculum.onchange=()=>{filterTerms()};upTerm.onchange=()=>{filterUnits()};upUnit.onchange=loadUploadLessons;async function authBlob(url){let r=await fetch(url,{headers:h(),cache:'no-store'});if(!r.ok){let x={};try{x=await r.json()}catch(e){}throw new Error(x.detail||`HTTP ${r.status}`)}return URL.createObjectURL(await r.blob())}async function setPreview(img,url){imgMsg.textContent='جارٍ تحميل الصفحة...';if(img.dataset.blob)URL.revokeObjectURL(img.dataset.blob);img.removeAttribute('src');try{let u=await authBlob(url);img.dataset.blob=u;img.src=u;imgMsg.textContent=''}catch(e){imgMsg.textContent='تعذر عرض الصفحة: '+e.message}}
async function loadAll(){await Promise.all([loadDocs(),loadQuestions()])}async function loadDocs(){documents=await fetch('/api/documents',{headers:h()}).then(r=>r.json());docs.innerHTML=documents.map(d=>`<div class="doc ${selectedDoc==d.id?'active':''}" onclick="pickDoc(${d.id})"><b>#${d.id} ${d.filename}</b><br><span class=muted>${d.page_count||0} صفحة · ${d.question_count||0} سؤال · ${d.status}</span></div>`).join('');if(!selectedDoc&&documents.length)pickDoc(documents[0].id)}async function pickDoc(id){selectedDoc=id;pageIndex=0;let r=await fetch(`/api/documents/${id}/pages`,{headers:h()});pages=r.ok?await r.json():[];await showPage();loadDocs()}async function showPage(){if(!selectedDoc||!pages.length){pageLabel.textContent='لا توجد صفحات';pageImg.removeAttribute('src');return}pageIndex=Math.max(0,Math.min(pageIndex,pages.length-1));let p=pages[pageIndex].page_number;pageLabel.textContent=`صفحة ${p} من ${pages.length}`;setPreview(pageImg,`/api/documents/${selectedDoc}/page/${p}/preview`);fetch(`/api/documents/${selectedDoc}/page/${p}/text`,{headers:h()}).then(r=>r.json()).then(x=>rawText.textContent=x.extracted_text||'').catch(()=>rawText.textContent='تعذر تحميل النص الخام')}function movePage(n){pageIndex+=n;showPage()}
async function saveManual(){if(!selectedDoc||!pages.length)return;let text=manualText.value;if(!text.trim()){auditMsg.textContent='أدخل نص السؤال أولًا';return}let p=pages[pageIndex].page_number,r=await fetch(`/api/documents/${selectedDoc}/questions/manual`,{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({page:p,text_verbatim:text,question_type:qtype.value})}),x=await r.json();auditMsg.textContent=r.ok?`تم حفظ السؤال #${x.id} كمرشح غير معتمد`:(x.detail||'حدث خطأ');if(r.ok){manualText.value='';await loadAll()}}
async function loadQuestions(){qs=await fetch('/api/questions?limit=500',{headers:h()}).then(r=>r.json());list.innerHTML=qs.length?qs.map(q=>`<div class=q onclick="pickQ(${q.id})">#${q.id} · ${q.source_filename} · صفحة ${q.source_page||q.page}<br>${q.text_verbatim.slice(0,140)}</div>`).join(''):'لا توجد أسئلة مرشحة حاليًا'}function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}function pickQ(id){sel=qs.find(x=>x.id==id);let p=sel.source_page||sel.page;review.innerHTML=`<h3>${sel.source_filename} — صفحة ${p}</h3><img id=qimg class=preview><div id=qimgMsg class=muted></div><pre class=raw>${esc(sel.text_verbatim)}</pre><input id=ans placeholder="الإجابة المعتمدة" value="${esc(sel.accepted_answer||'')}"><button onclick="patchQ(true)">اعتماد</button><button onclick="patchQ(false)">إلغاء الاعتماد</button><button onclick=openPdf()>فتح PDF</button>`;authBlob(`/api/documents/${sel.document_id}/page/${p}/preview`).then(u=>{qimg.src=u;qimg.dataset.blob=u}).catch(e=>qimgMsg.textContent='تعذر عرض الصفحة: '+e.message)}async function patchQ(v){await fetch('/api/questions/'+sel.id,{method:'PATCH',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({approved:v,accepted_answer:ans.value||null})});loadQuestions()}async function openPdf(){let r=await fetch(`/api/documents/${sel.document_id}/pdf-url`,{headers:h()}),x=await r.json();if(r.ok)window.open(x.url,'_blank')}async function upload(){let f=pdf.files[0];if(!f){msg.textContent='اختر ملف PDF أولًا';return}if(!upSubject.value||!upGrade.value||!upCurriculum.value||!upTerm.value){msg.textContent='اختر المادة والصف والمنهج والترم قبل الرفع';return}uploadBtn.disabled=true;try{let d=new FormData();d.append('file',f);d.append('kind',upKind.value);d.append('subject_id',upSubject.value);d.append('grade_level_id',upGrade.value);d.append('curriculum_version_id',upCurriculum.value);d.append('term_id',upTerm.value);if(upUnit.value)d.append('unit_id',upUnit.value);if(upLesson.value)d.append('lesson_id',upLesson.value);let sn=upSubject.options[upSubject.selectedIndex].text;d.append('subject',sn);let r=await fetch('/api/documents/upload',{method:'POST',headers:h(),body:d}),x=await r.json();msg.textContent=r.ok?`تم الرفع: ${x.candidate_questions_added} سؤال مرشح`:(x.detail||'خطأ');if(r.ok){selectedDoc=x.document_id;await loadAll()}}finally{uploadBtn.disabled=false}}loadAcademic();loadAll();</script></html>'''
@app.get('/',response_class=HTMLResponse)
def dashboard():return DASH
@app.get('/admin')
def admin(): return RedirectResponse('/admin/dashboard',status_code=307)
