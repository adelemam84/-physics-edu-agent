from __future__ import annotations

import hashlib
import json

from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .science_lesson_studio import _gemini_text
from .science_reference_library import _schema
from .security import require_admin


def _map_schema() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_reference_documents ADD COLUMN IF NOT EXISTS curriculum_map jsonb')
        con.execute('ALTER TABLE science_reference_documents ADD COLUMN IF NOT EXISTS curriculum_map_source_hash text')
        con.execute('ALTER TABLE science_reference_documents ADD COLUMN IF NOT EXISTS curriculum_map_at timestamptz')


def _source_pages(reference_id: str) -> tuple[dict, list[dict]]:
    _map_schema()
    with connect() as con:
        doc = con.execute('''SELECT id,title,subject,grade_label,academic_year,page_count,ingestion_status,
          extracted_pages,curriculum_map,curriculum_map_source_hash,curriculum_map_at
          FROM science_reference_documents WHERE id=%s''', (reference_id,)).fetchone()
        if not doc:
            raise HTTPException(404, 'Scientific reference not found')
        pages = list(con.execute('''SELECT page_number,page_text,extraction_method FROM science_reference_pages
          WHERE document_id=%s AND btrim(page_text)<>'' ORDER BY page_number''', (reference_id,)).fetchall())
    return dict(doc), [dict(x) for x in pages]


def _pages_hash(pages: list[dict]) -> str:
    raw = '\n'.join(f"{p['page_number']}\n{p['page_text']}" for p in pages)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def curriculum_map_state(reference_id: str) -> dict:
    doc, pages = _source_pages(reference_id)
    current_hash = _pages_hash(pages)
    stored = doc.get('curriculum_map_source_hash') or ''
    cmap = doc.get('curriculum_map') or None
    return {
        'reference_id': reference_id,
        'title': doc['title'],
        'subject': doc['subject'],
        'grade_label': doc.get('grade_label'),
        'page_count': doc['page_count'],
        'extracted_pages': len(pages),
        'ingestion_status': doc.get('ingestion_status'),
        'available': bool(cmap),
        'fresh': bool(cmap and stored and stored == current_hash),
        'curriculum_map': cmap,
        'policy': 'reference_pages_only_no_general_knowledge',
    }


@app.get('/api/admin/lesson-studio/references/{reference_id}/curriculum-map', dependencies=[Depends(require_admin)])
def get_curriculum_map(reference_id: str):
    return curriculum_map_state(reference_id)


@app.post('/api/admin/lesson-studio/references/{reference_id}/curriculum-map', dependencies=[Depends(require_admin)])
def build_curriculum_map(reference_id: str):
    doc, pages = _source_pages(reference_id)
    if not pages:
        raise HTTPException(409, 'Reference has no extracted pages yet')
    if len(pages) < int(doc['page_count']):
        raise HTTPException(409, {
            'message': 'Complete reference OCR/extraction before building the curriculum map',
            'page_count': int(doc['page_count']),
            'extracted_pages': len(pages),
        })
    chunks = []
    chars = 0
    for p in pages:
        text = str(p['page_text'] or '').strip()
        block = f"[صفحة {p['page_number']}]\n{text}"
        if chars + len(block) > 70000:
            break
        chunks.append(block)
        chars += len(block)
    expected = {
        'units': [{
            'title': 'string',
            'page_start': 1,
            'page_end': 1,
            'lessons': [{
                'title': 'string',
                'page_start': 1,
                'page_end': 1,
                'topics': [{'title': 'string', 'source_pages': [1]}],
                'key_terms_from_reference': ['string'],
            }],
        }],
        'unmapped_pages': [1],
        'notes': ['string'],
    }
    instruction = (
        'أنت تبني خريطة منهج من صفحات مرجع علمي فقط. ممنوع استخدام المعرفة العامة أو إضافة درس أو موضوع غير ظاهر في الصفحات. '
        'استخرج الوحدات والدروس والموضوعات كما يدعمها المرجع، واربط كل موضوع بأرقام الصفحات التي تدعمه. '
        'إذا لم تستطع تحديد بنية درس بثقة فاترك الصفحة في unmapped_pages بدل التخمين. '
        'لا تعيد صياغة أسماء الدروس بلا ضرورة، وحافظ على مصطلحات المرجع. أخرج JSON صالحًا فقط.'
    )
    prompt = (
        f"اسم المرجع: {doc['title']}\nالمادة: {doc['subject']}\nالصف: {doc.get('grade_label') or ''}\n"
        f"قالب الإخراج: {json.dumps(expected, ensure_ascii=False)}\n\n"
        'صفحات المرجع:\n' + '\n\n'.join(chunks)
    )
    raw = _gemini_text([{'text': prompt}], instruction, json_mode=True)
    try:
        cmap = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, 'Curriculum-map engine returned invalid JSON') from exc
    valid_pages = {int(p['page_number']) for p in pages}
    for unit in cmap.get('units') or []:
        for lesson in unit.get('lessons') or []:
            for topic in lesson.get('topics') or []:
                topic['source_pages'] = [int(x) for x in (topic.get('source_pages') or []) if int(x) in valid_pages]
    source_hash = _pages_hash(pages)
    with connect() as con:
        con.execute('''UPDATE science_reference_documents SET curriculum_map=%s::jsonb,
          curriculum_map_source_hash=%s,curriculum_map_at=now() WHERE id=%s''',
          (json.dumps(cmap, ensure_ascii=False), source_hash, reference_id))
    return {
        'reference_id': reference_id,
        'created': True,
        'fresh': True,
        'curriculum_map': cmap,
        'policy': 'reference_pages_only_no_general_knowledge',
    }
