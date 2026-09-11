from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .main import app
from .security import require_admin
from .completion_audit import completion_audit_snapshot
from .release_hardening import next_release_status
from .research_engine import research_engine_status
from .corpus_public_status import current_curriculum_phase2_status
from .lesson_studio_release_readiness import release_readiness_snapshot
from .operations_readiness import build_operations_readiness
from .services.runtime_identity import runtime_identity


def _deployment_provenance(env: Mapping[str, str] | None = None) -> dict:
    """Compatibility wrapper around the canonical secret-free runtime identity."""
    return runtime_identity(env, application_version=app.version)


def project_closure_snapshot() -> dict:
    """Build one consistent closure manifest across code, deployment and content gates."""
    lesson = release_readiness_snapshot()
    corpus = current_curriculum_phase2_status()
    completion = completion_audit_snapshot(
        release_snapshot=lesson,
        corpus_snapshot=corpus,
    )
    release = next_release_status()
    research = research_engine_status()
    operations = build_operations_readiness()
    deployment = _deployment_provenance()

    programmatic = list(completion.get('programmatic_remaining') or [])
    external = list(completion.get('external_or_human_remaining') or [])
    platform = lesson.get('platform') or {}
    known_programmatic_ids = {str(item.get('id') or '') for item in programmatic}
    for blocker in platform.get('blockers') or []:
        blocker_id = str(blocker.get('id') or '')
        if blocker.get('owner') != 'system' or blocker_id in known_programmatic_ids:
            continue
        programmatic.append({
            'id': blocker_id,
            'title': blocker.get('label') or blocker_id,
            'detail': blocker.get('detail') or '',
        })
        known_programmatic_ids.add(blocker_id)

    phase_x_platform_ready = bool(
        'system_blockers' in platform
        and int(platform.get('system_blockers') or 0) == 0
    )
    phase_x_acceptance_ready = bool(lesson.get('acceptance_ready'))
    code_complete = bool(completion.get('code_complete')) and phase_x_platform_ready and not programmatic
    technical_ready = bool(operations.get('ready_for_technical_handoff'))
    technical_blockers = list(operations.get('technical_blockers') or [])
    content_gates = list(operations.get('content_gates') or [])
    content_complete = len(external) == 0 and phase_x_acceptance_ready and not content_gates
    production_runtime_verified = bool(deployment['current_runtime_is_production_main'])

    runtime_checks = {
        'health_contract': 'registered',
        'research_orchestrator_active': research.get('orchestrator', {}).get('status') == 'active',
        'gemini_source_engine_configured': bool(research.get('configured')),
        'source_only_guardrail': research.get('guardrails', {}).get('source_only') is True,
        'question_bank_auto_write_disabled': research.get('guardrails', {}).get('question_bank_auto_write') is False,
        'lesson_release_engine_operational': lesson.get('reason') != 'approval_state_error',
        'phase_x_platform_ready': phase_x_platform_ready,
        'next_release_runtime_ready': release.get('release_state') in {'runtime_ready', 'runtime_ready_content_gate_open'},
        'technical_handoff_ready': technical_ready,
        'deployment_provenance_available': bool(deployment['provenance_available']),
        'production_runtime_is_main': production_runtime_verified,
    }

    if not code_complete:
        state = 'programmatic_attention_required'
    elif not technical_ready:
        state = 'technical_attention_required'
    elif not production_runtime_verified:
        state = 'production_deployment_verification_required'
    elif not content_complete:
        state = 'production_code_complete_external_gates_open'
    else:
        state = 'production_and_content_complete'

    release_line_ready = release.get('release_state') in {'runtime_ready', 'runtime_ready_content_gate_open'}
    signoff = [
        {'id': 'application_runtime', 'label': 'Application runtime', 'status': 'complete' if code_complete and technical_ready else 'blocked'},
        {
            'id': 'research_engine',
            'label': 'Grounded research engine',
            'status': 'complete' if runtime_checks['research_orchestrator_active'] and runtime_checks['gemini_source_engine_configured'] else 'blocked',
        },
        {
            'id': 'question_bank',
            'label': 'Current curriculum question bank',
            'status': 'complete' if not any(x.get('id') in {'visual_transcription_review', 'source_candidate_mismatch'} for x in external) else 'human_gate',
        },
        {
            'id': 'lesson_sources',
            'label': 'Approved explanatory lesson source',
            'status': 'complete' if not any(x.get('id') == 'approved_explanatory_source' for x in external) else 'external_gate',
        },
        {
            'id': 'lesson_studio',
            'label': 'Lesson Studio release workflow',
            'status': 'complete' if runtime_checks['lesson_release_engine_operational'] and phase_x_platform_ready else 'blocked',
        },
        {
            'id': 'phase_x_acceptance',
            'label': 'Hash-bound production acceptance',
            'status': 'complete' if phase_x_acceptance_ready else ('human_gate' if phase_x_platform_ready else 'blocked'),
        },
        {
            'id': 'production_release',
            'label': 'Production deployment line',
            'status': 'complete' if release_line_ready and production_runtime_verified else 'deployment_attention',
        },
    ]

    return {
        'version': app.version,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'closure_state': state,
        'code_complete': code_complete,
        'technical_ready': technical_ready,
        'technical_blockers': technical_blockers,
        'content_complete': content_complete,
        'content_gates': content_gates,
        'production_runtime_verified': production_runtime_verified,
        'programmatic_remaining': programmatic,
        'external_gates': external,
        'runtime_checks': runtime_checks,
        'deployment': deployment,
        'signoff': signoff,
        'corpus': {
            'academic_year': corpus.get('academic_year'),
            'total_questions': int((corpus.get('questions') or {}).get('total_questions') or 0),
            'approved_questions': int((corpus.get('questions') or {}).get('approved_questions') or 0),
            'published_quizzes': int((corpus.get('quizzes') or {}).get('published') or 0),
        },
        'lesson_studio': {
            'decision': lesson.get('decision'),
            'reason': lesson.get('reason'),
            'acceptance_ready': phase_x_acceptance_ready,
            'platform_ready': phase_x_platform_ready,
            'system_blockers': int(platform.get('system_blockers') or 0),
            'teacher_blockers': int(platform.get('teacher_blockers') or 0),
            'next_action': lesson.get('next_action'),
        },
        'next_release': {
            'release_state': release.get('release_state'),
            'exam_blueprint': release.get('exam_blueprint'),
            'content_gates': content_gates,
        },
        'final_policy': {
            'no_external_gate_is_auto_closed': True,
            'no_scientific_content_is_invented_for_completion': True,
            'human_teacher_approval_remains_final_content_gate': True,
            'production_code_complete_does_not_equal_content_complete': True,
            'technical_readiness_uses_operations_readiness_contract': True,
            'release_content_gates_block_content_complete': True,
            'phase_x_acceptance_is_hash_bound': True,
            'runtime_reports_its_own_deployment_sha_only': True,
            'latest_main_match_requires_external_deployment_verification': True,
            'closure_reuses_one_phase_x_snapshot_per_request': True,
        },
    }


