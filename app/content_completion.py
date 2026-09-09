from __future__ import annotations

import hashlib
import re
import urllib.request
import uuid

import fitz
from fastapi import Depends, Form, HTTPException
from fastapi.responses import HTMLResponse

from .corpus_public_status import current_curriculum_phase2_status
from .db import connect
from .main import app
from .security import require_admin
from .services.storage import BUCKET, delete_object, get_bytes, put_bytes, storage_configured


EXPLANATORY_KINDS = ('lesson', 'explanation', 'textbook', 'notes')
_MAX_SOURCE_BYTES = 90 * 1024 * 1024
_DRIVE_FILE_RE = re.compile(r'^https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)/')


def _gate_state(
    total_lessons: int,
    covered_lessons: int,
    open_qa_total: int,
    visual_pending: int,
    mismatches: int,
) -> dict:
    """Compute strict curriculum-content completion without weakening any human review gate."""
    total = max(int(total_lessons or 0), 0)
    covered = min(max(int(covered_lessons or 0), 0), total)
    uncovered = max(total - covered, 0)
    source_complete = total > 0 and uncovered == 0
    qa_complete = int(open_qa_total or 0) == 0
    return {
        'total_lessons': total,
        'covered_lessons': covered,
        'uncovered_lessons': uncovered,
        'explanatory_coverage_complete': source_complete,
        'open_qa_total': max(int(open_qa_total or 0), 0),
        'visual_transcription_required': max(int(visual_pending or 0), 0),
        'source_candidate_mismatch': max(int(mismatches or 0), 0),
        'question_review_complete': qa_complete,
        'content_complete': bool(source_complete and qa_complete),
    }


def _read_content_rows() -> dict:
    """Read current-curriculum source coverage and mapping details without mutating durable state."""
    with connect() as con:
        curriculum = con.execute(
            '''SELECT id,subject_id,grade_level_id,academic_year
               FROM curriculum_versions
               WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE
               ORDER BY id DESC LIMIT 1'''
        ).fetchone()
        if not curriculum:
            return {'curriculum': None, 'terms': [], 'lessons': [], 'mappings': [], 'documents': []}

        curriculum_id = int(curriculum['id'])
        terms = list(con.execute(
            '''SELECT id,term_number,name_ar FROM academic_terms
               WHERE curriculum_version_id=%s ORDER BY sort_order,term_number,id''',
            (curriculum_id,),
        ).fetchall())
        lessons = list(con.execute(
            '''SELECT l.id,l.title,l.chapter,l.term_id,l.unit_id,l.sort_order,
                      count(q.id) questions,
                      count(q.id) FILTER (WHERE q.approved=TRUE) approved_questions
               FROM lessons l
               LEFT JOIN questions q
                 ON q.lesson_id=l.id AND q.curriculum_version_id=l.curriculum_version_id
               WHERE l.curriculum_version_id=%s
               GROUP BY l.id,l.title,l.chapter,l.term_id,l.unit_id,l.sort_order
               ORDER BY l.sort_order,l.id''',
            (curriculum_id,),
        ).fetchall())
        mappings = list(con.execute(
            '''SELECT m.id,m.document_id,m.lesson_id,m.start_page,m.end_page,m.mapping_status,
                      m.confidence,m.notes,d.filename,d.kind,d.status document_status,
                      d.subject_id,d.grade_level_id,d.curriculum_version_id,d.term_id,
                      l.subject_id lesson_subject_id,l.grade_level_id lesson_grade_level_id,
                      l.curriculum_version_id lesson_curriculum_version_id,l.term_id lesson_term_id,
                      CASE
                        WHEN m.start_page >= 1 AND m.end_page >= m.start_page
                         AND (SELECT count(*)
                              FROM document_pages p
                              WHERE p.document_id=m.document_id
                                AND p.page_number BETWEEN m.start_page AND m.end_page
                                AND p.extracted_text IS NOT NULL
                                AND btrim(p.extracted_text)<>'') = (m.end_page-m.start_page+1)
                        THEN TRUE ELSE FALSE
                      END mapping_pages_ready
               FROM lesson_source_mappings m
               JOIN documents d ON d.id=m.document_id
               JOIN lessons l ON l.id=m.lesson_id
               WHERE l.curriculum_version_id=%s AND d.kind = ANY(%s)
               ORDER BY l.sort_order,l.id,m.start_page,m.id''',
            (curriculum_id, list(EXPLANATORY_KINDS)),
        ).fetchall())
        documents = list(con.execute(
            '''SELECT d.id,d.filename,d.kind,d.status,d.term_id,
                      f.page_count,f.file_size_bytes,f.file_sha256,
                      count(p.page_number) extracted_pages,
                      count(p.page_number) FILTER (
                        WHERE p.extracted_text IS NOT NULL AND btrim(p.extracted_text)<>''
                      ) nonblank_pages,
                      max(p.page_number) last_extracted_page,
                      (SELECT min(g.page_number)
                       FROM generate_series(1,COALESCE(f.page_count,0)) AS g(page_number)
                       WHERE NOT EXISTS (
                         SELECT 1 FROM document_pages missing
                         WHERE missing.document_id=d.id
                           AND missing.page_number=g.page_number
                       )) first_missing_page
               FROM documents d
               LEFT JOIN document_files f ON f.document_id=d.id
               LEFT JOIN document_pages p ON p.document_id=d.id
               WHERE d.curriculum_version_id=%s AND d.kind = ANY(%s)
               GROUP BY d.id,d.filename,d.kind,d.status,d.term_id,
                        f.page_count,f.file_size_bytes,f.file_sha256
               ORDER BY d.id DESC''',
            (curriculum_id, list(EXPLANATORY_KINDS)),
        ).fetchall())
        unclassified = con.execute(
            '''SELECT count(*) c FROM documents
               WHERE curriculum_version_id IS NULL OR term_id IS NULL
                  OR subject_id IS NULL OR grade_level_id IS NULL'''
        ).fetchone()['c']

    return {
        'curriculum': dict(curriculum),
        'terms': [dict(x) for x in terms],
        'lessons': [dict(x) for x in lessons],
        'mappings': [dict(x) for x in mappings],
        'documents': [dict(x) for x in documents],
        'unclassified_documents': int(unclassified or 0),
    }


