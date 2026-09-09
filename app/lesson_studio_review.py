from __future__ import annotations

import json

from fastapi import Depends, Form, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _organize, _schema
from .lesson_studio_version_history import _history_schema, _insert_job_snapshot
from .services.lesson_mutation_guard import (
    assert_expected_content_hash,
    assert_expected_source_hash,
    content_hash_from_row,
    lesson_content_precondition,
    source_review_hash,
)
from .services.lesson_release_state import invalidate_release_state


_SOURCE_REVIEW_SELECT = '''SELECT id,position,filename,content_type,extracted_text,alternate_ocr_text,
  confidence,ocr_confidence_band,ocr_conflicts,requires_review
  FROM science_lesson_sources WHERE job_id=%s ORDER BY position'''


def _review_schema() -> None:
    """Ensure the base Lesson Studio source-review schema is available."""
    _schema()


def _source_transcript(sources) -> str:
    """Build the canonical transcript represented by the current reviewed source rows."""
    return '\n\n'.join(
        f"[مصدر {s['position']}: {s['filename']}]\n{s['extracted_text'] or ''}" for s in sources
    )


def _source_signature(sources) -> list[tuple[int, str]]:
    """Return a stable signature for all teacher-visible OCR review rows."""
    return [(int(s['id']), source_review_hash(dict(s))) for s in sources]


