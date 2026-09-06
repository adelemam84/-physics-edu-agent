from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid

import fitz
from fastapi import Depends, File, Form, HTTPException, UploadFile

from .db import connect
from .main import app
from .science_lesson_studio import _gemini_text
from .security import require_admin
from .services.storage import get_bytes, put_bytes, storage_configured

MAX_REFERENCE_BYTES = 100 * 1024 * 1024


def _schema() -> None:
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS science_reference_documents(
          id uuid PRIMARY KEY,
          title text NOT NULL,
          subject text NOT NULL,
          grade_label text,
          academic_year text,
          filename text NOT NULL,
          sha256 text NOT NULL UNIQUE,
          object_key text,
          page_count integer NOT NULL,
          active boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now()
        )''')
        con.execute('ALTER TABLE science_reference_documents ADD COLUMN IF NOT EXISTS ingestion_status text NOT NULL DEFAULT \'ready\'')
        con.execute('ALTER TABLE science_reference_documents ADD COLUMN IF NOT EXISTS extracted_pages integer NOT NULL DEFAULT 0')
        con.execute('''CREATE TABLE IF NOT EXISTS science_reference_pages(
          id bigserial PRIMARY KEY,
          document_id uuid NOT NULL REFERENCES science_reference_documents(id) ON DELETE CASCADE,
          page_number integer NOT NULL,
          page_text text NOT NULL,
          extraction_method text NOT NULL DEFAULT 'pdf_text',
          UNIQUE(document_id,page_number)
        )''')
        con.execute('ALTER TABLE science_reference_pages ADD COLUMN IF NOT EXISTS extraction_method text NOT NULL DEFAULT \'pdf_text\'')
        con.execute('CREATE INDEX IF NOT EXISTS idx_science_reference_subject ON science_reference_documents(subject,grade_label,active)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_science_reference_pages_doc ON science_reference_pages(document_id,page_number)')


def _normalize_tokens(text: str) -> set[str]:
    words = re.findall(r'[\w\u0600-\u06ff]+', (text or '').lower(), flags=re.UNICODE)
    stop = {'من','في','على','إلى','الى','عن','هو','هي','هذا','هذه','the','and','of','to','a','an'}
    return {w for w in words if len(w) > 2 and w not in stop}


def _score_page(query_tokens: set[str], page_text: str) -> float:
    if not query_tokens:
        return 0.0
    page_tokens = _normalize_tokens(page_text)
    if not page_tokens:
        return 0.0
    overlap = len(query_tokens & page_tokens)
    return overlap / max(1, len(query_tokens))


def reference_context(subject: str, grade_label: str, query: str, limit: int = 8) -> dict:
    _schema()
    limit = min(20, max(1, int(limit)))
    with connect() as con:
        docs = list(con.execute('''SELECT id,title,subject,grade_label,academic_year,page_count,ingestion_status,extracted_pages
          FROM science_reference_documents WHERE active=TRUE AND lower(subject)=lower(%s)
          AND (%s='' OR grade_label IS NULL OR grade_label='' OR lower(grade_label)=lower(%s))
          ORDER BY created_at DESC''', (subject, grade_label or '', grade_label or '')).fetchall())
        if not docs:
            return {'available': False, 'documents': [], 'pages': [], 'policy': 'reference_only_no_silent_rewrite'}
        doc_ids = [d['id'] for d in docs]
        pages = list(con.execute('''SELECT document_id,page_number,page_text,extraction_method FROM science_reference_pages
          WHERE document_id=ANY(%s) AND btrim(page_text)<>'' ''', (doc_ids,)).fetchall())
    tokens = _normalize_tokens(query)
    ranked = []
    title_by_id = {str(d['id']): d['title'] for d in docs}
    for p in pages:
        score = _score_page(tokens, p['page_text'])
        if score <= 0:
            continue
        ranked.append({
            'document_id': str(p['document_id']),
            'document_title': title_by_id.get(str(p['document_id']), ''),
            'page_number': int(p['page_number']),
            'score': round(score, 4),
            'text': p['page_text'],
            'extraction_method': p.get('extraction_method'),
        })
    ranked.sort(key=lambda x: (-x['score'], x['page_number']))
    return {
        'available': True,
        'documents': [dict(d) for d in docs],
        'pages': ranked[:limit],
        'policy': 'reference_only_no_silent_rewrite',
    }


def _refresh_ingestion_status(reference_id: str) -> dict:
    with connect() as con:
        row = con.execute('SELECT page_count FROM science_reference_documents WHERE id=%s', (reference_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Scientific reference not found')
        extracted = con.execute('''SELECT count(*) n FROM science_reference_pages
          WHERE document_id=%s AND btrim(page_text)<>'' '' ''', (reference_id,)).fetchone()['n']
        total = int(row['page_count'])
        status = 'ready' if int(extracted) >= total else ('partial_ocr' if int(extracted) > 0 else 'ocr_required')
        con.execute('UPDATE science_reference_documents SET ingestion_status=%s,extracted_pages=%s WHERE id=%s',
                    (status, int(extracted), reference_id))
    return {'ingestion_status': status, 'extracted_pages': int(extracted), 'page_count': total}


@app.get('/api/admin/lesson-studio/references', dependencies=[Depends(require_admin)])
def list_science_references(subject: str | None = None):
    _schema()
    with connect() as con:
        base = '''SELECT id,title,subject,grade_label,academic_year,filename,page_count,active,
          ingestion_status,extracted_pages,created_at FROM science_reference_documents'''
        if subject:
            rows = list(con.execute(base + ' WHERE lower(subject)=lower(%s) ORDER BY created_at DESC', (subject,)).fetchall())
        else:
            rows = list(con.execute(base + ' ORDER BY subject,grade_label,created_at DESC').fetchall())
    return {'references': [dict(x) for x in rows], 'role': 'scientific_reference_not_teacher_source'}


@app.post('/api/admin/lesson-studio/references', dependencies=[Depends(require_admin)])
async def upload_science_reference(
    file: UploadFile = File(...),
    title: str = Form(...),
    subject: str = Form(...),
    grade_label: str = Form(''),
    academic_year: str = Form(''),
):
    _schema()
    if file.content_type != 'application/pdf' and not (file.filename or '').lower().endswith('.pdf'):
        raise HTTPException(415, 'Scientific reference must be a PDF')
    data = await file.read(MAX_REFERENCE_BYTES + 1)
    if len(data) > MAX_REFERENCE_BYTES:
        raise HTTPException(413, 'Scientific reference exceeds 100 MB')
    if not data.startswith(b'%PDF'):
        raise HTTPException(415, 'Invalid PDF file')
    digest = hashlib.sha256(data).hexdigest()
    with connect() as con:
        existing = con.execute('SELECT id,title,page_count,ingestion_status,extracted_pages FROM science_reference_documents WHERE sha256=%s', (digest,)).fetchone()
    if existing:
        return {'created': False, 'duplicate': True, 'reference': dict(existing)}
    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception as exc:
        raise HTTPException(422, 'PDF could not be parsed') from exc
    pages = []
    for i, page in enumerate(doc, 1):
        pages.append((i, page.get_text('text').strip()))
    doc.close()
    ref_id = str(uuid.uuid4())
    key = None
    if storage_configured():
        key = f'lesson-studio/references/{ref_id}.pdf'
        put_bytes(key, data, 'application/pdf')
    extracted = sum(1 for _, text in pages if text)
    status = 'ready' if extracted == len(pages) else ('partial_ocr' if extracted else 'ocr_required')
    with connect() as con:
        con.execute('''INSERT INTO science_reference_documents(
          id,title,subject,grade_label,academic_year,filename,sha256,object_key,page_count,ingestion_status,extracted_pages)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (ref_id, title.strip(), subject.strip().lower(), grade_label.strip(), academic_year.strip(),
           file.filename or 'reference.pdf', digest, key, len(pages), status, extracted))
        for page_no, text in pages:
            con.execute('''INSERT INTO science_reference_pages(document_id,page_number,page_text,extraction_method)
              VALUES(%s,%s,%s,%s)''', (ref_id, page_no, text, 'pdf_text' if text else 'pending_ocr'))
    return {
        'created': True,
        'id': ref_id,
        'title': title.strip(),
        'subject': subject.strip().lower(),
        'grade_label': grade_label.strip(),
        'page_count': len(pages),
        'extracted_pages': extracted,
        'ingestion_status': status,
        'stored_original': bool(key),
        'ocr_available': bool(key),
        'role': 'scientific_reference_not_teacher_source',
    }


