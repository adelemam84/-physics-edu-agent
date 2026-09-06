from __future__ import annotations

import hashlib
import io
import json
import re
import uuid

import fitz
from fastapi import Depends, File, Form, HTTPException, UploadFile

from .db import connect
from .main import app
from .security import require_admin
from .services.storage import put_bytes, storage_configured

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
        con.execute('''CREATE TABLE IF NOT EXISTS science_reference_pages(
          id bigserial PRIMARY KEY,
          document_id uuid NOT NULL REFERENCES science_reference_documents(id) ON DELETE CASCADE,
          page_number integer NOT NULL,
          page_text text NOT NULL,
          UNIQUE(document_id,page_number)
        )''')
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
        docs = list(con.execute('''SELECT id,title,subject,grade_label,academic_year,page_count
          FROM science_reference_documents WHERE active=TRUE AND lower(subject)=lower(%s)
          AND (%s='' OR grade_label IS NULL OR grade_label='' OR lower(grade_label)=lower(%s))
          ORDER BY created_at DESC''', (subject, grade_label or '', grade_label or '')).fetchall())
        if not docs:
            return {'available': False, 'documents': [], 'pages': [], 'policy': 'reference_only_no_silent_rewrite'}
        doc_ids = [d['id'] for d in docs]
        pages = list(con.execute('''SELECT document_id,page_number,page_text FROM science_reference_pages
          WHERE document_id=ANY(%s)''', (doc_ids,)).fetchall())
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
        })
    ranked.sort(key=lambda x: (-x['score'], x['page_number']))
    return {
        'available': True,
        'documents': [dict(d) for d in docs],
        'pages': ranked[:limit],
        'policy': 'reference_only_no_silent_rewrite',
    }


@app.get('/api/admin/lesson-studio/references', dependencies=[Depends(require_admin)])
def list_science_references(subject: str | None = None):
    _schema()
    with connect() as con:
        if subject:
            rows = list(con.execute('''SELECT id,title,subject,grade_label,academic_year,filename,page_count,active,created_at
              FROM science_reference_documents WHERE lower(subject)=lower(%s) ORDER BY created_at DESC''', (subject,)).fetchall())
        else:
            rows = list(con.execute('''SELECT id,title,subject,grade_label,academic_year,filename,page_count,active,created_at
              FROM science_reference_documents ORDER BY subject,grade_label,created_at DESC''').fetchall())
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
        existing = con.execute('SELECT id,title,page_count FROM science_reference_documents WHERE sha256=%s', (digest,)).fetchone()
    if existing:
        return {'created': False, 'duplicate': True, 'reference': dict(existing)}
    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception as exc:
        raise HTTPException(422, 'PDF could not be parsed') from exc
    pages = []
    for i, page in enumerate(doc, 1):
        text = page.get_text('text').strip()
        pages.append((i, text))
    doc.close()
    if not any(text for _, text in pages):
        raise HTTPException(422, 'PDF contains no extractable text; scanned references need OCR ingestion')
    ref_id = str(uuid.uuid4())
    key = None
    if storage_configured():
        key = f'lesson-studio/references/{ref_id}.pdf'
        put_bytes(key, data, 'application/pdf')
    with connect() as con:
        con.execute('''INSERT INTO science_reference_documents(
          id,title,subject,grade_label,academic_year,filename,sha256,object_key,page_count)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (ref_id, title.strip(), subject.strip().lower(), grade_label.strip(), academic_year.strip(),
           file.filename or 'reference.pdf', digest, key, len(pages)))
        for page_no, text in pages:
            con.execute('INSERT INTO science_reference_pages(document_id,page_number,page_text) VALUES(%s,%s,%s)',
                        (ref_id, page_no, text))
    return {
        'created': True,
        'id': ref_id,
        'title': title.strip(),
        'subject': subject.strip().lower(),
        'grade_label': grade_label.strip(),
        'page_count': len(pages),
        'stored_original': bool(key),
        'role': 'scientific_reference_not_teacher_source',
    }


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
