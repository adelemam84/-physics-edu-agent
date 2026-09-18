from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from fastapi import Depends, HTTPException

from .main import app
from .security import require_admin
from .science_lesson_studio import _job
from .services.storage import get_bytes
from .services.visual_summary import build_visual_summary, render_slides_pptx
from .services.canva_master_contract import CANVA_MASTER_DESIGN_ID, CANVA_MASTER_TEXT_FIELDS, canva_master_values


GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
GEMINI_NOTEBOOK_PROJECT_NUMBER = os.getenv('GEMINI_NOTEBOOK_PROJECT_NUMBER', '').strip()
GEMINI_NOTEBOOK_LOCATION = os.getenv('GEMINI_NOTEBOOK_LOCATION', 'global').strip() or 'global'

CANVA_CLIENT_ID = os.getenv('CANVA_CLIENT_ID', '').strip()
CANVA_CLIENT_SECRET = os.getenv('CANVA_CLIENT_SECRET', '').strip()
CANVA_BRAND_TEMPLATE_ID = os.getenv('CANVA_BRAND_TEMPLATE_ID', '').strip()
CANVA_FIELD_MAP_JSON = os.getenv('CANVA_FIELD_MAP_JSON', '').strip()
CANVA_MASTER_DESIGN_ENV = os.getenv('CANVA_MASTER_DESIGN_ID', '').strip()
CANVA_AUTOFILL_POLL_SECONDS = float(os.getenv('CANVA_AUTOFILL_POLL_SECONDS', '1.0') or '1.0')
CANVA_AUTOFILL_MAX_POLLS = int(os.getenv('CANVA_AUTOFILL_MAX_POLLS', '20') or '20')

GOOGLE_SLIDES_FOLDER_ID = os.getenv('GOOGLE_SLIDES_FOLDER_ID', '').strip()
AI_FREE_ONLY = os.getenv('AI_FREE_ONLY', 'true').strip().lower() in {'1','true','yes','on'}


def _google_access_token(scopes: list[str]) -> str:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise HTTPException(503, 'Google service account is not configured')
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        creds.refresh(Request())
        return str(creds.token)
    except Exception as exc:
        raise HTTPException(503, f'Google credentials could not be initialized: {exc}') from exc


def _canva_access_token() -> str:
    from .canva_oauth import canva_access_token
    return canva_access_token()


def _canva_source() -> tuple[str, str, str]:
    if CANVA_BRAND_TEMPLATE_ID:
        return (
            'brand_template',
            CANVA_BRAND_TEMPLATE_ID,
            f'https://api.canva.com/rest/v1/brand-templates/{CANVA_BRAND_TEMPLATE_ID}/dataset',
        )
    design_id = CANVA_MASTER_DESIGN_ENV or CANVA_MASTER_DESIGN_ID
    return (
        'design',
        design_id,
        f'https://api.canva.com/rest/v1/designs/{design_id}/dataset',
    )