@app.get('/api/admin/project-closure', dependencies=[Depends(require_admin)])
def project_closure():
    """Return the final project closure manifest for authorized administrators."""
    return project_closure_snapshot()


PAGE = r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>إغلاق المشروع</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1000px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.muted{color:#667085}.pill{display:inline-block;border:1px solid #e5e7eb;border-radius:999px;padding:6px 9px;margin:3px}a.btn{display:inline-block;background:#172033;color:#fff;text-decoration:none;padding:9px 13px;border-radius:9px}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/completion-audit">Completion Audit</a> · <a href="/admin/lesson-studio/acceptance">Phase X Acceptance</a> · <a href="/admin/lesson-studio/release-readiness">Lesson Studio Readiness</a></div>
<div id=out class=box>جارٍ إنشاء بيان الإغلاق...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r=await fetch('/api/admin/project-closure');if(r.status===401){location.href='/admin/login';return}if(!r.ok){out.innerHTML='<div class=bad>تعذر تحميل بيان الإغلاق</div>';return}let x;try{x=await r.json()}catch(err){out.innerHTML='<div class=bad>تعذر قراءة بيان الإغلاق</div>';return}let state=x.closure_state,cls=state==='production_and_content_complete'?'ok':state==='programmatic_attention_required'?'bad':'warn',d=x.deployment||{};out.innerHTML='<h1>Final Production Closure</h1><h2 class="'+cls+'">'+e(state)+'</h2><p class=muted>Version '+e(x.version)+' · '+e(x.generated_at)+'</p><div class=grid><div class=card><b>الكود</b><div class="'+(x.code_complete?'ok':'bad')+'">'+(x.code_complete?'✅ مكتمل':'⛔ يحتاج تدخل')+'</div></div><div class=card><b>Technical readiness</b><div class="'+(x.technical_ready?'ok':'bad')+'">'+(x.technical_ready?'✅ جاهز تقنيًا':'⛔ يحتاج تدخل تقني')+'</div></div><div class=card><b>Production runtime</b><div class="'+(x.production_runtime_verified?'ok':'warn')+'">'+(x.production_runtime_verified?'✅ main على Production':'⚠️ يحتاج تحقق نشر')+'</div></div><div class=card><b>المحتوى</b><div class="'+(x.content_complete?'ok':'warn')+'">'+(x.content_complete?'✅ مكتمل':'⚠️ بوابات علمية/بشرية مفتوحة')+'</div></div><div class=card><b>Phase X</b><div class="'+(x.lesson_studio.platform_ready?'ok':'bad')+'">Platform '+(x.lesson_studio.platform_ready?'✅':'⛔')+' · Acceptance '+(x.lesson_studio.acceptance_ready?'✅':'⚠️')+'</div></div><div class=card><b>الأسئلة المعتمدة</b><div>'+e(x.corpus.approved_questions)+' / '+e(x.corpus.total_questions)+'</div></div><div class=card><b>الاختبارات المنشورة</b><div>'+e(x.corpus.published_quizzes)+'</div></div></div><h2>Deployment Provenance</h2><div class=card><b>Environment:</b> '+e(d.environment||'unknown')+' · <b>Ref:</b> '+e(d.git_ref||'unknown')+'<br><b>Commit:</b> '+e(d.git_commit_short||'unavailable')+'<br><span class=muted>مطابقة هذه النسخة مع أحدث main يتم التحقق منها خارجيًا عبر مراقبة النشر، ولا يتم افتراضها من داخل التطبيق.</span></div><h2>Sign-off Matrix</h2>'+(x.signoff||[]).map(s=>'<span class=pill>'+e(s.label)+': '+e(s.status)+'</span>').join('')+'<h2>المتبقي الخارجي/البشري</h2>'+((x.external_gates||[]).length?(x.external_gates||[]).map(g=>'<div class="card warn"><b>'+e(g.title)+'</b><br><span class=muted>'+e(g.type)+' · '+e(g.count)+'</span><br><a class=btn href="'+e(g.path)+'">فتح الإجراء</a></div>').join(''):'<div class="card ok">✅ لا توجد بوابات متبقية في Completion Audit</div>')+'<h2>Runtime</h2>'+Object.entries(x.runtime_checks||{}).map(([k,v])=>'<div class="pill '+(v===true||v==='registered'?'ok':'warn')+'">'+e(k)+': '+e(v)+'</div>').join('')}
load();</script></main></html>'''


@app.get('/admin/project-closure', response_class=HTMLResponse)
def project_closure_page():
    """Render the project closure dashboard without mutating scientific or approval state."""
    return PAGE
