from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .lesson_studio_acceptance import acceptance_snapshot
from .lesson_studio_approval_state import sync_approval_state
from .science_lesson_studio import _schema


ACTION_ROUTES = {
    'runtime': '/admin/lesson-studio/acceptance',
    'reference_pdf': '/admin/lesson-studio/references',
    'curriculum_map': '/admin/lesson-studio/reference-workspace',
    'handwritten_job': '/admin/lesson-studio',
    'ocr_review': '/admin/lesson-studio/workspace',
    'notation_review': '/admin/lesson-studio/workspace',
    'diagram_review': '/admin/lesson-studio/workspace',
    'reference_review': '/admin/lesson-studio/reference-workspace',
    'scientific_reference_review': '/admin/lesson-studio/reference-workspace',
    'independent_second_review': '/admin/lesson-studio/tools',
    'teacher_approval': '/admin/lesson-studio/workspace',
    'final_pdf': '/admin/lesson-studio/workspace',
    'final_pdf_export': '/admin/lesson-studio/workspace',
}


def _latest_job_id() -> str | None:
    _schema()
    with connect() as con:
        row = con.execute("""SELECT id FROM science_lesson_jobs
          WHERE structured_json IS NOT NULL
          ORDER BY updated_at DESC NULLS LAST, created_at DESC
          LIMIT 1""").fetchone()
    return str(row['id']) if row else None


def _job_meta(job_id: str) -> dict:
    with connect() as con:
        row = con.execute("""SELECT id,title,subject,grade_label,mode,status,updated_at,created_at
          FROM science_lesson_jobs WHERE id=%s""", (job_id,)).fetchone()
    return dict(row) if row else {}


def _first_action(platform_blockers: list[dict], approval: dict | None, job_id: str | None) -> dict | None:
    for blocker in platform_blockers:
        key = str(blocker.get('id') or '')
        path = ACTION_ROUTES.get(key, '/admin/lesson-studio/acceptance')
        return {
            'id': key,
            'title': blocker.get('label') or key,
            'detail': blocker.get('detail') or '',
            'owner': blocker.get('owner') or 'teacher',
            'path': path,
        }
    if approval:
        gate_by_name = {str(x.get('gate')): x for x in approval.get('gates') or []}
        for gate in (
            'ocr_review','notation_review','diagram_review',
            'scientific_reference_review','independent_second_review',
            'teacher_approval','final_pdf_export',
        ):
            item = gate_by_name.get(gate)
            if not item or item.get('state') in {'complete','not_required'}:
                continue
            path = ACTION_ROUTES.get(gate, '/admin/lesson-studio/workspace')
            if job_id and path == '/admin/lesson-studio/workspace':
                path = f'{path}?job_id={job_id}'
            return {
                'id': gate,
                'title': gate.replace('_', ' '),
                'detail': item.get('details') or {},
                'owner': 'teacher',
                'path': path,
            }
    return None


def release_readiness_snapshot(job_id: str | None = None) -> dict:
    acceptance = acceptance_snapshot()
    selected_job = job_id or _latest_job_id()
    approval = None
    job = None
    approval_error = None
    if selected_job:
        job = _job_meta(selected_job)
        try:
            approval = sync_approval_state(selected_job)
        except Exception as exc:
            approval_error = str(exc)

    platform_blockers = list(acceptance.get('blockers') or [])
    system_blockers = [x for x in platform_blockers if x.get('owner') == 'system']
    teacher_blockers = [x for x in platform_blockers if x.get('owner') != 'system']

    if not selected_job:
        decision = 'action_required'
        reason = 'no_structured_lesson_job'
    elif approval_error:
        decision = 'blocked'
        reason = 'approval_state_error'
    elif system_blockers:
        decision = 'blocked'
        reason = 'runtime_or_system_blocker'
    elif approval and approval.get('blocked_gates'):
        decision = 'blocked'
        reason = 'lesson_gate_blocked'
    elif teacher_blockers:
        decision = 'action_required'
        reason = 'acceptance_input_required'
    elif approval and approval.get('next_actions'):
        decision = 'action_required'
        reason = 'lesson_gate_pending'
    elif approval and approval.get('summary', {}).get('all_required_complete') and acceptance.get('acceptance_ready'):
        decision = 'ready'
        reason = 'all_release_requirements_complete'
    else:
        decision = 'action_required'
        reason = 'release_requirements_incomplete'

    next_action = _first_action(platform_blockers, approval, selected_job)
    if not selected_job:
        next_action = {
            'id': 'handwritten_job',
            'title': 'إنشاء درس حقيقي ورفع المصدر',
            'detail': 'لا يوجد مشروع Lesson Studio منظم يمكن اختباره حتى النهاية.',
            'owner': 'teacher',
            'path': '/admin/lesson-studio',
        }

    return {
        'version': app.version,
        'decision': decision,
        'reason': reason,
        'job_id': selected_job,
        'job': job,
        'acceptance_ready': bool(acceptance.get('acceptance_ready')),
        'platform': {
            'checks': acceptance.get('checks') or [],
            'blockers': platform_blockers,
            'system_blockers': len(system_blockers),
            'teacher_blockers': len(teacher_blockers),
        },
        'approval': approval,
        'approval_error': approval_error,
        'next_action': next_action,
        'policy': {
            'ready_requires_real_source_acceptance': True,
            'ready_requires_hash_bound_pdf': True,
            'teacher_approval_is_final_content_gate': True,
            'scientific_content_is_never_invented_to_clear_a_gate': True,
        },
    }


