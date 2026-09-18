from __future__ import annotations

import base64
import json
import os
import re
import time

import httpx

from fastapi import Depends, HTTPException, Request

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _gemini_text
from .services.source_asset_runtime import render_asset_bytes
from .services.ai_governance import model_settings
from .services.ai_budget import enforce_ai_budget
from .services.ai_telemetry import record_ai_usage
from .services.provider_http import (
    provider_attempts,
    provider_error_attempts,
    request_with_retries,
)
from .services.rate_limit import enforce_request_policy

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_VISUAL_MODEL = os.getenv("VISUAL_REVIEW_OPENAI_MODEL", "gpt-5.6-terra").strip() or "gpt-5.6-terra"
VISUAL_REVIEW_FREE_ONLY = os.getenv("VISUAL_REVIEW_FREE_ONLY", "true").strip().lower() in {"1","true","yes","on"}
GEMINI_VISUAL_PRIMARY_MODEL = (
    os.getenv("VISUAL_REVIEW_GEMINI_PRIMARY_MODEL", "gemini-2.5-flash").strip()
    or "gemini-2.5-flash"
)
GEMINI_VISUAL_FALLBACK_MODELS = tuple(
    dict.fromkeys(
        model.strip()
        for model in os.getenv(
            "VISUAL_REVIEW_GEMINI_FALLBACK_MODELS",
            "gemini-2.5-flash-lite",
        ).split(",")
        if model.strip()
    )
)


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
          LEFT JOIN question_assets a ON a.question_id=q.id
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


def _candidate_ordinal(text: object) -> int | None:
    match = re.search(r'\bQ(\d+)\]', str(text or ''), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _prepare_source_row(row: dict) -> tuple[dict, str, int | None]:
    prepared = dict(row)
    ordinal = _candidate_ordinal(prepared.get('text_verbatim'))
    if prepared.get('object_key'):
        return prepared, 'exact_crop', ordinal

    page = int(prepared.get('source_page') or 0)
    document_id = int(prepared.get('document_id') or 0)
    if page < 1 or document_id < 1 or not prepared.get('storage_url'):
        raise HTTPException(503, 'Authoritative source page is unavailable')

    prepared.update({
        'object_key': f'source-drive:{document_id}:{page}:full-page-fallback',
        'page_number': page,
        'crop_x': 0.0,
        'crop_y': 0.0,
        'crop_width': 1.0,
        'crop_height': 1.0,
    })
    return prepared, 'full_source_page_fallback', ordinal


def _source_fingerprint(row: dict, asset_mode: str, ordinal: int | None) -> str:
    fields = (
        row.get('document_id'), row.get('source_page'), row.get('object_key'),
        row.get('crop_x'), row.get('crop_y'), row.get('crop_width'), row.get('crop_height'),
        asset_mode, ordinal or '',
    )
    return ':'.join(str(value or '') for value in fields)


def _suggestion_prompt(asset_mode: str, ordinal: int | None) -> str:
    scope = ''
    if asset_mode == 'full_source_page_fallback':
        target = f'السؤال رقم {ordinal}' if ordinal else 'السؤال المرشح المحدد'
        scope = (
            f'الصورة المرفقة هي صفحة المصدر الأصلية كاملة. المطلوب هو {target} فقط حسب ترتيب '
            'الأسئلة الظاهر في الصفحة. لا تنقل سؤالًا آخر من الصفحة. إذا تعذر تحديد حدود السؤال '
            'المطلوب بدقة، اذكر ذلك داخل uncertain_parts واخفض confidence بدل التخمين. '
        )
    return (
        scope +
        'اقرأ الصورة المصدرية المرفقة فقط، وانقل ما هو ظاهر حرفيًا قدر الإمكان. '
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


def _extract_openai_output_text(payload: dict) -> str:
    texts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") == "output_text" and block.get("text"):
                texts.append(str(block["text"]))
    return "\n".join(texts).strip()


def _openai_visual_json(image: bytes, prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise HTTPException(503, "OpenAI visual fallback is not configured")
    enforce_ai_budget(
        provider="openai",
        task="visual_review_fallback",
        model=OPENAI_VISUAL_MODEL,
    )
    body = {
        "model": OPENAI_VISUAL_MODEL,
        "reasoning": {"effort": "low"},
        "store": False,
        "input": [
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "أنت محرك نسخ بصري احتياطي لمصدر تعليمي. "
                        "استخدم الصورة المرفقة فقط. لا تستخدم المعرفة العامة، لا تحل السؤال، "
                        "ولا تعتمد المحتوى. أخرج JSON فقط."
                    ),
                }],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": "data:image/jpeg;base64,"
                        + base64.b64encode(image).decode("ascii"),
                        "detail": "high",
                    },
                ],
            },
        ],
    }
    started = time.perf_counter()
    try:
        response = request_with_retries(
            "POST",
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
            retry=False,
        )
    except httpx.HTTPError as exc:
        record_ai_usage(
            provider="openai",
            task="visual_review_fallback",
            model=OPENAI_VISUAL_MODEL,
            status="error",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_code="network",
            metadata={"provider_attempts": provider_error_attempts(exc)},
        )
        raise HTTPException(502, "OpenAI visual fallback is temporarily unavailable") from exc
    if response.status_code >= 400:
        record_ai_usage(
            provider="openai",
            task="visual_review_fallback",
            model=OPENAI_VISUAL_MODEL,
            status="error",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_code=str(response.status_code),
            metadata={"provider_attempts": provider_attempts(response)},
        )
        raise HTTPException(
            502,
            {
                "message": "OpenAI visual fallback request failed",
                "provider_status": response.status_code,
            },
        )
    payload = response.json()
    text = _extract_openai_output_text(payload)
    if not text:
        record_ai_usage(
            provider="openai",
            task="visual_review_fallback",
            model=OPENAI_VISUAL_MODEL,
            status="error",
            latency_ms=round((time.perf_counter() - started) * 1000),
            usage=payload.get("usage") or {},
            error_code="empty_content",
            metadata={"provider_attempts": provider_attempts(response)},
        )
        raise HTTPException(502, "OpenAI visual fallback returned no content")
    record_ai_usage(
        provider="openai",
        task="visual_review_fallback",
        model=OPENAI_VISUAL_MODEL,
        status="success",
        latency_ms=round((time.perf_counter() - started) * 1000),
        usage=payload.get("usage") or {},
        metadata={"provider_attempts": provider_attempts(response)},
    )
    return text


