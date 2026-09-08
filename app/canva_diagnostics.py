from __future__ import annotations

import os

import httpx
from fastapi import Depends, HTTPException

from .canva_oauth import canva_access_token, _stored_authorization
from .external_creative_integrations import (
    CANVA_BRAND_TEMPLATE_ID,
    CANVA_MASTER_DESIGN_ENV,
)
from .main import app
from .security import require_admin
from .services.canva_master_contract import CANVA_MASTER_DESIGN_ID, CANVA_MASTER_TEXT_FIELDS


def _source_contract() -> tuple[str, str, str]:
    source_design_id = CANVA_MASTER_DESIGN_ENV or CANVA_MASTER_DESIGN_ID
    if CANVA_BRAND_TEMPLATE_ID:
        return (
            'brand_template',
            CANVA_BRAND_TEMPLATE_ID,
            f'https://api.canva.com/rest/v1/brand-templates/{CANVA_BRAND_TEMPLATE_ID}/dataset',
        )
    return (
        'design',
        source_design_id,
        f'https://api.canva.com/rest/v1/designs/{source_design_id}/dataset',
    )


def _dataset_schema(payload: dict) -> dict:
    data = payload.get('dataset') or {}
    return data if isinstance(data, dict) else {}


def canva_readiness_snapshot(check_remote: bool = False) -> dict:
    auth = _stored_authorization()
    source_type, source_id, dataset_url = _source_contract()
    result = {
        'configured': bool(os.getenv('CANVA_CLIENT_ID') and os.getenv('CANVA_CLIENT_SECRET')),
        'source_type': source_type,
        'source_id': source_id,
        'expected_field_count': len(CANVA_MASTER_TEXT_FIELDS),
        'expected_fields': list(CANVA_MASTER_TEXT_FIELDS),
        'authorized': bool(auth.get('authorized')),
        'authorized_for_requested_scopes': bool(auth.get('authorized') and not auth.get('missing_scopes')),
        'needs_reauthorization': bool(auth.get('needs_reauthorization')),
        'missing_scopes': sorted(auth.get('missing_scopes') or []),
        'remote_checked': False,
        'dataset_field_count': None,
        'matching_field_count': None,
        'missing_fields': [],
        'ready': False,
    }
    if not check_remote:
        result['ready'] = bool(
            result['configured']
            and result['source_id']
            and result['authorized_for_requested_scopes']
        )
        return result

    token = canva_access_token()
    headers = {'Authorization': f'Bearer {token}'}
    with httpx.Client(timeout=30) as client:
        response = client.get(dataset_url, headers=headers)
    if response.status_code >= 400:
        raise HTTPException(502, f'Canva dataset diagnostics failed: {response.text[:500]}')
    dataset = _dataset_schema(response.json())
    expected = set(CANVA_MASTER_TEXT_FIELDS)
    available = set(dataset)
    missing = sorted(expected - available)
    matching = sorted(expected & available)
    result.update({
        'remote_checked': True,
        'dataset_field_count': len(dataset),
        'matching_field_count': len(matching),
        'matching_fields': matching,
        'missing_fields': missing,
        'ready': bool(dataset and not missing),
    })
    return result


@app.get('/api/admin/integrations/canva/diagnostics', dependencies=[Depends(require_admin)])
def canva_diagnostics(remote: bool = False):
    return canva_readiness_snapshot(check_remote=remote)