def content_completion_snapshot(*, corpus_snapshot: dict | None = None) -> dict:
    """Return the exact remaining source and question-review gates for current-curriculum completion."""
    rows = _read_content_rows()
    curriculum = rows.get('curriculum')
    if not curriculum:
        return {
            'active': False,
            'content_complete': False,
            'reason': 'current_curriculum_not_configured',
            'policy': {
                'no_scientific_content_is_invented': True,
                'no_source_or_question_is_auto_approved': True,
            },
        }

    corpus = corpus_snapshot if corpus_snapshot is not None else current_curriculum_phase2_status()
    qa_rows = corpus.get('qa_open_by_reason') or []
    qa_by_reason = {str(x.get('reason_code') or ''): int(x.get('total') or 0) for x in qa_rows}
    open_qa_total = sum(qa_by_reason.values())
    visual_pending = qa_by_reason.get('visual_transcription_required', 0)
    mismatches = qa_by_reason.get('source_candidate_mismatch', 0)

    valid_approved_by_lesson: dict[int, list[dict]] = {}
    mapping_rows: list[dict] = []
    for raw in rows['mappings']:
        mapping = dict(raw)
        context_match = (
            mapping.get('subject_id') == mapping.get('lesson_subject_id')
            and mapping.get('grade_level_id') == mapping.get('lesson_grade_level_id')
            and mapping.get('curriculum_version_id') == mapping.get('lesson_curriculum_version_id')
            and mapping.get('term_id') == mapping.get('lesson_term_id')
        )
        pages_ready = bool(mapping.get('mapping_pages_ready'))
        mapping['context_match'] = bool(context_match)
        mapping['pages_ready'] = pages_ready
        mapping_rows.append(mapping)
        if mapping.get('mapping_status') == 'approved' and context_match and pages_ready:
            valid_approved_by_lesson.setdefault(int(mapping['lesson_id']), []).append(mapping)

    lessons: list[dict] = []
    for raw in rows['lessons']:
        lesson = dict(raw)
        approved_sources = valid_approved_by_lesson.get(int(lesson['id']), [])
        lesson['approved_explanatory_sources'] = approved_sources
        lesson['approved_explanatory_mapping_count'] = len(approved_sources)
        lesson['covered'] = bool(approved_sources)
        lessons.append(lesson)

    covered = sum(1 for lesson in lessons if lesson['covered'])
    gates = _gate_state(len(lessons), covered, open_qa_total, visual_pending, mismatches)
    documents = []
    for raw in rows['documents']:
        document = dict(raw)
        page_count = int(document.get('page_count') or 0)
        first_missing = document.get('first_missing_page')
        document['next_extraction_page'] = (
            int(first_missing)
            if first_missing is not None
            else (page_count + 1 if page_count else 1)
        )
        document['extraction_complete'] = bool(page_count and int(document.get('extracted_pages') or 0) >= page_count)
        document['all_extracted_pages_nonblank'] = bool(
            page_count and int(document.get('nonblank_pages') or 0) >= page_count
        )
        documents.append(document)

    gate_rows = [
        {
            'id': 'approved_explanatory_source',
            'title': 'مصدر شرح معتمد لكل درس في المنهج الحالي',
            'ok': gates['explanatory_coverage_complete'],
            'count': gates['uncovered_lessons'],
            'owner': 'teacher',
        },
        {
            'id': 'visual_transcription_review',
            'title': 'مراجعة النسخ البصري من صور المصدر',
            'ok': visual_pending == 0,
            'count': visual_pending,
            'owner': 'teacher',
        },
        {
            'id': 'source_candidate_mismatch',
            'title': 'حسم حالات عدم تطابق السؤال مع المصدر',
            'ok': mismatches == 0,
            'count': mismatches,
            'owner': 'teacher',
        },
        {
            'id': 'all_question_qa',
            'title': 'لا توجد ملاحظات QA مفتوحة على أسئلة المنهج الحالي',
            'ok': open_qa_total == 0,
            'count': open_qa_total,
            'owner': 'teacher',
        },
    ]
    return {
        'active': True,
        'academic_year': curriculum.get('academic_year'),
        'curriculum_version_id': int(curriculum['id']),
        'content_complete': gates['content_complete'],
        'source_coverage': gates,
        'content_gates': gate_rows,
        'lessons': lessons,
        'documents': documents,
        'mappings': mapping_rows,
        'terms': rows['terms'],
        'qa_open_by_reason': qa_rows,
        'unclassified_documents': int(rows.get('unclassified_documents') or 0),
        'questions': corpus.get('questions') or {},
        'quizzes': corpus.get('quizzes') or {},
        'policy': {
            'pdf_source_is_authoritative': True,
            'each_lesson_requires_explicit_approved_page_range': True,
            'approved_ranges_require_all_pages_extracted_and_nonblank': True,
            'visual_suggestions_never_satisfy_human_review': True,
            'no_scientific_content_is_invented': True,
            'no_source_or_question_is_auto_approved_by_this_phase': True,
            'completion_requires_zero_open_question_qa': True,
        },
    }