@app.post('/api/admin/lesson-studio/references/{reference_id}/ocr', dependencies=[Depends(require_admin)])
def ocr_scanned_reference_pages(reference_id: str, start_page: int = Form(1), max_pages: int = Form(3)):
    _schema()
    max_pages = min(5, max(1, int(max_pages)))
    with connect() as con:
        row = con.execute('''SELECT id,title,object_key,page_count FROM science_reference_documents WHERE id=%s''', (reference_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Scientific reference not found')
    if not row['object_key']:
        raise HTTPException(409, 'Original reference PDF is not available in object storage')
    data = get_bytes(row['object_key'])
    doc = fitz.open(stream=data, filetype='pdf')
    start = max(1, int(start_page))
    end = min(doc.page_count, start + max_pages - 1)
    processed = []
    for page_no in range(start, end + 1):
        with connect() as con:
            page_row = con.execute('SELECT page_text FROM science_reference_pages WHERE document_id=%s AND page_number=%s',
                                   (reference_id, page_no)).fetchone()
        if page_row and str(page_row['page_text'] or '').strip():
            processed.append({'page': page_no, 'status': 'already_extracted'})
            continue
        page = doc.load_page(page_no - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
        image = pix.tobytes('png')
        prompt = (
            f'هذه صفحة {page_no} من مرجع علمي معتمد. انقل النص العلمي الظاهر كما هو قدر الإمكان، '
            'مع الحفاظ على العناوين والمعادلات والرموز والوحدات. لا تلخص ولا تضف من المعرفة العامة. '
            'إذا كان جزء غير مقروء فاكتب [غير واضح].'
        )
        text = _gemini_text([
            {'text': prompt},
            {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(image).decode('ascii')}},
        ], 'أنت محرك OCR لمراجع علمية. المطلوب نسخ الصفحة فقط دون تفسير أو تصحيح أو إضافة.')
        with connect() as con:
            con.execute('''UPDATE science_reference_pages SET page_text=%s,extraction_method='gemini_page_ocr'
              WHERE document_id=%s AND page_number=%s''', (text.strip(), reference_id, page_no))
        processed.append({'page': page_no, 'status': 'ocr_extracted', 'chars': len(text.strip())})
    doc.close()
    state = _refresh_ingestion_status(reference_id)
    return {'reference_id': reference_id, 'processed': processed, **state, 'next_start_page': end + 1 if end < state['page_count'] else None}


@app.post('/api/admin/lesson-studio/references/{reference_id}/active', dependencies=[Depends(require_admin)])
def set_science_reference_active(reference_id: str, active: bool = Form(...)):
    _schema()
    with connect() as con:
        row = con.execute('SELECT id FROM science_reference_documents WHERE id=%s', (reference_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Scientific reference not found')
        con.execute('UPDATE science_reference_documents SET active=%s WHERE id=%s', (bool(active), reference_id))
    return {'id': reference_id, 'active': bool(active)}


@app.get('/api/admin/lesson-studio/reference-context', dependencies=[Depends(require_admin)])
def preview_science_reference_context(subject: str, grade_label: str = '', query: str = '', limit: int = 8):
    return reference_context(subject, grade_label, query, limit)
