from __future__ import annotations

import json
import uuid

from fastapi import Depends, HTTPException

from .db import connect
from .external_creative_integrations import create_canva_design, create_gemini_notebook, create_google_slides
from .main import app
from .science_lesson_studio import _job
from .security import require_admin
from .services.lesson_integrity import review_source_hash

PROVIDERS = {
    'canva': create_canva_design,
    'google_slides': create_google_slides,
    'gemini_notebook_enterprise': create_gemini_notebook,
}


def _artifact_schema() -> None:
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS science_lesson_external_artifacts(
          id uuid PRIMARY KEY,
          job_id uuid NOT NULL REFERENCES science_lesson_jobs(id) ON DELETE CASCADE,
          provider text NOT NULL,
          source_hash text NOT NULL,
          status text NOT NULL,
          external_id text,
          external_url text,
          metadata jsonb,
          error text,
          created_at timestamptz NOT NULL DEFAULT now()
        )''')
        con.execute('''CREATE INDEX IF NOT EXISTS idx_lesson_external_artifacts_job
          ON science_lesson_external_artifacts(job_id,created_at DESC)''')


def _content_hash(job_id: str) -> str:
    row, _ = _job(job_id)
    structured = row.get('structured_json') or {}
    if not structured:
        raise HTTPException(409, 'Process the lesson before creating external artifacts')
    return review_source_hash(str(row.get('raw_transcript') or ''), dict(structured))


def _external_identity(provider: str, result: dict) -> tuple[str, str, dict]:
    external_id = ''
    external_url = ''
    metadata: dict = {'source_grounded': bool(result.get('source_grounded'))}
    if provider == 'canva':
        design = result.get('design') or {}
        urls = design.get('urls') or {}
        external_id = str(design.get('id') or result.get('job_id') or '')
        external_url = str(urls.get('edit_url') or urls.get('view_url') or design.get('url') or '')
        metadata.update({
            'status': result.get('status'),
            'fields_used': list(result.get('fields_used') or []),
            'source_id': result.get('source_id'),
            'autofill_type': result.get('autofill_type'),
        })
    elif provider == 'google_slides':
        file = result.get('file') or {}
        external_id = str(file.get('id') or '')
        external_url = str(file.get('webViewLink') or '')
        metadata.update({'name': file.get('name')})
    elif provider == 'gemini_notebook_enterprise':
        external_id = str(result.get('notebook_id') or '')
        external_url = str(result.get('url') or '')
        sources = list(result.get('sources') or [])
        metadata.update({
            'source_uploads': len(sources),
            'source_uploads_ok': sum(1 for x in sources if isinstance(x, dict) and x.get('ok')),
        })
    return external_id[:500], external_url[:2000], metadata


def _record(job_id: str, provider: str, source_hash: str, status: str, *, result: dict | None = None, error: str = '') -> str:
    _artifact_schema()
    artifact_id = str(uuid.uuid4())
    external_id, external_url, metadata = _external_identity(provider, result or {})
    with connect() as con:
        con.execute('''INSERT INTO science_lesson_external_artifacts(
          id,job_id,provider,source_hash,status,external_id,external_url,metadata,error
        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)''', (
            artifact_id, job_id, provider, source_hash, status, external_id or None,
            external_url or None, json.dumps(metadata, ensure_ascii=False), (error or '')[:1200] or None,
        ))
    return artifact_id


def _artifact_row(artifact_id: str, current_hash: str) -> dict:
    with connect() as con:
        row = con.execute('''SELECT id,job_id,provider,source_hash,status,external_id,external_url,
          metadata,error,created_at FROM science_lesson_external_artifacts WHERE id=%s''', (artifact_id,)).fetchone()
    data = dict(row)
    data['fresh_for_current_content'] = data.get('source_hash') == current_hash
    return data


@app.get('/api/admin/lesson-studio/jobs/{job_id}/external-artifacts', dependencies=[Depends(require_admin)])
def list_external_artifacts(job_id: str):
    _artifact_schema()
    current_hash = _content_hash(job_id)
    with connect() as con:
        rows = list(con.execute('''SELECT id,job_id,provider,source_hash,status,external_id,external_url,
          metadata,error,created_at FROM science_lesson_external_artifacts
          WHERE job_id=%s ORDER BY created_at DESC LIMIT 100''', (job_id,)).fetchall())
    artifacts = []
    for row in rows:
        item = dict(row)
        item['fresh_for_current_content'] = item.get('source_hash') == current_hash
        artifacts.append(item)
    return {
        'job_id': job_id,
        'current_source_hash': current_hash,
        'artifacts': artifacts,
        'policy': {
            'stale_external_artifacts_never_count_as_current': True,
            'external_artifact_status_never_approves_scientific_content': True,
        },
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/external-artifacts/{provider}', dependencies=[Depends(require_admin)])
def create_external_artifact(job_id: str, provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(400, 'Unsupported external provider')
    source_hash = _content_hash(job_id)
    try:
        result = PROVIDERS[provider](job_id)
    except HTTPException as exc:
        _record(job_id, provider, source_hash, 'failed', error=str(exc.detail))
        raise
    except Exception as exc:
        _record(job_id, provider, source_hash, 'failed', error=f'{type(exc).__name__}: {exc}')
        raise HTTPException(502, 'External creative integration failed') from exc
    artifact_id = _record(job_id, provider, source_hash, 'created', result=result)
    current_hash = _content_hash(job_id)
    return {
        'artifact': _artifact_row(artifact_id, current_hash),
        'result': result,
        'fresh_for_current_content': current_hash == source_hash,
    }