def lesson_review_data(job_id: str):
    """Return source-review rows, optimistic-concurrency hashes and confidence summary."""
    _review_schema()
    with connect() as con:
        job = con.execute('''SELECT id,title,subject,grade_label,output_mode,status,
          raw_transcript,structured_json FROM science_lesson_jobs WHERE id=%s''', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        rows = list(con.execute(_SOURCE_REVIEW_SELECT, (job_id,)).fetchall())
    sources = []
    for r in rows:
        item = dict(r)
        conflicts = item.get('ocr_conflicts') or []
        item['conflict_count'] = len(conflicts)
        item['source_hash'] = source_review_hash(item)
        sources.append(item)
    return {
        'job': dict(job),
        'content_hash': content_hash_from_row(dict(job)),
        'sources': sources,
        'summary': {
            'total_sources': len(sources),
            'pending_sources': sum(1 for x in sources if x['requires_review']),
            'green': sum(1 for x in sources if x['ocr_confidence_band'] == 'green'),
            'yellow': sum(1 for x in sources if x['ocr_confidence_band'] == 'yellow'),
            'red': sum(1 for x in sources if x['ocr_confidence_band'] == 'red'),
            'conflicts': sum(int(x['conflict_count']) for x in sources),
        },
        'policy': {
            'content_hash_precondition_required_for_mutations': True,
            'source_hash_precondition_required_for_ocr_review_mutations': True,
            'source_approval_and_transcript_refresh_commit_atomically': True,
        },
    }


app.get('/api/admin/lesson-studio/jobs/{job_id}/review', dependencies=[Depends(require_admin)])(lesson_review_data)


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/approve', dependencies=[Depends(require_admin)])
def approve_lesson_source(
    job_id: str,
    source_id: int,
    approved_text: str = Form(...),
    expected_source_hash: str = Form(...),
    expected_content_hash: str = Depends(lesson_content_precondition),
):
    """Approve OCR text and rebuild the lesson only if both visible job/source revisions are still current."""
    text = approved_text.strip()
    if not text:
        raise HTTPException(400, 'Approved transcript cannot be empty')
    _review_schema()

    # Build the potentially expensive organized structure outside locks from one
    # explicit teacher-visible snapshot. The same snapshot is revalidated under
    # row locks before any source or lesson mutation is committed.
    with connect() as con:
        job = con.execute('SELECT * FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        sources = list(con.execute(_SOURCE_REVIEW_SELECT, (job_id,)).fetchall())
    job_item = dict(job)
    assert_expected_content_hash(job_item, expected_content_hash)
    target = next((dict(s) for s in sources if int(s['id']) == int(source_id)), None)
    if not target:
        raise HTTPException(404, 'Lesson source not found')
    assert_expected_source_hash(target, expected_source_hash)
    initial_signature = _source_signature(sources)

    projected = [dict(s) for s in sources]
    for item in projected:
        if int(item['id']) == int(source_id):
            item['extracted_text'] = text
            item['requires_review'] = False
            item['ocr_confidence_band'] = 'teacher_approved'
            break
    transcript = _source_transcript(projected)
    pending = sum(1 for s in projected if s['requires_review'])
    structured = None
    if pending == 0:
        structured = _organize(
            transcript,
            job_item['subject'],
            job_item['grade_label'] or '',
            job_item['title'],
            job_item['output_mode'],
        )

    _history_schema()
    with connect() as con:
        current_job = con.execute('SELECT * FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not current_job:
            raise HTTPException(404, 'Lesson studio job not found')
        current_job = dict(current_job)
        assert_expected_content_hash(current_job, expected_content_hash)
        current_sources = list(con.execute(_SOURCE_REVIEW_SELECT + ' FOR UPDATE', (job_id,)).fetchall())
        if _source_signature(current_sources) != initial_signature:
            raise HTTPException(409, {
                'message': 'Lesson OCR sources changed during approval; reload before approving',
                'action': 'reload_workspace',
            })
        current_target = next((dict(s) for s in current_sources if int(s['id']) == int(source_id)), None)
        if not current_target:
            raise HTTPException(404, 'Lesson source not found')
        assert_expected_source_hash(current_target, expected_source_hash)

        _insert_job_snapshot(
            con,
            job_id,
            current_job,
            'ocr_source_approval',
            f'Approved OCR source {source_id} against explicit content/source revisions',
            {'source_id': source_id, 'source_hash': expected_source_hash},
        )
        con.execute('''UPDATE science_lesson_sources SET extracted_text=%s,requires_review=FALSE,
          ocr_confidence_band='teacher_approved' WHERE id=%s AND job_id=%s''', (text, source_id, job_id))
        if structured is None:
            con.execute('UPDATE science_lesson_jobs SET raw_transcript=%s,updated_at=now() WHERE id=%s',
                        (transcript, job_id))
            invalidate_release_state(con, job_id, status='review_required')
        else:
            con.execute('''UPDATE science_lesson_jobs SET raw_transcript=%s,structured_json=%s::jsonb,
              updated_at=now() WHERE id=%s''',
              (transcript, json.dumps(structured, ensure_ascii=False), job_id))
            invalidate_release_state(con, job_id, status='content_review_required')

    return {
        'approved': True,
        'source_id': source_id,
        'pending_sources': pending,
        'structured_rebuilt': structured is not None,
        'structured': structured,
        'atomic_source_and_lesson_update': True,
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/reopen', dependencies=[Depends(require_admin)])
def reopen_lesson_source(
    job_id: str,
    source_id: int,
    expected_source_hash: str = Form(...),
    expected_content_hash: str = Depends(lesson_content_precondition),
):
    """Reopen OCR review only when the teacher-visible lesson and source revisions are still current."""
    _review_schema()
    with connect() as con:
        job = con.execute('SELECT * FROM science_lesson_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        assert_expected_content_hash(dict(job), expected_content_hash)
        row = con.execute('''SELECT id,position,filename,content_type,extracted_text,alternate_ocr_text,
          confidence,ocr_confidence_band,ocr_conflicts,requires_review
          FROM science_lesson_sources WHERE id=%s AND job_id=%s FOR UPDATE''',
          (source_id, job_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson source not found')
        assert_expected_source_hash(dict(row), expected_source_hash)
        con.execute("UPDATE science_lesson_sources SET requires_review=TRUE,ocr_confidence_band='yellow' WHERE id=%s AND job_id=%s", (source_id, job_id))
        invalidate_release_state(con, job_id, status='review_required')
    return {
        'reopened': True,
        'source_id': source_id,
        'previous_approval_invalidated': True,
        'previous_pdf_invalidated': True,
    }


PAGE = '''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مراجعة Lesson Studio</title><style>body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.src{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.green{border-right:6px solid #12b76a}.yellow{border-right:6px solid #f79009}.red{border-right:6px solid #f04438}.approved,.teacher_approved{border-right:6px solid #1570ef}textarea{width:100%;min-height:180px;box-sizing:border-box;font:inherit;padding:10px}button,input{font:inherit;padding:9px;border-radius:8px;border:1px solid #ccd2dd}button{cursor:pointer}.muted{color:#667085;white-space:pre-wrap}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style><main><div class=box><a href="/admin/lesson-studio">Lesson Studio</a> · <a href="/admin/dashboard">لوحة التحكم</a></div><div class=box><h1>مراجعة النسخ</h1><div><input id=jid placeholder="رقم المشروع"><button id=load>تحميل</button></div><p id=sum class=muted></p></div><div id=list></div><script>const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let contentHash='';async function load(){let id=jid.value.trim();if(!id)return;let r=await fetch('/api/admin/lesson-studio/jobs/'+encodeURIComponent(id)+'/review');if(r.status===401){location.href='/admin/login';return}let x=await r.json();if(!r.ok){sum.textContent=JSON.stringify(x.detail||x);return}contentHash=x.content_hash||'';sum.textContent='المصادر: '+x.summary.total_sources+' · تحتاج مراجعة: '+x.summary.pending_sources+' · تعارضات: '+x.summary.conflicts;list.innerHTML=x.sources.map(s=>`<div class="box src ${esc(s.ocr_confidence_band||'yellow')}"><h3>مصدر ${s.position}: ${esc(s.filename)}</h3><p>الثقة: ${esc(s.ocr_confidence_band)} · Score: ${esc(s.confidence)} · تعارضات: ${s.conflict_count}</p><div class=grid><div><b>النص الأساسي</b><textarea id="t${s.id}">${esc(s.extracted_text)}</textarea></div><div><b>القراءة الثانية</b><div class=muted>${esc(s.alternate_ocr_text||'لا توجد قراءة ثانية')}</div></div></div><p><button data-id="${s.id}" data-hash="${esc(s.source_hash)}" class=approve>اعتماد النص الظاهر</button></p></div>`).join('');document.querySelectorAll('.approve').forEach(b=>b.addEventListener('click',async()=>{let fd=new FormData();fd.append('approved_text',document.getElementById('t'+b.dataset.id).value);fd.append('expected_source_hash',b.dataset.hash||'');b.disabled=true;let q=await fetch('/api/admin/lesson-studio/jobs/'+encodeURIComponent(id)+'/sources/'+b.dataset.id+'/approve',{method:'POST',headers:{'X-Lesson-Content-Hash':contentHash},body:fd});let y=await q.json();b.disabled=false;if(!q.ok){alert(JSON.stringify(y.detail||y));return}load()}))}document.getElementById('load').addEventListener('click',load)</script></main></html>'''


@app.get('/admin/lesson-studio/review', response_class=HTMLResponse)
def lesson_review_page():
    """Serve the focused Lesson Studio OCR review page."""
    return PAGE
