from __future__ import annotations

import json

from fastapi import Depends, Form, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _organize, _schema


def _refresh_transcript_and_structure(job_id: str) -> dict:
    _schema()
    with connect() as con:
        job = con.execute('SELECT * FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        sources = list(con.execute('''SELECT id,position,filename,extracted_text,requires_review
          FROM science_lesson_sources WHERE job_id=%s ORDER BY position''', (job_id,)).fetchall())
    transcript = '\n\n'.join(
        f"[مصدر {s['position']}: {s['filename']}]\n{s['extracted_text'] or ''}" for s in sources
    )
    pending = sum(1 for s in sources if s['requires_review'])
    structured = None
    if pending == 0:
        structured = _organize(
            transcript,
            job['subject'],
            job['grade_label'] or '',
            job['title'],
            job['output_mode'],
        )
    with connect() as con:
        if structured is None:
            con.execute("UPDATE science_lesson_jobs SET raw_transcript=%s,status='review_required',updated_at=now() WHERE id=%s", (transcript, job_id))
        else:
            con.execute("UPDATE science_lesson_jobs SET raw_transcript=%s,structured_json=%s::jsonb,status='content_review_required',updated_at=now() WHERE id=%s",
                        (transcript, json.dumps(structured, ensure_ascii=False), job_id))
    return {'pending_sources': pending, 'structured_rebuilt': structured is not None, 'structured': structured}


@app.get('/api/admin/lesson-studio/jobs/{job_id}/review', dependencies=[Depends(require_admin)])
def lesson_review_data(job_id: str):
    _schema()
    with connect() as con:
        job = con.execute('SELECT id,title,subject,grade_label,output_mode,status,structured_json FROM science_lesson_jobs WHERE id=%s', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        rows = list(con.execute('''SELECT id,position,filename,content_type,extracted_text,alternate_ocr_text,
          confidence,ocr_confidence_band,ocr_conflicts,requires_review
          FROM science_lesson_sources WHERE job_id=%s ORDER BY position''', (job_id,)).fetchall())
    sources = []
    for r in rows:
        item = dict(r)
        conflicts = item.get('ocr_conflicts') or []
        item['conflict_count'] = len(conflicts)
        sources.append(item)
    return {
        'job': dict(job),
        'sources': sources,
        'summary': {
            'total_sources': len(sources),
            'pending_sources': sum(1 for x in sources if x['requires_review']),
            'green': sum(1 for x in sources if x['ocr_confidence_band'] == 'green'),
            'yellow': sum(1 for x in sources if x['ocr_confidence_band'] == 'yellow'),
            'red': sum(1 for x in sources if x['ocr_confidence_band'] == 'red'),
            'conflicts': sum(int(x['conflict_count']) for x in sources),
        },
    }


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/approve', dependencies=[Depends(require_admin)])
def approve_lesson_source(job_id: str, source_id: int, approved_text: str = Form(...)):
    text = approved_text.strip()
    if not text:
        raise HTTPException(400, 'Approved transcript cannot be empty')
    _schema()
    with connect() as con:
        row = con.execute('SELECT id FROM science_lesson_sources WHERE id=%s AND job_id=%s', (source_id, job_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson source not found')
        con.execute('''UPDATE science_lesson_sources SET extracted_text=%s,requires_review=FALSE,
          ocr_confidence_band='teacher_approved' WHERE id=%s AND job_id=%s''', (text, source_id, job_id))
    refresh = _refresh_transcript_and_structure(job_id)
    return {'approved': True, 'source_id': source_id, **refresh}


@app.post('/api/admin/lesson-studio/jobs/{job_id}/sources/{source_id}/reopen', dependencies=[Depends(require_admin)])
def reopen_lesson_source(job_id: str, source_id: int):
    _schema()
    with connect() as con:
        row = con.execute('SELECT id FROM science_lesson_sources WHERE id=%s AND job_id=%s', (source_id, job_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Lesson source not found')
        con.execute("UPDATE science_lesson_sources SET requires_review=TRUE,ocr_confidence_band='yellow' WHERE id=%s AND job_id=%s", (source_id, job_id))
        con.execute("UPDATE science_lesson_jobs SET status='review_required',updated_at=now() WHERE id=%s", (job_id,))
    return {'reopened': True, 'source_id': source_id}


PAGE = '''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مراجعة Lesson Studio</title><style>body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.src{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.green{border-right:6px solid #12b76a}.yellow{border-right:6px solid #f79009}.red{border-right:6px solid #f04438}.approved{border-right:6px solid #1570ef}textarea{width:100%;min-height:180px;box-sizing:border-box;font:inherit;padding:10px}button,input{font:inherit;padding:9px;border-radius:8px;border:1px solid #ccd2dd}button{cursor:pointer}.muted{color:#667085;white-space:pre-wrap}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style><main><div class=box><a href="/admin/lesson-studio">Lesson Studio</a> · <a href="/admin/dashboard">لوحة التحكم</a></div><div class=box><h1>مراجعة النسخ</h1><div><input id=jid placeholder="رقم المشروع"><button id=load>تحميل</button></div><p id=sum class=muted></p></div><div id=list></div><script>const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function load(){let id=jid.value.trim();if(!id)return;let r=await fetch('/api/admin/lesson-studio/jobs/'+encodeURIComponent(id)+'/review');if(r.status===401){location.href='/admin/login';return}let x=await r.json();if(!r.ok){sum.textContent=JSON.stringify(x.detail||x);return}sum.textContent='المصادر: '+x.summary.total_sources+' · تحتاج مراجعة: '+x.summary.pending_sources+' · تعارضات: '+x.summary.conflicts;list.innerHTML=x.sources.map(s=>`<div class="box src ${esc(s.ocr_confidence_band||'yellow')}"><h3>مصدر ${s.position}: ${esc(s.filename)}</h3><p>الثقة: ${esc(s.ocr_confidence_band)} · Score: ${esc(s.confidence)} · تعارضات: ${s.conflict_count}</p><div class=grid><div><b>النص الأساسي</b><textarea id="t${s.id}">${esc(s.extracted_text)}</textarea></div><div><b>القراءة الثانية</b><div class=muted>${esc(s.alternate_ocr_text||'لا توجد قراءة ثانية')}</div></div></div><p><button data-id="${s.id}" class=approve>اعتماد النص الظاهر</button></p></div>`).join('');document.querySelectorAll('.approve').forEach(b=>b.addEventListener('click',async()=>{let fd=new FormData();fd.append('approved_text',document.getElementById('t'+b.dataset.id).value);b.disabled=true;let q=await fetch('/api/admin/lesson-studio/jobs/'+encodeURIComponent(id)+'/sources/'+b.dataset.id+'/approve',{method:'POST',body:fd});let y=await q.json();b.disabled=false;if(!q.ok){alert(JSON.stringify(y.detail||y));return}load()}))}document.getElementById('load').addEventListener('click',load)</script></main></html>'''


@app.get('/admin/lesson-studio/review', response_class=HTMLResponse)
def lesson_review_page():
    return PAGE