def _provider_status_code(exc: HTTPException) -> int | None:
    detail = exc.detail
    provider_status = None
    if isinstance(detail, dict):
        provider_status = detail.get("status") or detail.get("provider_status")
    try:
        return int(provider_status) if provider_status is not None else None
    except (TypeError, ValueError):
        return None


def _should_gemini_model_failover(exc: HTTPException) -> bool:
    provider_status = _provider_status_code(exc)
    return bool(
        provider_status in {408, 429, 500, 502, 503, 504}
        or (provider_status is None and exc.status_code == 503)
    )


def _gemini_visual_json(image: bytes, prompt: str, row: dict) -> tuple[str, str, list[str]]:
    primary = GEMINI_VISUAL_PRIMARY_MODEL if VISUAL_REVIEW_FREE_ONLY else str(model_settings()["gemini_lesson_studio"])
    models = [primary, *[m for m in GEMINI_VISUAL_FALLBACK_MODELS if m != primary]]
    attempted: list[str] = []
    last_exc: HTTPException | None = None
    parts = [
        {"text": f"Document: {row['filename']} · original page {row['source_page']}"},
        {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(image).decode("ascii")}},
    ]
    for model in models:
        attempted.append(model)
        try:
            raw = _gemini_text(
                parts,
                prompt,
                json_mode=True,
                task="visual_review",
                provider_timeout=45,
                provider_retry=False,
                model_override=model,
            )
            return raw, f"gemini:{model}", attempted
        except HTTPException as exc:
            last_exc = exc
            if not _should_gemini_model_failover(exc):
                raise
    assert last_exc is not None
    raise last_exc


