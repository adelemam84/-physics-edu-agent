from __future__ import annotations

import hashlib
import json


def diagram_spec_hash(diagram: dict) -> str:
    """Return a deterministic identity for the scientific diagram specification."""
    kind = str(diagram.get('normalized_kind') or diagram.get('kind') or '').strip()
    parameters = dict(diagram.get('parameters') or {})
    payload = json.dumps(
        {'kind': kind, 'parameters': parameters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def diagram_manifest(structured: dict) -> dict:
    """Build the current diagram-spec manifest without trusting stored approval flags."""
    items: list[dict] = []
    for index, raw in enumerate(structured.get('diagram_specs') or []):
        diagram = dict(raw or {})
        engine = dict(diagram.get('diagram_engine') or {})
        spec_hash = diagram_spec_hash(diagram)
        approved_hash = str(engine.get('approved_spec_hash') or '')
        version_bound = bool(
            diagram.get('diagram_spec_versioned')
            or engine.get('schema_validated')
            or diagram.get('parameters')
        )
        approval_fresh = bool(
            engine.get('teacher_reviewed')
            and not engine.get('review_required')
            and approved_hash
            and approved_hash == spec_hash
        ) if version_bound else bool(
            engine.get('svg') and not engine.get('review_required')
        )
        items.append({
            'index': index,
            'kind': str(diagram.get('normalized_kind') or diagram.get('kind') or ''),
            'spec_hash': spec_hash,
            'version_bound': version_bound,
            'schema_validated': bool(engine.get('schema_validated')),
            'teacher_reviewed': bool(engine.get('teacher_reviewed')),
            'approved_spec_hash': approved_hash,
            'approval_fresh': approval_fresh,
        })

    identity = [
        {'index': x['index'], 'kind': x['kind'], 'spec_hash': x['spec_hash']}
        for x in items
    ]
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    manifest_hash = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    return {
        'hash': manifest_hash,
        'items': items,
        'total': len(items),
        'version_bound_total': sum(1 for x in items if x['version_bound']),
        'stale_or_unapproved': sum(1 for x in items if x['version_bound'] and not x['approval_fresh']),
        'policy': {
            'identity_uses_kind_and_parameters': True,
            'stored_approval_flags_are_not_identity': True,
            'old_approval_never_matches_changed_spec': True,
        },
    }
