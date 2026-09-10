from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .content_completion import content_completion_snapshot
from .corpus_public_status import current_curriculum_phase2_status
from .lesson_studio_release_readiness import release_readiness_snapshot
from .main import app
from .security import require_admin


def completion_audit_snapshot(
    *,
    release_snapshot: dict | None = None,
    corpus_snapshot: dict | None = None,
) -> dict:
    """Audit code vs external completion using strict whole-curriculum source coverage."""
    release = release_snapshot if release_snapshot is not None else release_readiness_snapshot()
    corpus = corpus_snapshot if corpus_snapshot is not None else current_curriculum_phase2_status()
    content = content_completion_snapshot(corpus_snapshot=corpus)
    coverage = content.get('source_coverage') or {}

    visual_pending = int(coverage.get('visual_transcription_required') or 0)
    mismatches = int(coverage.get('source_candidate_mismatch') or 0)
    open_qa_total = int(coverage.get('open_qa_total') or 0)
    other_qa = max(open_qa_total - visual_pending - mismatches, 0)
    uncovered_lessons = int(coverage.get('uncovered_lessons') or 0)

    external = []
    if not content.get('active'):
        external.append({
            'id': 'current_curriculum_inactive',
            'type': 'external_source',
            'title': 'تهيئة المنهج الحالي النشط قبل استكمال المحتوى',
            'count': 1,
            'detail': str(content.get('reason') or 'current_curriculum_not_configured'),
            'path': '/admin/academic',
        })
    else:
        if not coverage.get('explanatory_coverage_complete'):
            external.append({
                'id': 'approved_explanatory_source',
                'type': 'external_source',
                'title': 'اعتماد مصدر شرح حقيقي لكل درس غير مغطى في المنهج الحالي',
                'count': uncovered_lessons,
                'path': '/admin/content-completion',
            })
        if visual_pending:
            external.append({
                'id': 'visual_transcription_review',
                'type': 'human_review',
                'title': 'مراجعة الأسئلة البصرية من صور المصدر',
                'count': visual_pending,
                'path': '/admin/content-completion',
            })
        if mismatches:
            external.append({
                'id': 'source_candidate_mismatch',
                'type': 'human_review',
                'title': 'حسم حالات عدم تطابق المصدر',
                'count': mismatches,
                'path': '/admin/content-completion',
            })
        if other_qa:
            external.append({
                'id': 'other_question_qa_review',
                'type': 'human_review',
                'title': 'حسم ملاحظات QA الأخرى المفتوحة على أسئلة المنهج الحالي',
                'count': other_qa,
                'path': '/admin/current-corpus',
            })

    programmatic = []
    if release.get('approval_error'):
        programmatic.append({
            'id': 'approval_state_error',
            'title': 'إصلاح خطأ Approval State runtime',
            'detail': release['approval_error'],
        })
    for blocker in release.get('platform', {}).get('blockers') or []:
        if blocker.get('owner') == 'system':
            programmatic.append({
                'id': blocker.get('id'),
                'title': blocker.get('label'),
                'detail': blocker.get('detail'),
            })

    approved_mappings = sum(
        1
        for mapping in content.get('mappings') or []
        if mapping.get('mapping_status') == 'approved'
        and mapping.get('context_match')
        and mapping.get('pages_ready')
    )
    return {
        'version': app.version,
        'code_complete': len(programmatic) == 0,
        'content_completion_ready': bool(content.get('content_complete')),
        'production_operational': release.get('reason') != 'approval_state_error',
        'release_decision': release.get('decision'),
        'programmatic_remaining': programmatic,
        'external_or_human_remaining': external,
        'counts': {
            'explanatory_documents': len(content.get('documents') or []),
            'approved_explanatory_mappings': approved_mappings,
            'current_curriculum_lessons': int(coverage.get('total_lessons') or 0),
            'lessons_with_approved_explanatory_source': int(coverage.get('covered_lessons') or 0),
            'uncovered_explanatory_lessons': uncovered_lessons,
            'visual_transcription_required': visual_pending,
            'source_candidate_mismatch': mismatches,
            'open_question_qa': open_qa_total,
            'approved_questions': int((corpus.get('questions') or {}).get('approved_questions') or 0),
            'total_questions': int((corpus.get('questions') or {}).get('total_questions') or 0),
            'published_quizzes': int((corpus.get('quizzes') or {}).get('published') or 0),
        },
        'next_action': external[0] if external else release.get('next_action'),
        'definition': {
            'code_complete': 'No known system-owned blocker remains in runtime/release readiness.',
            'content_complete': (
                'Requires an explicitly approved explanatory page range for every current-curriculum lesson '
                'with every page in that range extracted and nonblank, plus human resolution of every open question QA item.'
            ),
        },
        'policy': {
            'external_work_is_not_reported_as_code_defect': True,
            'visual_content_is_never_invented_to_close_review': True,
            'missing_theory_source_is_never_filled_from_model_memory': True,
            'one_mapping_cannot_impersonate_full_curriculum_coverage': True,
            'content_completion_uses_current_curriculum_only': True,
            'inactive_curriculum_is_reported_explicitly': True,
        },
    }