def _drive_file_id(url: str) -> str:
    """Accept only canonical Google Drive file URLs for server-side source import."""
    match = _DRIVE_FILE_RE.match(str(url or '').strip())
    if not match:
        raise HTTPException(400, 'استخدم رابط Google Drive بصيغة /file/d/<id>/ فقط')
    return match.group(1)


def _download_drive_pdf(url: str) -> bytes:
    """Download one explicitly selected Drive PDF with a strict size and content check."""
    file_id = _drive_file_id(url)
    request = urllib.request.Request(
        f'https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t',
        headers={
            'User-Agent': 'Mozilla/5.0 PhysicsEduAgent/1.8',
            'Accept': 'application/pdf,application/octet-stream;q=0.9,*/*;q=0.1',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(_MAX_SOURCE_BYTES + 1)
    except Exception as exc:
        raise HTTPException(502, 'تعذر تنزيل ملف Google Drive المحدد') from exc
    if len(raw) > _MAX_SOURCE_BYTES:
        raise HTTPException(413, 'ملف المصدر يتجاوز حد 90 MB')
    if not raw.startswith(b'%PDF'):
        raise HTTPException(415, 'الرابط لم يرجع ملف PDF صالحًا')
    return raw


def _current_source_context(con, term_id: int) -> dict:
    """Resolve an explicitly selected term inside the active third-secondary physics curriculum."""
    row = con.execute(
        '''SELECT cv.id curriculum_version_id,cv.subject_id,cv.grade_level_id,
                  cv.academic_year,t.id term_id,t.name_ar term_name
           FROM curriculum_versions cv
           JOIN academic_terms t ON t.curriculum_version_id=cv.id
           WHERE cv.subject_id=1 AND cv.grade_level_id=6 AND cv.active=TRUE AND t.id=%s
           ORDER BY cv.id DESC LIMIT 1''',
        (term_id,),
    ).fetchone()
    if not row:
        raise HTTPException(409, 'الترم المحدد لا ينتمي للمنهج الحالي النشط')
    return dict(row)


def _cleanup_unlinked_upload(object_key: str) -> None:
    """Delete a failed unique staging object only when no document has committed it."""
    try:
        with connect() as con:
            linked = con.execute(
                'SELECT 1 FROM document_files WHERE object_key=%s LIMIT 1',
                (object_key,),
            ).fetchone()
        if not linked:
            delete_object(object_key)
    except Exception:
        return


def _store_explanatory_pdf(raw: bytes, filename: str, drive_url: str, kind: str, term_id: int) -> dict:
    """Store a teacher-selected explanatory PDF without creating or approving lesson mappings."""
    if kind not in EXPLANATORY_KINDS:
        raise HTTPException(400, 'نوع مصدر الشرح غير صالح')
    if not storage_configured():
        raise HTTPException(503, 'Object storage is not configured')
    try:
        with fitz.open(stream=raw, filetype='pdf') as pdf:
            page_count = int(pdf.page_count)
    except Exception as exc:
        raise HTTPException(415, 'تعذر فتح PDF المحدد') from exc
    if page_count < 1:
        raise HTTPException(400, 'PDF لا يحتوي صفحات')

    digest = hashlib.sha256(raw).hexdigest()
    with connect() as con:
        existing = con.execute(
            '''SELECT d.id,d.filename,d.kind,d.status,d.curriculum_version_id,d.term_id,
                      f.page_count,f.file_sha256
               FROM document_files f JOIN documents d ON d.id=f.document_id
               WHERE f.file_sha256=%s LIMIT 1''',
            (digest,),
        ).fetchone()
        if existing:
            return {'document': dict(existing), 'duplicate': True, 'auto_approved': False}
        context = _current_source_context(con, term_id)

    object_key = f'content-sources/{digest[:20]}-{uuid.uuid4().hex}.pdf'
    put_bytes(object_key, raw, 'application/pdf')
    duplicate = None
    created = None
    try:
        with connect() as con:
            context = _current_source_context(con, term_id)
            row = con.execute(
                '''INSERT INTO documents(
                     filename,subject,source_type,storage_url,kind,status,
                     subject_id,grade_level_id,curriculum_version_id,term_id
                   ) VALUES(%s,'physics','pdf',%s,%s,'source_review_required',%s,%s,%s,%s)
                   RETURNING id,filename,kind,status,curriculum_version_id,term_id''',
                (
                    filename.strip() or 'physics-source.pdf',
                    drive_url,
                    kind,
                    context['subject_id'],
                    context['grade_level_id'],
                    context['curriculum_version_id'],
                    context['term_id'],
                ),
            ).fetchone()
            linked = con.execute(
                '''INSERT INTO document_files(
                     document_id,bucket_name,object_key,content_type,file_sha256,file_size_bytes,page_count
                   ) VALUES(%s,%s,%s,'application/pdf',%s,%s,%s)
                   ON CONFLICT(file_sha256) DO NOTHING RETURNING document_id''',
                (row['id'], BUCKET, object_key, digest, len(raw), page_count),
            ).fetchone()
            if not linked:
                con.execute('DELETE FROM documents WHERE id=%s', (row['id'],))
                duplicate = con.execute(
                    '''SELECT d.id,d.filename,d.kind,d.status,d.curriculum_version_id,d.term_id,
                              f.page_count,f.file_sha256
                       FROM document_files f JOIN documents d ON d.id=f.document_id
                       WHERE f.file_sha256=%s LIMIT 1''',
                    (digest,),
                ).fetchone()
            else:
                created = dict(row)
                created['page_count'] = page_count
                created['file_sha256'] = digest
    except Exception:
        _cleanup_unlinked_upload(object_key)
        raise

    if duplicate:
        _cleanup_unlinked_upload(object_key)
        return {'document': dict(duplicate), 'duplicate': True, 'auto_approved': False}
    return {'document': created, 'duplicate': False, 'auto_approved': False}


def _extract_source_page_batch(document_id: int, start_page: int, max_pages: int) -> dict:
    """Extract a bounded text batch from the stored authoritative PDF while preserving page numbers."""
    start = max(int(start_page), 1)
    limit = min(max(int(max_pages), 1), 15)
    with connect() as con:
        row = con.execute(
            '''SELECT d.id,d.kind,f.object_key,f.page_count
               FROM documents d JOIN document_files f ON f.document_id=d.id
               WHERE d.id=%s''',
            (document_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, 'مصدر الشرح غير موجود')
    if row['kind'] not in EXPLANATORY_KINDS:
        raise HTTPException(409, 'الملف ليس مصدر شرح معتمد النوع')
    raw = get_bytes(str(row['object_key']))
    try:
        pdf = fitz.open(stream=raw, filetype='pdf')
    except Exception as exc:
        raise HTTPException(503, 'تعذر فتح PDF المخزن') from exc
    try:
        effective_page_count = int(row['page_count'] or pdf.page_count)
        if start > effective_page_count:
            return {'document_id': document_id, 'processed': 0, 'blank_pages': [], 'complete': True}
        end = min(effective_page_count, start + limit - 1)
        extracted: list[tuple[int, str, str | None]] = []
        blank_pages: list[int] = []
        for page_number in range(start, end + 1):
            text = str(pdf.load_page(page_number - 1).get_text('text') or '').strip()
            if not text:
                blank_pages.append(page_number)
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None
            extracted.append((page_number, text, digest))
    finally:
        pdf.close()

    with connect() as con:
        for page_number, text, digest in extracted:
            con.execute(
                '''INSERT INTO document_pages(document_id,page_number,extracted_text,text_sha256)
                   VALUES(%s,%s,%s,%s)
                   ON CONFLICT(document_id,page_number) DO UPDATE SET
                     extracted_text=excluded.extracted_text,text_sha256=excluded.text_sha256''',
                (document_id, page_number, text, digest),
            )
    return {
        'document_id': document_id,
        'processed': len(extracted),
        'start_page': start,
        'end_page': end,
        'next_page': end + 1 if end < effective_page_count else None,
        'blank_pages': blank_pages,
        'complete': end >= effective_page_count,
        'ocr_required': bool(blank_pages),
    }


@app.get('/api/admin/content-completion', dependencies=[Depends(require_admin)])
def content_completion_api():
    """Expose the strict current-curriculum content completion snapshot to administrators."""
    return content_completion_snapshot()


@app.post('/api/admin/content-completion/sources/drive', dependencies=[Depends(require_admin)])
def import_drive_explanatory_source(
    drive_url: str = Form(...),
    filename: str = Form('physics-source.pdf'),
    kind: str = Form('textbook'),
    term_id: int = Form(...),
):
    """Import a teacher-selected Drive PDF as a review-required explanatory source, never as approved content."""
    raw = _download_drive_pdf(drive_url)
    return _store_explanatory_pdf(raw, filename, drive_url, kind, term_id)


@app.post('/api/admin/content-completion/sources/{document_id}/extract', dependencies=[Depends(require_admin)])
def extract_explanatory_source(document_id: int, start_page: int = 1, max_pages: int = 10):
    """Extract one bounded page batch so the teacher can map and approve exact source ranges."""
    return _extract_source_page_batch(document_id, start_page, max_pages)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>اكتمال محتوى المنهج</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1180px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.muted{color:#667085}.row{display:flex;gap:7px;flex-wrap:wrap;align-items:center}input,select,button{font:inherit;padding:9px;border:1px solid #ccd2dd;border-radius:8px}input[type=text]{min-width:260px;flex:1}button{cursor:pointer}.primary{background:#172033;color:#fff}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:right}@media(max-width:700px){table{font-size:13px}.hide-sm{display:none}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/completion-audit">Completion Audit</a> · <a href="/admin/current-corpus">مراجعة الأسئلة</a> · <a href="/admin/lesson-studio/references">مكتبة مراجع Lesson Studio</a></div>
<div id=summary class=box>جارٍ تحميل حالة اكتمال المحتوى...</div>
<div class=box><h2>1) إدخال مصدر شرح من Google Drive</h2><p class=muted>هذه الخطوة تسجل الملف كمصدر يحتاج مراجعة فقط. لا تعتمد أي درس ولا سؤال تلقائيًا.</p><div class=row><input id=driveUrl type=text placeholder="https://drive.google.com/file/d/.../view"><input id=fileName type=text placeholder="اسم الملف"><select id=kind><option value=textbook>كتاب / textbook</option><option value=lesson>درس</option><option value=explanation>شرح</option><option value=notes>مذكرات</option></select><select id=term></select><button class=primary onclick=importDrive()>استيراد المصدر</button></div><div id=importMsg class=muted></div><p class=muted>للملفات القديمة غير المصنفة: <a href="/admin/document-recovery">فتح استعادة وتصنيف الملفات</a>.</p></div>
<div class=box><h2>2) مصادر الشرح الحالية واستخراج الصفحات</h2><div id=documents></div></div>
<div class=box><h2>3) ربط نطاقات الصفحات بالدروس واعتمادها يدويًا</h2><div id=mappingHelp class=muted>أنشئ mapping كمسودة أولًا، ثم اضغط اعتماد بعد مراجعة نطاق الصفحات.</div><div id=mappings></div></div>
<div class=box><h2>4) مراجعة الأسئلة البصرية</h2><div id=visual></div><div class=row><button onclick=batchSuggest()>تجهيز 5 اقتراحات من القصاصات الأصلية</button><a href="/admin/workflow?quality_issue=any">فتح مسار المراجعة البشرية</a></div><p class=muted>الاقتراح البصري Draft فقط ولا يغلق QA ولا يعتمد السؤال.</p></div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));let state=null;
async function api(url,opt={}){let r;try{r=await fetch(url,opt)}catch(err){throw new Error('تعذر الاتصال بالخادم')}if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=null;try{x=await r.json()}catch(err){}if(!r.ok)throw new Error(typeof x?.detail==='string'?x.detail:JSON.stringify(x?.detail||('HTTP '+r.status)));return x}
async function load(){try{state=await api('/api/admin/content-completion');render()}catch(err){if(err.message!=='auth')summary.innerHTML='<div class=bad>'+e(err.message)+'</div>'}}
function render(){if(!state.active){summary.innerHTML='<div class=bad>لا يوجد منهج حالي نشط.</div>';return}let c=state.source_coverage||{};summary.innerHTML='<h1>Final Curriculum Content Completion — '+e(state.academic_year)+'</h1><div class=grid><div class=card><b>تغطية مصادر الشرح</b><div class="'+(c.explanatory_coverage_complete?'ok':'warn')+'">'+e(c.covered_lessons)+' / '+e(c.total_lessons)+' درس</div></div><div class=card><b>Visual QA</b><div class="'+(c.visual_transcription_required?'warn':'ok')+'">'+e(c.visual_transcription_required)+' مفتوح</div></div><div class=card><b>Source mismatch</b><div class="'+(c.source_candidate_mismatch?'warn':'ok')+'">'+e(c.source_candidate_mismatch)+' مفتوح</div></div><div class=card><b>اكتمال المحتوى</b><div class="'+(state.content_complete?'ok':'warn')+'">'+(state.content_complete?'✅ مكتمل':'⚠️ بوابات بشرية مفتوحة')+'</div></div></div><h3>الدروس</h3><table><tr><th>الدرس</th><th>الأسئلة</th><th>مصدر شرح معتمد</th></tr>'+state.lessons.map(l=>'<tr><td>'+e(l.chapter||'')+' — '+e(l.title)+'</td><td>'+e(l.approved_questions)+' / '+e(l.questions)+'</td><td class="'+(l.covered?'ok':'warn')+'">'+(l.covered?'✅ '+e(l.approved_explanatory_mapping_count):'⚠️ غير مغطى')+'</td></tr>').join('')+'</table>';term.innerHTML=(state.terms||[]).map(t=>'<option value="'+t.id+'">'+e(t.name_ar)+'</option>').join('');renderDocs();renderMappings();visual.innerHTML='<b>visual_transcription_required:</b> '+e(c.visual_transcription_required)+' · <b>source_candidate_mismatch:</b> '+e(c.source_candidate_mismatch)+' · <b>كل QA المفتوح:</b> '+e(c.open_qa_total)}
function renderDocs(){let rows=state.documents||[];documents.innerHTML=rows.length?rows.map(d=>{let lessons=state.lessons.filter(l=>l.term_id==d.term_id);return '<div class=card><b>#'+d.id+' '+e(d.filename)+'</b> <span class=muted>'+e(d.kind)+' · '+e(d.status)+'</span><br><span class=muted>استخراج '+e(d.extracted_pages)+' / '+e(d.page_count||0)+' · صفحات بنص '+e(d.nonblank_pages)+'</span><div class=row><button onclick="extractDoc('+d.id+','+e(d.next_extraction_page||1)+')">استخراج 10 صفحات تالية</button><select id="lesson-'+d.id+'">'+lessons.map(l=>'<option value="'+l.id+'">'+e(l.title)+'</option>').join('')+'</select><input id="start-'+d.id+'" type=number min=1 placeholder="من صفحة"><input id="end-'+d.id+'" type=number min=1 placeholder="إلى صفحة"><button onclick="draftMap('+d.id+')">إنشاء ربط للمراجعة</button></div></div>'}).join(''):'<p class=warn>لا توجد مصادر شرح للمنهج الحالي بعد.</p>'}
function renderMappings(){let rows=state.mappings||[];mappings.innerHTML=rows.length?'<table><tr><th>الملف</th><th>الدرس</th><th>الصفحات</th><th>الحالة</th><th></th></tr>'+rows.map(m=>{let l=state.lessons.find(x=>x.id==m.lesson_id);return '<tr><td>'+e(m.filename)+'</td><td>'+e(l?.title||m.lesson_id)+'</td><td>'+e(m.start_page)+'–'+e(m.end_page)+'</td><td>'+e(m.mapping_status)+(m.context_match?'':' ⚠️ سياق غير متطابق')+(m.pages_ready?'':' ⚠️ صفحات غير مكتملة')+'</td><td>'+(m.mapping_status==='approved'&&m.context_match&&m.pages_ready?'✅':m.context_match&&m.pages_ready?'<button onclick="approveMap('+m.id+')">اعتماد يدوي</button>':'')+'</td></tr>'}).join('')+'</table>':'<p class=muted>لا توجد روابط صفحات بعد.</p>'}
async function importDrive(){let fd=new FormData();fd.append('drive_url',driveUrl.value.trim());fd.append('filename',fileName.value.trim()||'physics-source.pdf');fd.append('kind',kind.value);fd.append('term_id',term.value);importMsg.textContent='جارٍ تنزيل وحفظ المصدر...';try{let x=await api('/api/admin/content-completion/sources/drive',{method:'POST',body:fd});importMsg.className=x.duplicate?'warn':'ok';importMsg.textContent=x.duplicate?'الملف موجود بالفعل كمصدر #'+x.document.id:'تم تسجيل المصدر #'+x.document.id+' كمصدر يحتاج مراجعة. ابدأ استخراج الصفحات.';await load()}catch(err){importMsg.className='bad';importMsg.textContent=err.message}}
async function extractDoc(id,start){try{await api('/api/admin/content-completion/sources/'+id+'/extract?start_page='+encodeURIComponent(start)+'&max_pages=10',{method:'POST'});await load()}catch(err){alert(err.message)}}
async function draftMap(id){let lid=document.getElementById('lesson-'+id).value,s=Number(document.getElementById('start-'+id).value),en=Number(document.getElementById('end-'+id).value);if(!lid||!s||!en){alert('اختر الدرس وحدد بداية ونهاية الصفحات');return}try{await api('/api/admin/documents/'+id+'/lesson-source',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lesson_id:Number(lid),start_page:s,end_page:en})});await load()}catch(err){alert(err.message)}}
async function approveMap(id){if(!confirm('هل راجعت نطاق الصفحات وتريد اعتماد هذا الربط كمصدر شرح للدرس؟'))return;try{await api('/api/admin/lesson-sources/'+id+'/approve',{method:'POST'});await load()}catch(err){alert(err.message)}}
async function batchSuggest(){try{let x=await api('/api/admin/current-corpus/visual-review/batch-suggest?limit=5',{method:'POST'});alert('تم تجهيز '+e(x.processed)+' اقتراحات للمراجعة فقط');await load()}catch(err){alert(err.message)}}
load();
</script></main></html>'''


@app.get('/admin/content-completion', response_class=HTMLResponse)
def content_completion_page():
    """Render the administrator cockpit for finishing real-source curriculum content."""
    return PAGE
