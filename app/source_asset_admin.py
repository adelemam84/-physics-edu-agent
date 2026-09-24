from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from .db import connect
from .security import require_admin
from .services.source_asset_runtime import render_asset_bytes

router = APIRouter()


@router.get('/api/admin/questions/{question_id}/source-asset', dependencies=[Depends(require_admin)])
def admin_source_asset(question_id: int):
    with connect() as con:
        row = con.execute(
            '''SELECT a.object_key,a.page_number,a.crop_x,a.crop_y,a.crop_width,a.crop_height,
                      d.storage_url
               FROM question_assets a
               JOIN documents d ON d.id=a.document_id
               WHERE a.question_id=%s''',
            (question_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, 'Question asset not found')
    try:
        image = render_asset_bytes(dict(row))
    except Exception as exc:
        raise HTTPException(503, 'Source asset is temporarily unavailable') from exc
    return Response(image, media_type='image/jpeg', headers={'Cache-Control':'private,max-age=300'})


@router.get('/api/admin/current-corpus/assets/status', dependencies=[Depends(require_admin)])
def current_corpus_asset_status():
    with connect() as con:
        row = con.execute(
            '''SELECT
                 count(*) FILTER (WHERE q.approved=FALSE) pending_questions,
                 count(*) FILTER (WHERE q.approved=FALSE AND a.question_id IS NOT NULL) pending_with_asset,
                 count(*) FILTER (WHERE q.approved=FALSE AND a.question_id IS NULL) pending_without_asset,
                 count(*) FILTER (WHERE q.approved=TRUE AND a.question_id IS NOT NULL) approved_with_asset
               FROM questions q
               LEFT JOIN question_assets a ON a.question_id=q.id
               WHERE q.curriculum_version_id=(
                 SELECT id FROM curriculum_versions
                 WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE
                 ORDER BY id DESC LIMIT 1
               )'''
        ).fetchone()
        mismatch = con.execute(
            '''SELECT count(*) c FROM question_review_notes qr
               JOIN questions q ON q.id=qr.question_id
               WHERE q.curriculum_version_id=(
                 SELECT id FROM curriculum_versions
                 WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE
                 ORDER BY id DESC LIMIT 1
               ) AND qr.reason_code='source_candidate_mismatch' AND qr.status='open' '''
        ).fetchone()['c']
    out = dict(row)
    out['source_candidate_mismatch'] = int(mismatch or 0)
    out['status'] = 'asset_linkage_complete' if int(out['pending_without_asset'] or 0) <= int(out['source_candidate_mismatch']) else 'asset_linkage_in_progress'
    return out
