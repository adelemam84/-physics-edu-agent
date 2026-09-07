from __future__ import annotations

from difflib import SequenceMatcher
import json

from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from .lesson_studio_version_history import _history_schema


def _norm(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) if not isinstance(value, str) else value


def _change(kind: str, key: str, before, after) -> dict:
    b, a = _norm(before), _norm(after)
    ratio = SequenceMatcher(a=b, b=a).ratio() if (b or a) else 1.0
    return {
        'kind': kind,
        'key': key,
        'before': before,
        'after': after,
        'similarity': round(ratio, 4),
        'changed': b != a,
    }


def _index_by(items: list[dict], keys: tuple[str, ...]) -> dict[str, dict]:
    out = {}
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        key = ''
        for field in keys:
            value = str(item.get(field) or '').strip()
            if value:
                key = value
                break
        out[key or f'index:{i}'] = item
    return out


def structured_diff(before: dict, after: dict) -> dict:
    before = dict(before or {})
    after = dict(after or {})
    changes = []

    for field in ('title', 'summary', 'objectives', 'key_terms', 'warnings'):
        if field in before or field in after:
            c = _change('field', field, before.get(field), after.get(field))
            if c['changed']:
                changes.append(c)

    b_sections = _index_by(before.get('sections') or [], ('heading', 'title'))
    a_sections = _index_by(after.get('sections') or [], ('heading', 'title'))
    for key in sorted(set(b_sections) | set(a_sections)):
        c = _change('section', key, b_sections.get(key), a_sections.get(key))
        if c['changed']:
            changes.append(c)

    b_eq = _index_by(before.get('equations_or_rules') or [], ('label', 'expression'))
    a_eq = _index_by(after.get('equations_or_rules') or [], ('label', 'expression'))
    for key in sorted(set(b_eq) | set(a_eq)):
        c = _change('equation', key, b_eq.get(key), a_eq.get(key))
        if c['changed']:
            changes.append(c)

    b_diag = _index_by(before.get('diagram_specs') or [], ('title', 'kind', 'normalized_kind'))
    a_diag = _index_by(after.get('diagram_specs') or [], ('title', 'kind', 'normalized_kind'))
    for key in sorted(set(b_diag) | set(a_diag)):
        c = _change('diagram', key, b_diag.get(key), a_diag.get(key))
        if c['changed']:
            changes.append(c)

    b_add = before.get('approved_additions') or []
    a_add = after.get('approved_additions') or []
    c = _change('approved_additions', 'approved_additions', b_add, a_add)
    if c['changed']:
        changes.append(c)

    summary = {
        'total_changes': len(changes),
        'sections': sum(1 for x in changes if x['kind'] == 'section'),
        'equations': sum(1 for x in changes if x['kind'] == 'equation'),
        'diagrams': sum(1 for x in changes if x['kind'] == 'diagram'),
        'fields': sum(1 for x in changes if x['kind'] == 'field'),
        'approved_additions': sum(1 for x in changes if x['kind'] == 'approved_additions'),
    }
    return {'summary': summary, 'changes': changes}


def _load_version(job_id: str, version_no: int | None) -> dict:
    _history_schema()
    with connect() as con:
        if version_no is None:
            row = con.execute('SELECT structured_json,raw_transcript,status,teacher_approved FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
        else:
            row = con.execute('SELECT structured_json,raw_transcript,job_status status,teacher_approved FROM science_lesson_versions WHERE job_id=%s AND version_no=%s', (job_id, version_no)).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson version not found')
    return dict(row)


def compare_versions(job_id: str, from_version: int, to_version: int | None = None) -> dict:
    before = _load_version(job_id, from_version)
    after = _load_version(job_id, to_version)
    transcript = _change('transcript', 'raw_transcript', before.get('raw_transcript') or '', after.get('raw_transcript') or '')
    structured = structured_diff(dict(before.get('structured_json') or {}), dict(after.get('structured_json') or {}))
    return {
        'job_id': job_id,
        'from_version': from_version,
        'to_version': to_version if to_version is not None else 'current',
        'transcript': transcript,
        'structured': structured,
        'status': {
            'before': before.get('status'),
            'after': after.get('status'),
            'teacher_approved_before': bool(before.get('teacher_approved')),
            'teacher_approved_after': bool(after.get('teacher_approved')),
        },
        'read_only': True,
        'policy': {
            'scientific_meaning_not_inferred': True,
            'diff_does_not_approve_or_restore': True,
            'source_files_untouched': True,
        },
    }


@app.get('/api/admin/lesson-studio/jobs/{job_id}/versions/{from_version}/diff', dependencies=[Depends(require_admin)])
def lesson_version_diff(job_id: str, from_version: int, to_version: int | None = None):
    return compare_versions(job_id, from_version, to_version)
