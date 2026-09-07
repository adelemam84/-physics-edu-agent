from __future__ import annotations

import base64
import json

from fastapi import Depends, HTTPException

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _gemini_text
from .services.source_asset_runtime import render_asset_bytes


def _schema() -> None:
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS question_visual_suggestions(
          question_id bigint PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
          source_document_id bigint NOT NULL,
          source_page integer NOT NULL,
          suggestion jsonb NOT NULL,
          confidence numeric,
          model text,
          source_asset_fingerprint text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")


def _queue_rows(limit: int = 100) -> list[dict]:
    _schema()
    with connect() as con:
        rows = list(con.execute("""
          SELECT q.id,q.document_id,COALESCE(q.source_page,q.page) source_page,
            q.text_verbatim,q.question_type,q.difficulty,q.accepted_answer,
            a.object_key,a.page_number,a.crop_x,a.crop_y,a.crop_width,a.crop_height,
            d.filename,d.storage_url,
            s.suggestion,s.confidence suggestion_confidence,s.updated_at suggestion_updated_at
          FROM question_review_notes qr
          JOIN questions q ON q.id=qr.question_id
          JOIN question_assets a ON a.question_id=q.id
          JOIN documents d ON d.id=q.document_id
          LEFT JOIN question_visual_suggestions s ON s.question_id=q.id
          WHERE qr.reason_code='visual_transcription_required'
            AND qr.status='open'
            AND q.curriculum_version_id=(
              SELECT id FROM curriculum_versions
              WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE
              ORDER BY id DESC LIMIT 1
            )
          ORDER BY q.id
          LIMIT %s
        """, (min(max(int(limit),1),250),)).fetchall())
    return [dict(x) for x in rows]


def _source_fingerprint(row: dict) -> str:
    return ':'.join(str(row.get(k) or '') for k in (
        'document_id','source_page','object_key','crop_x','crop_y','crop_width','crop_height'
    ))


def _suggestion_prompt() -> str:
    return (
        'اقرأ قصاصة السؤال المرفقة فقط، وانقل ما هو ظاهر حرفيًا قدر الإمكان. '
        'لا تستخدم المعرفة العامة ولا تحل السؤال من عندك ولا تستنتج إجابة غير ظاهرة. '
        'إذا كان جزء غير مقروء فاكتبه داخل uncertain_parts بدل التخمين. '
        'لو توجد اختيارات انقلها بترتيبها كما تظهر. '
        'visible_answer يجب أن يكون null ما لم تكن الإجابة نفسها ظاهرة صراحة في القصاصة. '
        'difficulty_guess تقدير تشغيلي غير علمي للاستخدام في المراجعة فقط. '
        'أخرج JSON فقط بالقالب: '
        '{"question_text":"string","options":["string"],"visible_answer":null,'
        '"question_type":"mcq|numeric|essay|unknown","difficulty_guess":"easy|medium|hard|unclassified",'
        '"uncertain_parts":["string"],"visual_description":"string","confidence":0.0}.'
    )


def generate_visual_suggestion(question_id: int) -> dict:
    _schema()
    with connect() as con:
        row = con.execute("""
          SELECT q.id,q.document_id,COALESCE(q.source_page,q.page) source_page,
            a.object_key,a.page_number,a.crop_x,a.crop_y,a.crop_width,a.crop_height,
            d.filename,d.storage_url
          FROM questions q
          JOIN question_assets a ON a.question_id=q.id
          JOIN documents d ON d.id=q.document_id
          JOIN question_review_notes qr ON qr.question_id=q.id
          WHERE q.id=%s AND qr.reason_code='visual_transcription_required' AND qr.status='open'
          LIMIT 1
        """, (question_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Pending visual-review question not found')

    row = dict(row)
    try:
        image = render_asset_bytes(row)
    except Exception as exc:
        raise HTTPException(503, 'Authoritative source asset is temporarily unavailable') from exc

    raw = _gemini_text([
        {'text': f"Document: {row['filename']} · original page {row['source_page']}"},
        {'inlineData': {'mimeType':'image/jpeg','data':base64.b64encode(image).decode('ascii')}},
    ], _suggestion_prompt(), json_mode=True)
    try:
        suggestion = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, 'Visual transcription engine returned invalid JSON') from exc

    allowed_types={'mcq','numeric','essay','unknown'}
    allowed_difficulty={'easy','medium','hard','unclassified'}
    qtype=str(suggestion.get('question_type') or 'unknown')
    difficulty=str(suggestion.get('difficulty_guess') or 'unclassified')
    if qtype not in allowed_types:
        qtype='unknown'
    if difficulty not in allowed_difficulty:
        difficulty='unclassified'
    suggestion['question_type']=qtype
    suggestion['difficulty_guess']=difficulty
    suggestion['options']=[str(x) for x in (suggestion.get('options') or [])][:8]
    suggestion['uncertain_parts']=[str(x) for x in (suggestion.get('uncertain_parts') or [])][:20]
    try:
        confidence=max(0.0,min(1.0,float(suggestion.get('confidence') or 0.0)))
    except (TypeError,ValueError):
        confidence=0.0
    suggestion['confidence']=confidence
    suggestion['policy']='source_image_only_no_auto_approval'
    suggestion['source_page']=int(row['source_page'])

    fingerprint=_source_fingerprint(row)
    with connect() as con:
        con.execute("""
          INSERT INTO question_visual_suggestions(
            question_id,source_document_id,source_page,suggestion,confidence,model,source_asset_fingerprint,updated_at)
          VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s,now())
          ON CONFLICT(question_id) DO UPDATE SET
            source_document_id=excluded.source_document_id,
            source_page=excluded.source_page,
            suggestion=excluded.suggestion,
            confidence=excluded.confidence,
            model=excluded.model,
            source_asset_fingerprint=excluded.source_asset_fingerprint,
            updated_at=now()
        """, (question_id,row['document_id'],row['source_page'],json.dumps(suggestion,ensure_ascii=False),
              confidence,'lesson_studio_gemini',fingerprint))
    return {'question_id':question_id,'suggestion':suggestion,'stored':True,'auto_approved':False}


@app.get('/api/admin/current-corpus/visual-review/queue', dependencies=[Depends(require_admin)])
def visual_review_queue(limit: int = 100):
    rows=_queue_rows(limit)
    return {
        'count':len(rows),
        'items':rows,
        'with_suggestion':sum(1 for x in rows if x.get('suggestion')),
        'without_suggestion':sum(1 for x in rows if not x.get('suggestion')),
        'policy':'source_image_only_no_auto_approval',
    }


@app.post('/api/admin/current-corpus/visual-review/{question_id}/suggest', dependencies=[Depends(require_admin)])
def visual_review_suggest(question_id: int):
    return generate_visual_suggestion(question_id)


@app.post('/api/admin/current-corpus/visual-review/batch-suggest', dependencies=[Depends(require_admin)])
def visual_review_batch_suggest(limit: int = 5):
    rows=[x for x in _queue_rows(min(max(limit,1),5)) if not x.get('suggestion')]
    results=[]
    for row in rows:
        try:
            results.append(generate_visual_suggestion(int(row['id'])))
        except HTTPException as exc:
            results.append({'question_id':int(row['id']),'error':exc.detail})
    return {'processed':len(results),'results':results,'auto_approved':False}
