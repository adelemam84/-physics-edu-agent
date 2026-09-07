from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .lesson_studio_release_readiness import release_readiness_snapshot
from .corpus_public_status import current_curriculum_phase2_status


EXPLANATORY_KINDS = ('lesson','explanation','textbook','notes')


def completion_audit_snapshot() -> dict:
    release = release_readiness_snapshot()
    corpus = current_curriculum_phase2_status()

    with connect() as con:
        source = con.execute("""SELECT
          count(DISTINCT d.id) FILTER (WHERE d.kind = ANY(%s)) explanatory_documents,
          count(*) FILTER (WHERE d.kind = ANY(%s) AND m.mapping_status='approved') approved_mappings
          FROM documents d
          LEFT JOIN lesson_source_mappings m ON m.document_id=d.id""",
          (list(EXPLANATORY_KINDS), list(EXPLANATORY_KINDS))).fetchone()

    qa_rows = corpus.get('qa_open_by_reason') or []
    visual_pending = sum(int(x.get('total') or 0) for x in qa_rows if x.get('reason_code') == 'visual_transcription_required')
    mismatches = sum(int(x.get('total') or 0) for x in qa_rows if x.get('reason_code') == 'source_candidate_mismatch')

    external = []
    if int(source.get('approved_mappings') or 0) == 0:
        external.append({
            'id':'approved_explanatory_source',
            'type':'external_source',
            'title':'اعتماد مصدر شرح/كتاب حقيقي وربطه بالدروس',
            'count':0,
            'path':'/admin/document-recovery',
        })
    if visual_pending:
        external.append({
            'id':'visual_transcription_review',
            'type':'human_review',
            'title':'مراجعة الأسئلة البصرية من صور المصدر',
            'count':visual_pending,
            'path':'/admin/current-corpus',
        })
    if mismatches:
        external.append({
            'id':'source_candidate_mismatch',
            'type':'human_review',
            'title':'حسم حالات عدم تطابق المصدر',
            'count':mismatches,
            'path':'/admin/current-corpus',
        })

    programmatic = []
    if release.get('approval_error'):
        programmatic.append({
            'id':'approval_state_error',
            'title':'إصلاح خطأ Approval State runtime',
            'detail':release['approval_error'],
        })
    for blocker in release.get('platform',{}).get('blockers') or []:
        if blocker.get('owner') == 'system':
            programmatic.append({
                'id':blocker.get('id'),
                'title':blocker.get('label'),
                'detail':blocker.get('detail'),
            })

    return {
        'version': app.version,
        'code_complete': len(programmatic) == 0,
        'production_operational': release.get('reason') != 'approval_state_error',
        'release_decision': release.get('decision'),
        'programmatic_remaining': programmatic,
        'external_or_human_remaining': external,
        'counts': {
            'explanatory_documents': int(source.get('explanatory_documents') or 0),
            'approved_explanatory_mappings': int(source.get('approved_mappings') or 0),
            'visual_transcription_required': visual_pending,
            'source_candidate_mismatch': mismatches,
            'approved_questions': int((corpus.get('questions') or {}).get('approved_questions') or 0),
            'total_questions': int((corpus.get('questions') or {}).get('total_questions') or 0),
            'published_quizzes': int((corpus.get('quizzes') or {}).get('published') or 0),
        },
        'next_action': external[0] if external else release.get('next_action'),
        'definition': {
            'code_complete':'No known system-owned blocker remains in runtime/release readiness.',
            'content_complete':'Requires approved explanatory source plus human resolution of source-image review items.',
        },
        'policy': {
            'external_work_is_not_reported_as_code_defect': True,
            'visual_content_is_never_invented_to_close_review': True,
            'missing_theory_source_is_never_filled_from_model_memory': True,
        },
    }


@app.get('/api/admin/completion-audit', dependencies=[Depends(require_admin)])
def completion_audit():
    return completion_audit_snapshot()


PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>تدقيق اكتمال المشروع</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:920px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.item{padding:10px;border-bottom:1px solid #eee}.muted{color:#667085}a.btn{display:inline-block;padding:9px 13px;background:#172033;color:white;border-radius:9px;text-decoration:none}</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/lesson-studio/release-readiness">Release Readiness</a></div><div id=out class=box>جارٍ التدقيق...</div><script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r=await fetch('/api/admin/completion-audit');if(r.status===401){location.href='/admin/login';return}let x=await r.json();let ext=x.external_or_human_remaining||[],pr=x.programmatic_remaining||[];out.innerHTML='<h1>تدقيق اكتمال المشروع</h1><p class="'+(x.code_complete?'ok':'bad')+'"><b>'+(x.code_complete?'✅ لا توجد نواقص برمجية معروفة':'⛔ توجد نواقص برمجية')+'</b></p><p class=muted>Release decision: '+e(x.release_decision)+' · version '+e(x.version)+'</p><h2>المتبقي البرمجي</h2>'+(pr.length?pr.map(v=>'<div class="item bad">'+e(v.title)+'<div class=muted>'+e(v.detail||'')+'</div></div>').join(''):'<div class="item ok">✅ لا شيء</div>')+'<h2>المتبقي الذي يحتاج مصدرًا/مراجعة بشرية</h2>'+(ext.length?ext.map(v=>'<div class="item warn">'+e(v.title)+' · '+e(v.count)+'<br><a class=btn href="'+e(v.path)+'">فتح</a></div>').join(''):'<div class="item ok">✅ لا شيء</div>')+'<h2>الحالة الحالية</h2><div class=item>الأسئلة المعتمدة: '+e(x.counts.approved_questions)+' / '+e(x.counts.total_questions)+'</div><div class=item>الاختبارات المنشورة: '+e(x.counts.published_quizzes)+'</div><div class=item>مصادر الشرح المعتمدة: '+e(x.counts.approved_explanatory_mappings)+'</div>'}
load();</script></main></html>'''


@app.get('/admin/completion-audit', response_class=HTMLResponse)
def completion_audit_page():
    return PAGE