def integration_status() -> dict:
    notebook_configured = bool(GOOGLE_SERVICE_ACCOUNT_JSON and GEMINI_NOTEBOOK_PROJECT_NUMBER)
    notebook_ready = bool(notebook_configured and not AI_FREE_ONLY)
    canva_source_type, canva_source_id, _ = _canva_source()
    canva_ready = bool(CANVA_CLIENT_ID and CANVA_CLIENT_SECRET and canva_source_id)
    slides_ready = bool(GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SLIDES_FOLDER_ID)
    return {
        'gemini_notebook_enterprise': {
            'configured': notebook_ready,
            'configured_credentials': notebook_configured,
            'mode': 'disabled_by_free_only_policy' if AI_FREE_ONLY else 'official_preview_api',
            'requires': ['GOOGLE_SERVICE_ACCOUNT_JSON','GEMINI_NOTEBOOK_PROJECT_NUMBER','Gemini Notebook Enterprise license'],
            'location': GEMINI_NOTEBOOK_LOCATION,
            'blocked_by_free_only_policy': AI_FREE_ONLY,
        },
        'canva': {
            'configured': canva_ready,
            'mode': 'connect_api_design_autofill',
            'requires': ['CANVA_CLIENT_ID','CANVA_CLIENT_SECRET','Canva OAuth authorization','design:content:read','design:content:write','design:meta:read'],
            'note': 'Uses Canva create_from_design Autofill by default; Brand Template is an optional fallback.',
            'master_design_id': CANVA_MASTER_DESIGN_ID,
            'master_field_count': len(CANVA_MASTER_TEXT_FIELDS),
            'master_design_ready': True,
            'brand_template_ready': bool(CANVA_BRAND_TEMPLATE_ID),
            'design_autofill_ready': bool(canva_source_id),
            'autofill_source': canva_source_type,
            'source_id': canva_source_id,
        },
        'google_slides': {
            'configured': slides_ready,
            'mode': 'pptx_import_via_drive',
            'requires': ['GOOGLE_SERVICE_ACCOUNT_JSON','GOOGLE_SLIDES_FOLDER_ID'],
        },
        'mindmap_internal': {
            'configured': True,
            'mode': 'deterministic_svg',
            'external_optional': 'MindMap AI can be used interactively outside runtime; project export stays provider-independent.',
        },
        'policy': {
            'external_integrations_optional': True,
            'source_grounded_payload_only': True,
            'external_failure_does_not_block_internal_exports': True,
            'free_only': AI_FREE_ONLY,
            'paid_enterprise_integrations_blocked': AI_FREE_ONLY,
        },
    }


def _summary_payload(job_id: str) -> tuple[dict, dict, list[dict]]:
    row, sources = _job(job_id)
    structured = row.get('structured_json')
    if not structured:
        raise HTTPException(409, 'Process the lesson before using external integrations')
    summary = build_visual_summary(dict(structured))
    return dict(row), summary, [dict(x) for x in sources]


def _notebook_base() -> str:
    if not GEMINI_NOTEBOOK_PROJECT_NUMBER:
        raise HTTPException(503, 'Gemini Notebook Enterprise project number is not configured')
    loc = GEMINI_NOTEBOOK_LOCATION
    endpoint = 'global' if loc == 'global' else loc
    return f'https://{endpoint}-discoveryengine.googleapis.com/v1alpha/projects/{GEMINI_NOTEBOOK_PROJECT_NUMBER}/locations/{loc}'


def create_gemini_notebook(job_id: str) -> dict:
    if AI_FREE_ONLY:
        raise HTTPException(
            409,
            'Gemini Notebook Enterprise is disabled while AI_FREE_ONLY=true',
        )
    row, summary, sources = _summary_payload(job_id)
    token = _google_access_token(['https://www.googleapis.com/auth/cloud-platform'])
    headers = {'Authorization':f'Bearer {token}','Content-Type':'application/json'}
    with httpx.Client(timeout=90) as client:
        r = client.post(f'{_notebook_base()}/notebooks', headers=headers, json={'title': f"{row.get('title') or summary['title']} — Lesson Studio"})
        if r.status_code >= 400:
            raise HTTPException(502, f'Gemini Notebook create failed: {r.text[:500]}')
        notebook = r.json()
        notebook_id = str(notebook.get('notebookId') or '')
        if not notebook_id:
            raise HTTPException(502, 'Gemini Notebook create returned no notebookId')
        uploaded = []
        upload_base = _notebook_base().replace('/v1alpha/', '/upload/v1alpha/')
        for source in sources:
            try:
                data = get_bytes(source['object_key'])
                h = {
                    'Authorization':f'Bearer {token}',
                    'X-Goog-Upload-File-Name':str(source.get('filename') or 'lesson-source'),
                    'X-Goog-Upload-Protocol':'raw',
                    'Content-Type':str(source.get('content_type') or 'application/octet-stream'),
                }
                u = client.post(f'{upload_base}/notebooks/{notebook_id}/sources:uploadFile', headers=h, content=data)
                uploaded.append({'source_id':source['id'],'ok':u.status_code < 400,'response':u.json() if u.status_code < 400 else u.text[:300]})
            except Exception as exc:
                uploaded.append({'source_id':source.get('id'),'ok':False,'response':str(exc)})
    url = f'https://notebook.cloud.google.com/{GEMINI_NOTEBOOK_LOCATION}/notebook/{notebook_id}?project={GEMINI_NOTEBOOK_PROJECT_NUMBER}'
    return {'provider':'gemini_notebook_enterprise','notebook_id':notebook_id,'url':url,'sources':uploaded,'source_grounded':True}


