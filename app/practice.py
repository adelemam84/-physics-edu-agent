from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

from .main import app
from .db import connect
from .services.source_asset_runtime import render_asset_bytes


@app.get('/api/practice/questions')
def practice_questions(limit: int = 100):
    with connect() as con:
        rows = con.execute(
            '''
            SELECT q.id, q.text_verbatim, q.question_type,
                   q.document_id, coalesce(q.source_page,q.page) AS source_page,
                   d.filename AS source_filename,
                   (a.question_id IS NOT NULL) AS has_asset
            FROM questions q
            JOIN documents d ON d.id=q.document_id
            LEFT JOIN question_assets a ON a.question_id=q.id
            WHERE q.approved=TRUE
            ORDER BY q.id
            LIMIT %s
            ''',
            (min(max(limit,1),500),),
        ).fetchall()
    return list(rows)


@app.get('/api/practice/questions/{question_id}/asset')
def practice_asset(question_id: int):
    with connect() as con:
        row = con.execute(
            '''
            SELECT a.object_key,a.page_number,a.crop_x,a.crop_y,a.crop_width,a.crop_height,
                   d.storage_url
            FROM question_assets a
            JOIN questions q ON q.id=a.question_id
            JOIN documents d ON d.id=a.document_id
            WHERE a.question_id=%s AND q.approved=TRUE
            ''',
            (question_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, 'Approved question asset not found')
    try:
        image = render_asset_bytes(dict(row))
    except Exception as exc:
        raise HTTPException(503, 'Question source image is temporarily unavailable') from exc
    return Response(image, media_type='image/jpeg', headers={'Cache-Control':'public, max-age=300'})


PRACTICE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>التدريب العلمي</title><style>body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:900px;margin:auto;padding:18px}.card{background:white;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 3px 14px #0000000a}.asset{width:100%;max-height:70vh;object-fit:contain;border-radius:10px;background:#fafafa}.meta{color:#667085;font-size:13px}.text{white-space:pre-wrap;line-height:1.8}.empty{text-align:center;padding:50px 10px;color:#667085}</style><main><h1>التدريب العلمي</h1><p>يظهر هنا فقط ما تم اعتماده من بنك الأسئلة.</p><div id=items></div></main><script>fetch('/api/practice/questions').then(r=>r.json()).then(qs=>{items.innerHTML=qs.length?qs.map(q=>`<article class=card><div class=meta>#${q.id} · ${q.source_filename} · صفحة ${q.source_page}</div>${q.has_asset?`<img class=asset src="/api/practice/questions/${q.id}/asset">`:''}<div class=text>${esc(q.text_verbatim)}</div></article>`).join(''):'<div class=empty>لا توجد أسئلة معتمدة للطلاب حتى الآن.</div>'});function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}</script></html>'''


@app.get('/practice', response_class=HTMLResponse)
def practice_page():
    return PRACTICE
