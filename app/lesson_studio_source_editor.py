from __future__ import annotations

from io import BytesIO
import json
import logging
import math
import uuid

from fastapi import Depends, Form, HTTPException
from fastapi.responses import Response
from PIL import Image

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _schema, _verified_ocr
from .services.lesson_release_state import invalidate_release_state
from .services.storage import delete_object, get_bytes, put_bytes, storage_configured

logger = logging.getLogger(__name__)


def _editor_schema() -> None:
    _schema()
    with connect() as con:
        con.execute('ALTER TABLE science_lesson_sources ADD COLUMN IF NOT EXISTS adjusted_object_key text')
        con.execute('ALTER TABLE science_lesson_sources ADD COLUMN IF NOT EXISTS adjustment_meta jsonb')


def _source(job_id: str, source_id: int):
    _editor_schema()
    with connect() as con:
        row = con.execute('SELECT * FROM science_lesson_sources WHERE id=%s AND job_id=%s', (source_id, job_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Lesson source not found')
    if not str(row['content_type']).startswith('image/'):
        raise HTTPException(409, 'Manual image correction is available for image sources only')
    return row


def _delete_unpromoted_adjusted_source(key: str) -> None:
    """Best-effort cleanup for one uniquely owned adjusted-source upload."""
    try:
        delete_object(key)
    except Exception:
        logger.exception('Failed to delete unpromoted adjusted lesson source %s', key)


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _crop(img: Image.Image, left: float, top: float, right: float, bottom: float) -> Image.Image:
    l, t, r, b = map(_clamp01, (left, top, right, bottom))
    if r - l < 0.05 or b - t < 0.05:
        raise HTTPException(400, 'Crop region is too small')
    box = (round(l * img.width), round(t * img.height), round(r * img.width), round(b * img.height))
    return img.crop(box)


def _perspective(img: Image.Image, points: list[float]) -> Image.Image:
    if len(points) != 8:
        raise HTTPException(400, 'perspective_json must contain 8 normalized numbers')
    vals = [_clamp01(x) for x in points]
    tl = (vals[0] * img.width, vals[1] * img.height)
    tr = (vals[2] * img.width, vals[3] * img.height)
    br = (vals[4] * img.width, vals[5] * img.height)
    bl = (vals[6] * img.width, vals[7] * img.height)
    width = max(math.dist(tl, tr), math.dist(bl, br))
    height = max(math.dist(tl, bl), math.dist(tr, br))
    if width < 40 or height < 40:
        raise HTTPException(400, 'Perspective region is too small')
    # Pillow QUAD expects UL, LL, LR, UR source coordinates.
    quad = (tl[0], tl[1], bl[0], bl[1], br[0], br[1], tr[0], tr[1])
    return img.transform((round(width), round(height)), Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC)


def _render_adjusted(data: bytes, *, left: float, top: float, right: float, bottom: float, rotation: int, perspective_json: str) -> tuple[bytes, dict]:
    try:
        img = Image.open(BytesIO(data)).convert('RGB')
    except Exception as exc:
        raise HTTPException(415, 'Source image could not be decoded') from exc
    original_size = img.size
    img = _crop(img, left, top, right, bottom)
    rotation = int(rotation) % 360
    if rotation not in {0, 90, 180, 270}:
        raise HTTPException(400, 'rotation must be 0, 90, 180 or 270')
    if rotation:
        img = img.rotate(-rotation, expand=True)
    perspective_points: list[float] = []
    if perspective_json.strip():
        try:
            payload = json.loads(perspective_json)
            perspective_points = [float(x) for x in payload]
        except Exception as exc:
            raise HTTPException(400, 'perspective_json must be valid JSON array') from exc
        img = _perspective(img, perspective_points)
    out = BytesIO()
    img.save(out, format='PNG', optimize=True)
    meta = {
        'original_size': list(original_size),
        'output_size': [img.width, img.height],
        'crop': [left, top, right, bottom],
        'rotation': rotation,
        'perspective_points': perspective_points,
        'original_preserved': True,
    }
    return out.getvalue(), meta


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/adjust', dependencies=[Depends(require_admin)])
def adjust_lesson_source(
    job_id: str,
    source_id: int,
    crop_left: float = Form(0.0),
    crop_top: float = Form(0.0),
    crop_right: float = Form(1.0),
    crop_bottom: float = Form(1.0),
    rotation: int = Form(0),
    perspective_json: str = Form(''),
):
    row = _source(job_id, source_id)
    if not storage_configured():
        raise HTTPException(503, 'Object storage is not configured')
    data = get_bytes(row['object_key'])
    adjusted, meta = _render_adjusted(
        data,
        left=crop_left,
        top=crop_top,
        right=crop_right,
        bottom=crop_bottom,
        rotation=rotation,
        perspective_json=perspective_json,
    )
    key = f'lesson-studio/{job_id}/adjusted-source-{source_id}-{uuid.uuid4().hex}.png'
    put_bytes(key, adjusted, 'image/png')
    with connect() as con:
        job = con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job:
            _delete_unpromoted_adjusted_source(key)
            raise HTTPException(404, 'Lesson studio job not found')
        current = con.execute('SELECT id FROM science_lesson_sources WHERE id=%s AND job_id=%s FOR UPDATE', (source_id, job_id)).fetchone()
        if not current:
            _delete_unpromoted_adjusted_source(key)
            raise HTTPException(404, 'Lesson source not found')
        con.execute('''UPDATE science_lesson_sources SET adjusted_object_key=%s,adjustment_meta=%s::jsonb,
          requires_review=TRUE,ocr_confidence_band='yellow' WHERE id=%s AND job_id=%s''',
          (key, json.dumps(meta, ensure_ascii=False), source_id, job_id))
        invalidate_release_state(con, job_id, status='review_required')
    return {
        'adjusted': True,
        'source_id': source_id,
        'meta': meta,
        'original_preserved': True,
        'previous_approval_invalidated': True,
        'previous_pdf_invalidated': True,
    }


@app.get('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/adjusted', dependencies=[Depends(require_admin)])
def adjusted_source_preview(job_id: str, source_id: int):
    row = _source(job_id, source_id)
    key = row.get('adjusted_object_key')
    if not key:
        raise HTTPException(404, 'No adjusted derivative exists')
    return Response(get_bytes(key), media_type='image/png', headers={'Cache-Control': 'private, max-age=120'})


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/rerun-ocr', dependencies=[Depends(require_admin)])
def rerun_adjusted_source_ocr(job_id: str, source_id: int):
    row = _source(job_id, source_id)
    key = row.get('adjusted_object_key')
    if not key:
        raise HTTPException(409, 'Create an adjusted derivative before rerunning OCR')
    data = get_bytes(key)
    primary, alternate, envelope = _verified_ocr(data, 'image/png', int(row['position']))
    with connect() as con:
        job = con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        current = con.execute('''SELECT adjusted_object_key FROM science_lesson_sources
          WHERE id=%s AND job_id=%s FOR UPDATE''', (source_id, job_id)).fetchone()
        if not current:
            raise HTTPException(404, 'Lesson source not found')
        if current.get('adjusted_object_key') != key:
            raise HTTPException(409, 'Adjusted source changed during OCR; rerun against the current derivative')
        con.execute('''UPDATE science_lesson_sources SET extracted_text=%s,alternate_ocr_text=%s,
          confidence=%s,ocr_confidence_band=%s,ocr_conflicts=%s::jsonb,requires_review=TRUE
          WHERE id=%s AND job_id=%s''',
          (primary, alternate, envelope.get('score'), envelope.get('confidence_band'),
           json.dumps(envelope.get('conflicts') or [], ensure_ascii=False), source_id, job_id))
        invalidate_release_state(con, job_id, status='review_required')
    return {
        'source_id': source_id,
        'rerun': True,
        'verification': envelope,
        'teacher_approval_required': True,
        'previous_approval_invalidated': True,
        'previous_pdf_invalidated': True,
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/reset-adjustment', dependencies=[Depends(require_admin)])
def reset_source_adjustment(job_id: str, source_id: int):
    _editor_schema()
    with connect() as con:
        job = con.execute('SELECT id FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        current = con.execute('SELECT id FROM science_lesson_sources WHERE id=%s AND job_id=%s FOR UPDATE', (source_id, job_id)).fetchone()
        if not current:
            raise HTTPException(404, 'Lesson source not found')
        con.execute('''UPDATE science_lesson_sources SET adjusted_object_key=NULL,adjustment_meta=NULL,
          requires_review=TRUE,ocr_confidence_band='yellow' WHERE id=%s AND job_id=%s''', (source_id, job_id))
        invalidate_release_state(con, job_id, status='review_required')
    return {
        'reset': True,
        'source_id': source_id,
        'original_preserved': True,
        'previous_approval_invalidated': True,
        'previous_pdf_invalidated': True,
    }