def _semantic_canva_values(summary: dict) -> dict[str, str]:
    values = canva_master_values(summary)
    sections = list(summary.get('sections') or [])
    values.update({
        'TITLE': str(summary.get('title') or ''),
        'SUBJECT': str(summary.get('subject') or ''),
        'GRADE': str(summary.get('grade_label') or ''),
        'SUMMARY': str(summary.get('summary') or ''),
    })
    for i, item in enumerate(sections[:8], 1):
        values[f'SECTION_{i}_TITLE'] = str(item.get('title') or '')
        values[f'SECTION_{i}_BODY'] = str(item.get('summary') or '')
        values[f'SECTION_{i}_SOURCE'] = '، '.join(item.get('source_refs') or [])
    return values


def _canva_dataset(client: httpx.Client, headers: dict[str, str]) -> tuple[str, str, dict]:
    source_type, source_id, dataset_url = _canva_source()
    ds = client.get(dataset_url, headers=headers)
    if ds.status_code >= 400:
        raise HTTPException(502, f'Canva source dataset failed: {ds.text[:500]}')
    return source_type, source_id, (ds.json().get('dataset') or {})


def _poll_canva_autofill(client: httpx.Client, headers: dict[str, str], job_id: str) -> dict:
    for _ in range(max(1, CANVA_AUTOFILL_MAX_POLLS)):
        result = client.get(f'https://api.canva.com/rest/v1/autofills/{job_id}', headers=headers)
        if result.status_code >= 400:
            raise HTTPException(502, f'Canva autofill status failed: {result.text[:500]}')
        payload = result.json()
        job = payload.get('job') or {}
        status = str(job.get('status') or '')
        if status == 'success':
            return job
        if status == 'failed':
            error = job.get('error') or {}
            raise HTTPException(502, f"Canva autofill failed: {error.get('code','autofill_error')} — {error.get('message','unknown error')}")
        time.sleep(max(0.2, CANVA_AUTOFILL_POLL_SECONDS))
    return {'id': job_id, 'status': 'in_progress'}


def create_canva_design(job_id: str) -> dict:
    row, summary, _sources = _summary_payload(job_id)
    token = _canva_access_token()
    headers = {'Authorization':f'Bearer {token}','Content-Type':'application/json'}
    with httpx.Client(timeout=60) as client:
        source_type, source_id, dataset = _canva_dataset(client, headers)
        semantic = _semantic_canva_values(summary)
        mapping = {}
        if CANVA_FIELD_MAP_JSON:
            try:
                mapping = json.loads(CANVA_FIELD_MAP_JSON)
            except Exception:
                mapping = {}
        data = {}
        for semantic_key, value in semantic.items():
            target = str(mapping.get(semantic_key) or semantic_key)
            if target in dataset and (dataset[target] or {}).get('type') == 'text':
                data[target] = {'type':'text','text':value}
        if not data:
            raise HTTPException(409, 'Canva source has no matching autofill text fields; verify the master field labels or CANVA_FIELD_MAP_JSON')

        autofill_type = 'create_from_brand_template' if source_type == 'brand_template' else 'create_from_design'
        source_key = 'brand_template_id' if source_type == 'brand_template' else 'design_id'
        payload = {
            'type':autofill_type,
            source_key:source_id,
            'title':f"{row.get('title') or summary['title']} — Visual Summary",
            'data':data,
        }
        started = client.post('https://api.canva.com/rest/v1/autofills',headers=headers,json=payload)
        if started.status_code >= 400:
            raise HTTPException(502, f'Canva autofill start failed: {started.text[:500]}')
        started_job = started.json().get('job') or {}
        canva_job_id = str(started_job.get('id') or '')
        if not canva_job_id:
            raise HTTPException(502, 'Canva autofill returned no job id')
        final_job = _poll_canva_autofill(client, headers, canva_job_id)

    result = final_job.get('result') or {}
    design = result.get('design') or {}
    return {
        'provider':'canva',
        'job_id':canva_job_id,
        'status':final_job.get('status'),
        'design':design,
        'fields_used':sorted(data),
        'source_grounded':True,
        'autofill_type':autofill_type,
        'source_id':source_id,
        'trial_information':result.get('trial_information'),
    }