def _should_openai_fallback(exc: HTTPException) -> bool:
    provider_status = _provider_status_code(exc)
    return bool(
        (not VISUAL_REVIEW_FREE_ONLY)
        and OPENAI_API_KEY
        and (
            provider_status in {408, 429, 500, 502, 503, 504}
            or (provider_status is None and exc.status_code == 503)
        )
    )


def generate_visual_suggestion(question_id: int) -> dict:
    _schema()
    with connect() as con:
        row = con.execute("""
          SELECT q.id,q.document_id,COALESCE(q.source_page,q.page) source_page,
            q.text_verbatim,
            a.object_key,a.page_number,a.crop_x,a.crop_y,a.crop_width,a.crop_height,
            d.filename,d.storage_url
          FROM questions q
          LEFT JOIN question_assets a ON a.question_id=q.id
          JOIN documents d ON d.id=q.document_id
          JOIN question_review_notes qr ON qr.question_id=q.id
          WHERE q.id=%s AND qr.reason_code='visual_transcription_required' AND qr.status='open'
          LIMIT 1
        """, (question_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Pending visual-review question not found')

    row, asset_mode, ordinal = _prepare_source_row(dict(row))
    try:
        image = render_asset_bytes(row)
    except Exception as exc:
        raise HTTPException(503, 'Authoritative source asset is temporarily unavailable') from exc

    prompt = _suggestion_prompt(asset_mode, ordinal)
    primary_model = GEMINI_VISUAL_PRIMARY_MODEL if VISUAL_REVIEW_FREE_ONLY else str(model_settings()['gemini_lesson_studio'])
    primary_provider_id = 'gemini:' + primary_model
    provider_id = primary_provider_id
    fallback_from = None
    gemini_models_attempted: list[str] = []
    try:
        raw, provider_id, gemini_models_attempted = _gemini_visual_json(image, prompt, row)
        if provider_id != primary_provider_id:
            fallback_from = primary_provider_id
    except HTTPException as exc:
        if not _should_openai_fallback(exc):
            raise
        raw = _openai_visual_json(
            image,
            f"Document: {row['filename']} · original page {row['source_page']}\n" + prompt,
        )
        fallback_from = primary_provider_id
        provider_id = 'openai:' + OPENAI_VISUAL_MODEL
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
    suggestion['asset_mode']=asset_mode
    suggestion['source_candidate_ordinal']=ordinal
    suggestion['provider']=provider_id
    suggestion['fallback_from']=fallback_from
    suggestion['gemini_models_attempted']=gemini_models_attempted

    fingerprint=_source_fingerprint(row, asset_mode, ordinal)
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
              confidence,provider_id,fingerprint))
    return {
        'question_id':question_id,
        'suggestion':suggestion,
        'stored':True,
        'auto_approved':False,
        'free_only':VISUAL_REVIEW_FREE_ONLY,
    }


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
def visual_review_suggest(question_id: int, request: Request):
    enforce_request_policy(
        request,
        name='admin_visual_review',
        default_limit=30,
        default_window_seconds=3600,
    )
    return generate_visual_suggestion(question_id)


@app.post('/api/admin/current-corpus/visual-review/batch-suggest', dependencies=[Depends(require_admin)])
def visual_review_batch_suggest(request: Request, limit: int = 5):
    enforce_request_policy(
        request,
        name='admin_visual_review_batch',
        default_limit=8,
        default_window_seconds=3600,
    )
    rows=[x for x in _queue_rows(min(max(limit,1),5)) if not x.get('suggestion')]
    results=[]
    for row in rows:
        try:
            results.append(generate_visual_suggestion(int(row['id'])))
        except HTTPException as exc:
            results.append({'question_id':int(row['id']),'error':exc.detail})
    return {'processed':len(results),'results':results,'auto_approved':False}


@app.get('/api/admin/current-corpus/visual-review/{question_id}', dependencies=[Depends(require_admin)])
def visual_review_get(question_id: int):
    _schema()
    with connect() as con:
        row=con.execute("""SELECT question_id,source_document_id,source_page,suggestion,confidence,model,
          source_asset_fingerprint,created_at,updated_at
          FROM question_visual_suggestions WHERE question_id=%s""",(question_id,)).fetchone()
    if not row:
        raise HTTPException(404,'Visual suggestion not found')
    return dict(row)