@app.get('/api/admin/lesson-studio/release-readiness', dependencies=[Depends(require_admin)])
def lesson_studio_release_readiness(job_id: str | None = None):
    return release_readiness_snapshot(job_id)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>جاهزية إصدار Lesson Studio</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:980px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.item{padding:10px;border-bottom:1px solid #eee}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.muted{color:#667085}.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#f2f4f7;margin:2px}a.btn{display:inline-block;padding:10px 14px;border-radius:10px;background:#172033;color:#fff;text-decoration:none}input,button{font:inherit;padding:9px;border:1px solid #ccd2dd;border-radius:9px;width:100%}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/lesson-studio/workspace">Workspace</a> · <a href="/admin/lesson-studio/acceptance">Acceptance</a></div>
<div class=box><h1>Release Readiness Orchestrator</h1><div class=grid><div><label>Job ID اختياري</label><input id=jid placeholder="اتركه فارغًا لاختيار أحدث درس"></div><div style="align-self:end"><button id=loadBtn>فحص الجاهزية</button></div></div></div>
<div id=out class=box>جارٍ الفحص...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let id=jid.value.trim(),u='/api/admin/lesson-studio/release-readiness'+(id?'?job_id='+encodeURIComponent(id):'');let r=await fetch(u);if(r.status===401){location.href='/admin/login';return}let x=await r.json();if(!r.ok){out.innerHTML='<div class=bad>'+e(JSON.stringify(x))+'</div>';return}let cls=x.decision==='ready'?'ok':x.decision==='blocked'?'bad':'warn',a=x.approval||{},s=a.summary||{},n=x.next_action;out.innerHTML='<h2 class="'+cls+'">'+(x.decision==='ready'?'✅ جاهز للإصدار':x.decision==='blocked'?'⛔ محجوب':'⚠️ يحتاج إجراء')+'</h2><p class=muted>السبب: '+e(x.reason)+' · الإصدار '+e(x.version)+'</p>'+(x.job?'<div class=card><b>'+e(x.job.title||x.job.id)+'</b><div class=muted>'+e(x.job.subject||'')+' · '+e(x.job.grade_label||'')+' · '+e(x.job.status||'')+'</div></div>':'')+'<div class=grid><div class=card><b>Acceptance</b><div class="'+(x.acceptance_ready?'ok':'bad')+'">'+(x.acceptance_ready?'مكتمل':'غير مكتمل')+'</div></div><div class=card><b>Gates مكتملة</b><div>'+e(s.complete||0)+'</div></div><div class=card><b>Pending</b><div>'+e(s.pending||0)+'</div></div><div class=card><b>Blocked</b><div>'+e(s.blocked||0)+'</div></div></div>'+(n?'<div class=card><h3>الإجراء التالي</h3><p><b>'+e(n.title)+'</b></p><p class=muted>'+e(typeof n.detail==='string'?n.detail:JSON.stringify(n.detail))+'</p><a class=btn href="'+e(n.path)+'">تنفيذ الإجراء</a></div>':'<div class="card ok">✅ لا يوجد إجراء متبقٍ</div>')+'<h3>بوابات المنصة</h3>'+(x.platform.checks||[]).map(c=>'<div class="item '+(c.ok?'ok':'bad')+'">'+(c.ok?'✅ ':'⚠️ ')+e(c.label)+'<div class=muted>'+e(c.detail)+'</div></div>').join('')+'<h3>بوابات الدرس</h3>'+((a.gates||[]).map(g=>'<span class=pill>'+e(g.gate)+': '+e(g.state)+'</span>').join('')||'<span class=muted>لا توجد حالة درس بعد.</span>')}
loadBtn.onclick=load;load();
</script></main></html>'''


@app.get('/admin/lesson-studio/release-readiness', response_class=HTMLResponse)
def lesson_studio_release_readiness_page():
    return PAGE