def canva_readiness() -> dict:
    status = integration_status()['canva']
    if not (CANVA_CLIENT_ID and CANVA_CLIENT_SECRET):
        return {**status, 'authorized': False, 'dataset_reachable': False, 'reason':'client_credentials_missing'}
    try:
        token = _canva_access_token()
    except HTTPException as exc:
        return {**status, 'authorized': False, 'dataset_reachable': False, 'reason':str(exc.detail)}
    headers = {'Authorization':f'Bearer {token}','Content-Type':'application/json'}
    try:
        with httpx.Client(timeout=30) as client:
            source_type, source_id, dataset = _canva_dataset(client, headers)
        master_fields = set(CANVA_MASTER_TEXT_FIELDS)
        dataset_fields = set(dataset)
        return {
            **status,
            'authorized': True,
            'dataset_reachable': True,
            'source_type':source_type,
            'source_id':source_id,
            'dataset_field_count':len(dataset_fields),
            'matching_master_fields':len(master_fields & dataset_fields),
            'missing_master_fields':sorted(master_fields - dataset_fields),
            'ready_for_autofill':bool(master_fields & dataset_fields),
        }
    except HTTPException as exc:
        return {**status, 'authorized': True, 'dataset_reachable': False, 'ready_for_autofill':False, 'reason':str(exc.detail)}


def create_google_slides(job_id: str) -> dict:
    row, summary, _sources = _summary_payload(job_id)
    token = _google_access_token([
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/presentations',
    ])
    pptx = render_slides_pptx(summary)
    meta = {
        'name': f"{row.get('title') or summary['title']} — Visual Summary",
        'mimeType':'application/vnd.google-apps.presentation',
        'parents':[GOOGLE_SLIDES_FOLDER_ID],
    }
    boundary='lessonstudio_boundary_97431'
    body=(
        f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
        + json.dumps(meta, ensure_ascii=False)
        + f'\r\n--{boundary}\r\nContent-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation\r\n\r\n'
    ).encode('utf-8') + pptx + f'\r\n--{boundary}--'.encode('utf-8')
    headers={
        'Authorization':f'Bearer {token}',
        'Content-Type':f'multipart/related; boundary={boundary}',
    }
    with httpx.Client(timeout=90) as client:
        r=client.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink',headers=headers,content=body)
    if r.status_code >= 400:
        raise HTTPException(502, f'Google Slides import failed: {r.text[:500]}')
    data=r.json()
    return {'provider':'google_slides','file':data,'source_grounded':True}


@app.get('/api/admin/external-creative-integrations', dependencies=[Depends(require_admin)])
def external_creative_integrations_status():
    return integration_status()


@app.post('/api/admin/lesson-studio/jobs/{job_id}/external/gemini-notebook', dependencies=[Depends(require_admin)])
def external_gemini_notebook(job_id: str):
    return create_gemini_notebook(job_id)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/external/canva', dependencies=[Depends(require_admin)])
def external_canva(job_id: str):
    return create_canva_design(job_id)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/external/google-slides', dependencies=[Depends(require_admin)])
def external_google_slides(job_id: str):
    return create_google_slides(job_id)


@app.get('/api/admin/integrations/canva/master-contract', dependencies=[Depends(require_admin)])
def canva_master_contract():
    return {
        'design_id': CANVA_MASTER_DESIGN_ENV or CANVA_MASTER_DESIGN_ID,
        'fields': list(CANVA_MASTER_TEXT_FIELDS),
        'field_count': len(CANVA_MASTER_TEXT_FIELDS),
        'source_grounded_only': True,
        'brand_template_id_configured': bool(CANVA_BRAND_TEMPLATE_ID),
        'default_mode':'create_from_design',
    }


@app.get('/api/admin/integrations/canva/readiness', dependencies=[Depends(require_admin)])
def canva_integration_readiness():
    return canva_readiness()