@app.get('/api/admin/completion-audit', dependencies=[Depends(require_admin)])
def completion_audit():
    """Return the completion audit for authorized administrators."""
    return completion_audit_snapshot()


PAGE = r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>تدقيق اكتمال المشروع</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:920px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.item{padding:10px;border-bottom:1px solid #eee}.muted{color:#667085}a.btn{display:inline-block;padding:9px 13px;background:#172033;color:white;border-radius:9px;text-decoration:none}</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/content-completion">Content Completion</a> · <a href="/admin/lesson-studio/release-readiness">Release Readiness</a></div><div id=out class=box>جارٍ التدقيق...</div><script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r;try{r=await fetch('/api/admin/completion-audit')}catch(err){out.innerHTML='<div class=bad>تعذر تشغيل تدقيق الاكتمال</div>';return}if(r.status===401){location.href='/admin/login';return}if(!r.ok){out.innerHTML='<div class=bad>تعذر تشغيل تدقيق الاكتمال</div>';return}let x;try{x=await r.json()}catch(err){out.innerHTML='<div class=bad>تعذر قراءة نتيجة التدقيق</div>';return}let ext=x.external_or_human_remaining||[],pr=x.programmatic_remaining||[],c=x.counts||{};out.innerHTML='<h1>تدقيق اكتمال المشروع</h1><p class="'+(x.code_complete?'ok':'bad')+'"><b>'+(x.code_complete?'✅ لا توجد نواقص برمجية معروفة':'⛔ توجد نواقص برمجية')+'</b></p><p class=muted>Release decision: '+e(x.release_decision)+' · version '+e(x.version)+'</p><h2>المتبقي البرمجي</h2>'+(pr.length?pr.map(v=>'<div class="item bad">'+e(v.title)+'<div class=muted>'+e(v.detail||'')+'</div></div>').join(''):'<div class="item ok">✅ لا شيء</div>')+'<h2>المتبقي الذي يحتاج مصدرًا/مراجعة بشرية</h2>'+(ext.length?ext.map(v=>'<div class="item warn">'+e(v.title)+' · '+e(v.count)+'<div class=muted>'+e(v.detail||'')+'</div><br><a class=btn href="'+e(v.path)+'">فتح</a></div>').join(''):'<div class="item ok">✅ لا شيء</div>')+'<h2>الحالة الحالية</h2><div class=item>الأسئلة المعتمدة: '+e(c.approved_questions)+' / '+e(c.total_questions)+'</div><div class=item>الاختبارات المنشورة: '+e(c.published_quizzes)+'</div><div class=item>تغطية مصدر الشرح: '+e(c.lessons_with_approved_explanatory_source)+' / '+e(c.current_curriculum_lessons)+' درس</div><div class=item>QA مفتوح: '+e(c.open_question_qa)+'</div>'}
load();</script></main></html>'''


@app.get('/admin/completion-audit', response_class=HTMLResponse)
def completion_audit_page():
    """Render the completion audit dashboard."""
    return PAGE
