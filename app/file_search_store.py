from __future__ import annotations

import os
import time

import httpx
from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from .services.ai_budget import enforce_ai_budget
from .services.ai_telemetry import record_ai_usage
from . import research_engine

STORE_SETTING_KEY = 'gemini_file_search_store'
STORE_DISPLAY_NAME = os.getenv('GEMINI_FILE_SEARCH_DISPLAY_NAME', 'physics-edu-agent-2026-2027').strip() or 'physics-edu-agent-2026-2027'
EMBEDDING_MODEL = os.getenv('GEMINI_FILE_SEARCH_EMBEDDING_MODEL', 'models/gemini-embedding-2').strip() or 'models/gemini-embedding-2'


def _db_store_name() -> str:
    try:
        with connect() as con:
            row = con.execute('SELECT value FROM settings WHERE key=%s', (STORE_SETTING_KEY,)).fetchone()
        return str(row['value']).strip() if row and row.get('value') else ''
    except Exception:
        return ''


def configured_store_name() -> str:
    env_name = os.getenv('GEMINI_FILE_SEARCH_STORE', '').strip()
    return env_name or _db_store_name()


def _activate_store(name: str) -> None:
    # research_engine keeps a module-level value for fast request routing; updating
    # it here makes a newly provisioned store usable immediately in this runtime.
    research_engine.GEMINI_FILE_SEARCH_STORE = name


def _persist_store(name: str) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO settings(key,value) VALUES(%s,%s)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (STORE_SETTING_KEY, name),
        )
    _activate_store(name)


def _create_store() -> dict:
    api_key = research_engine.GEMINI_API_KEY
    if not api_key:
        raise HTTPException(503, 'GEMINI_API_KEY is not configured in the runtime environment')
    enforce_ai_budget(
        provider='gemini',
        task='file_search_store_admin',
        model=EMBEDDING_MODEL,
    )
    url = 'https://generativelanguage.googleapis.com/v1beta/fileSearchStores'
    body = {
        'displayName': STORE_DISPLAY_NAME,
        'embeddingModel': EMBEDDING_MODEL,
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=45) as client:
            response = client.post(url, headers={'x-goog-api-key': api_key}, json=body)
    except httpx.HTTPError as exc:
        record_ai_usage(
            provider='gemini',
            task='file_search_store_admin',
            model=EMBEDDING_MODEL,
            status='error',
            latency_ms=round((time.perf_counter()-started)*1000),
            error_code='network',
        )
        raise HTTPException(502, 'Gemini File Search store service is temporarily unavailable') from exc
    if response.status_code >= 400:
        record_ai_usage(
            provider='gemini',
            task='file_search_store_admin',
            model=EMBEDDING_MODEL,
            status='error',
            latency_ms=round((time.perf_counter()-started)*1000),
            error_code=str(response.status_code),
        )
        try:
            detail = response.json()
        except ValueError:
            detail = response.text[:500]
        raise HTTPException(502, {
            'message': 'Failed to create Gemini File Search store',
            'provider_status': response.status_code,
            'provider_detail': detail,
        })
    payload = response.json()
    name = str(payload.get('name') or '').strip()
    if not name.startswith('fileSearchStores/'):
        record_ai_usage(
            provider='gemini',
            task='file_search_store_admin',
            model=EMBEDDING_MODEL,
            status='error',
            latency_ms=round((time.perf_counter()-started)*1000),
            error_code='invalid_resource_name',
        )
        raise HTTPException(502, 'Gemini returned an invalid File Search store resource name')
    record_ai_usage(
        provider='gemini',
        task='file_search_store_admin',
        model=EMBEDDING_MODEL,
        status='success',
        latency_ms=round((time.perf_counter()-started)*1000),
        metadata={'operation':'create_file_search_store'},
    )
    _persist_store(name)
    return payload


def ensure_store() -> dict:
    name = configured_store_name()
    if name:
        _activate_store(name)
        return {
            'created': False,
            'reused': True,
            'name': name,
            'display_name': STORE_DISPLAY_NAME,
            'embedding_model': EMBEDDING_MODEL,
            'source': 'environment' if os.getenv('GEMINI_FILE_SEARCH_STORE', '').strip() else 'neon_settings',
        }
    payload = _create_store()
    return {
        'created': True,
        'reused': False,
        'name': payload['name'],
        'display_name': payload.get('displayName', STORE_DISPLAY_NAME),
        'embedding_model': payload.get('embeddingModel', EMBEDDING_MODEL),
        'source': 'gemini_api_and_neon_settings',
    }


@app.get('/api/admin/research-engine/file-search-store/status', dependencies=[Depends(require_admin)])
def file_search_store_status():
    name = configured_store_name()
    if name:
        _activate_store(name)
    return {
        'configured': bool(name),
        'name': name or None,
        'display_name': STORE_DISPLAY_NAME,
        'embedding_model': EMBEDDING_MODEL,
        'gemini_api_key_configured': bool(research_engine.GEMINI_API_KEY),
        'persistence': 'environment_or_neon_settings',
    }


@app.post('/api/admin/research-engine/file-search-store/ensure', dependencies=[Depends(require_admin)])
def file_search_store_ensure():
    return ensure_store()
