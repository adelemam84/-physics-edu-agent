from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
from fastapi import Depends, HTTPException

from .db import connect
from .file_search_store import configured_store_name, ensure_store
from .main import app
from .research_engine import GEMINI_API_KEY
from .security import require_admin

MAX_INDEX_CHARS = 4_000_000


def _ensure_sync_table() -> None:
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS gemini_source_sync(
          document_id bigint PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
          store_name text NOT NULL,
          operation_name text,
          provider_document_name text,
          state text NOT NULL DEFAULT 'not_started',
          indexed_chars bigint NOT NULL DEFAULT 0,
          source_pages integer NOT NULL DEFAULT 0,
          source_sha256 text,
          error_detail text,
          synced_at timestamptz,
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_gemini_source_sync_state ON gemini_source_sync(state,updated_at DESC)")


def _document(document_id: int):
    with connect() as con:
        row = con.execute("""SELECT d.id,d.filename,d.status,d.subject_id,d.grade_level_id,d.curriculum_version_id,d.term_id,
          coalesce(f.sha256,'') source_sha256,
          (SELECT count(*) FROM document_pages p WHERE p.document_id=d.id) source_pages
          FROM documents d LEFT JOIN document_files f ON f.document_id=d.id
          WHERE d.id=%s""", (document_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Document not found')
    if not all((row['subject_id'], row['grade_level_id'], row['curriculum_version_id'], row['term_id'])):
        raise HTTPException(409, 'Document academic context is incomplete')
    return row


def build_index_text(document_id: int) -> tuple[str, int]:
    """Build a page-addressable text corpus for broad research.

    Visual/question review still uses exact PDF pages. File Search receives only
    extracted source text with explicit page markers, so broad RAG stays traceable
    without uploading large PDFs from a serverless function.
    """
    with connect() as con:
        pages = list(con.execute("""SELECT page_number,coalesce(extracted_text,'') extracted_text
          FROM document_pages WHERE document_id=%s ORDER BY page_number""", (document_id,)).fetchall())
    if not pages:
        raise HTTPException(409, 'Document has no extracted source pages')
    chunks=[]
    for p in pages:
        text=' '.join(str(p['extracted_text'] or '').split())
        if not text:
            continue
        chunks.append(f"[SOURCE_PAGE:{int(p['page_number'])}]\n{text}")
    corpus='\n\n'.join(chunks).strip()
    if not corpus:
        raise HTTPException(409, 'Document has no indexable source text')
    if len(corpus) > MAX_INDEX_CHARS:
        raise HTTPException(413, 'Extracted source text is too large for one indexing job')
    return corpus, len(pages)


def _metadata(doc) -> list[dict]:
    return [
        {'key':'document_id','numericValue':int(doc['id'])},
        {'key':'filename','stringValue':str(doc['filename'])[:500]},
        {'key':'curriculum_version_id','numericValue':int(doc['curriculum_version_id'])},
        {'key':'subject_id','numericValue':int(doc['subject_id'])},
        {'key':'grade_level_id','numericValue':int(doc['grade_level_id'])},
        {'key':'term_id','numericValue':int(doc['term_id'])},
        {'key':'source_policy','stringValue':'approved_project_source_only'},
    ]


def _start_resumable_upload(store_name: str, display_name: str, data: bytes, metadata: list[dict]) -> str:
    url=f'https://generativelanguage.googleapis.com/upload/v1beta/{store_name}:uploadToFileSearchStore'
    headers={
        'x-goog-api-key': GEMINI_API_KEY,
        'X-Goog-Upload-Protocol':'resumable',
        'X-Goog-Upload-Command':'start',
        'X-Goog-Upload-Header-Content-Length':str(len(data)),
        'X-Goog-Upload-Header-Content-Type':'text/plain; charset=utf-8',
        'Content-Type':'application/json',
    }
    body={
        'displayName': display_name[:512],
        'mimeType':'text/plain',
        'customMetadata':metadata,
        'chunkingConfig':{'whiteSpaceConfig':{'maxTokensPerChunk':800,'maxOverlapTokens':120}},
    }
    with httpx.Client(timeout=45) as client:
        response=client.post(url,headers=headers,json=body)
    if response.status_code >= 400:
        raise HTTPException(502, {'message':'Gemini resumable upload start failed','provider_status':response.status_code,'provider_detail':response.text[:500]})
    upload_url=response.headers.get('x-goog-upload-url','').strip()
    if not upload_url:
        raise HTTPException(502, 'Gemini did not return a resumable upload URL')
    return upload_url


def _finish_upload(upload_url: str, data: bytes) -> dict:
    headers={
        'Content-Length':str(len(data)),
        'X-Goog-Upload-Offset':'0',
        'X-Goog-Upload-Command':'upload, finalize',
        'Content-Type':'text/plain; charset=utf-8',
    }
    with httpx.Client(timeout=120) as client:
        response=client.post(upload_url,headers=headers,content=data)
    if response.status_code >= 400:
        raise HTTPException(502, {'message':'Gemini source upload failed','provider_status':response.status_code,'provider_detail':response.text[:500]})
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, 'Gemini source upload returned invalid JSON') from exc


def _save_sync(document_id: int, store_name: str, *, operation_name: str='', provider_document_name: str='', state: str, indexed_chars: int, source_pages: int, source_sha256: str='', error_detail: str='') -> None:
    _ensure_sync_table()
    synced_at = datetime.now(timezone.utc) if state == 'active' else None
    with connect() as con:
        con.execute("""INSERT INTO gemini_source_sync(document_id,store_name,operation_name,provider_document_name,state,indexed_chars,source_pages,source_sha256,error_detail,synced_at,updated_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
          ON CONFLICT(document_id) DO UPDATE SET store_name=excluded.store_name,operation_name=excluded.operation_name,
          provider_document_name=excluded.provider_document_name,state=excluded.state,indexed_chars=excluded.indexed_chars,
          source_pages=excluded.source_pages,source_sha256=excluded.source_sha256,error_detail=excluded.error_detail,
          synced_at=coalesce(excluded.synced_at,gemini_source_sync.synced_at),updated_at=now()""",
          (document_id,store_name,operation_name or None,provider_document_name or None,state,indexed_chars,source_pages,source_sha256 or None,error_detail or None,synced_at))


def sync_document(document_id: int) -> dict:
    if not GEMINI_API_KEY:
        raise HTTPException(503, 'GEMINI_API_KEY is not configured')
    doc=_document(document_id)
    store=ensure_store()['name'] if not configured_store_name() else configured_store_name()
    corpus,page_count=build_index_text(document_id)
    data=corpus.encode('utf-8')
    try:
        upload_url=_start_resumable_upload(store, str(doc['filename']), data, _metadata(doc))
        payload=_finish_upload(upload_url,data)
        operation_name=str(payload.get('name') or '')
        done=bool(payload.get('done'))
        response=payload.get('response') or {}
        provider_doc=str(response.get('document',{}).get('name') or response.get('name') or '')
        state='active' if done and not payload.get('error') else ('failed' if payload.get('error') else 'processing')
        _save_sync(document_id,store,operation_name=operation_name,provider_document_name=provider_doc,state=state,indexed_chars=len(corpus),source_pages=page_count,source_sha256=str(doc['source_sha256'] or ''),error_detail=json.dumps(payload.get('error'),ensure_ascii=False) if payload.get('error') else '')
    except HTTPException as exc:
        _save_sync(document_id,store,state='failed',indexed_chars=len(corpus),source_pages=page_count,source_sha256=str(doc['source_sha256'] or ''),error_detail=str(exc.detail)[:2000])
        raise
    return {'document_id':document_id,'filename':doc['filename'],'store_name':store,'state':state,'operation_name':operation_name or None,'indexed_chars':len(corpus),'source_pages':page_count,'source_mode':'page_marked_extracted_text','visual_review_mode':'exact_pdf_pages'}


def _operation(name: str) -> dict:
    if not name:
        return {}
    url=f'https://generativelanguage.googleapis.com/v1beta/{name}'
    with httpx.Client(timeout=30) as client:
        r=client.get(url,headers={'x-goog-api-key':GEMINI_API_KEY})
    if r.status_code >= 400:
        raise HTTPException(502, {'message':'Gemini operation status failed','provider_status':r.status_code,'provider_detail':r.text[:500]})
    return r.json()


@app.get('/api/admin/research-engine/index/status',dependencies=[Depends(require_admin)])
def index_status():
    _ensure_sync_table()
    with connect() as con:
        rows=list(con.execute("""SELECT s.*,d.filename FROM gemini_source_sync s JOIN documents d ON d.id=s.document_id ORDER BY s.updated_at DESC""").fetchall())
        total=con.execute("SELECT count(*) n FROM documents WHERE curriculum_version_id IS NOT NULL").fetchone()['n']
    return {'store_name':configured_store_name() or None,'documents_total':int(total or 0),'synced':[dict(r) for r in rows],'policy':'broad_search_text_index_only; visual_and_question_review_exact_pdf_pages'}


@app.post('/api/admin/research-engine/index/document/{document_id}',dependencies=[Depends(require_admin)])
def index_document(document_id:int):
    return sync_document(document_id)


@app.post('/api/admin/research-engine/index/refresh/{document_id}',dependencies=[Depends(require_admin)])
def refresh_index_status(document_id:int):
    _ensure_sync_table()
    with connect() as con:
        row=con.execute("SELECT * FROM gemini_source_sync WHERE document_id=%s",(document_id,)).fetchone()
    if not row:
        raise HTTPException(404,'Document has not been indexed')
    payload=_operation(str(row['operation_name'] or '')) if row['operation_name'] else {}
    state=row['state']
    provider_doc=str(row['provider_document_name'] or '')
    err=''
    if payload:
        if payload.get('error'):
            state='failed';err=json.dumps(payload['error'],ensure_ascii=False)
        elif payload.get('done'):
            state='active'
            response=payload.get('response') or {}
            provider_doc=str(response.get('document',{}).get('name') or response.get('name') or provider_doc)
        else:
            state='processing'
        _save_sync(document_id,str(row['store_name']),operation_name=str(row['operation_name'] or ''),provider_document_name=provider_doc,state=state,indexed_chars=int(row['indexed_chars'] or 0),source_pages=int(row['source_pages'] or 0),source_sha256=str(row['source_sha256'] or ''),error_detail=err)
    return {'document_id':document_id,'state':state,'provider_document_name':provider_doc or None,'operation':payload or None}
