from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .main import app
from .security import require_admin
from .completion_audit import completion_audit_snapshot
from .release_hardening import next_release_status
from .research_engine import research_engine_status
from .corpus_public_status import current_curriculum_phase2_status
from .lesson_studio_release_readiness import release_readiness_snapshot


def project_closure_snapshot() -> dict:
    completion=completion_audit_snapshot()
    release=next_release_status()
    research=research_engine_status()
    corpus=current_curriculum_phase2_status()
    lesson=release_readiness_snapshot()

    code_complete=bool(completion.get('code_complete'))
    programmatic=list(completion.get('programmatic_remaining') or [])
    external=list(completion.get('external_or_human_remaining') or [])

    runtime_checks={
        'health_contract':'registered',
        'research_orchestrator_active': research.get('orchestrator',{}).get('status') == 'active',
        'gemini_source_engine_configured': bool(research.get('configured')),
        'source_only_guardrail': research.get('guardrails',{}).get('source_only') is True,
        'question_bank_auto_write_disabled': research.get('guardrails',{}).get('question_bank_auto_write') is False,
        'lesson_release_engine_operational': lesson.get('reason') != 'approval_state_error',
        'next_release_runtime_ready': release.get('release_state') in {'runtime_ready','runtime_ready_content_gate_open'},
    }

    if not code_complete:
        state='programmatic_attention_required'
    elif external:
        state='production_code_complete_external_gates_open'
    else:
        state='production_and_content_complete'

    signoff=[
        {'id':'application_runtime','label':'Application runtime','status':'complete' if code_complete else 'blocked'},
        {'id':'research_engine','label':'Grounded research engine','status':'complete' if runtime_checks['research_orchestrator_active'] and runtime_checks['gemini_source_engine_configured'] else 'blocked'},
        {'id':'question_bank','label':'Current curriculum question bank','status':'complete' if not any(x.get('id') in {'visual_transcription_review','source_candidate_mismatch'} for x in external) else 'human_gate'},
        {'id':'lesson_sources','label':'Approved explanatory lesson source','status':'complete' if not any(x.get('id')=='approved_explanatory_source' for x in external) else 'external_gate'},
        {'id':'lesson_studio','label':'Lesson Studio release workflow','status':'complete' if runtime_checks['lesson_release_engine_operational'] else 'blocked'},
        {'id':'production_release','label':'Production deployment line','status':'complete' if release.get('release_state') in {'runtime_ready','runtime_ready_content_gate_open'} else 'attention'},
    ]

    return {
        'version': app.version,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'closure_state': state,
        'code_complete': code_complete,
        'content_complete': len(external) == 0,
        'programmatic_remaining': programmatic,
        'external_gates': external,
        'runtime_checks': runtime_checks,
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
            'acceptance_ready': bool(lesson.get('acceptance_ready')),
        },
        'next_release': {
            'release_state': release.get('release_state'),
            'exam_blueprint': release.get('exam_blueprint'),
        },
        'final_policy': {
            'no_external_gate_is_auto_closed': True,
            'no_scientific_content_is_invented_for_completion': True,
            'human_teacher_approval_remains_final_content_gate': True,
            'production_code_complete_does_not_equal_content_complete': True,
        },
    }


@app.get('/api/admin/project-closure', dependencies=[Depends(require_admin)])
def project_closure():
    return project_closure_snapshot()


PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>إغلاق المشروع</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1000px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.muted{color:#667085}.pill{display:inline-block;border:1px solid #e5e7eb;border-radius:999px;padding:6px 9px;margin:3px}a.btn{display:inline-block;background:#172033;color:#fff;text-decoration:none;padding:9px 13px;border-radius:9px}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/completion-audit">Completion Audit</a> · <a href="/admin/lesson-studio/release-readiness">Lesson Studio Readiness</a></div>
<div id=out class=box>جارٍ إنشاء بيان الإغلاق...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r=await fetch('/api/admin/project-closure');if(r.status===401){location.href='/admin/login';return}let x=await r.json();let state=x.closure_state,cls=state==='production_and_content_complete'?'ok':state==='production_code_complete_external_gates_open'?'warn':'bad';out.innerHTML='<h1>Final Production Closure</h1><h2 class="'+cls+'">'+e(state)+'</h2><p class=muted>Version '+e(x.version)+' · '+e(x.generated_at)+'</p><div class=grid><div class=card><b>الكود</b><div class="'+(x.code_complete?'ok':'bad')+'">'+(x.code_complete?'✅ مكتمل':'⛔ يحتاج تدخل')+'</div></div><div class=card><b>المحتوى</b><div class="'+(x.content_complete?'ok':'warn')+'">'+(x.content_complete?'✅ مكتمل':'⚠️ بوابات خارجية مفتوحة')+'</div></div><div class=card><b>الأسئلة المعتمدة</b><div>'+e(x.corpus.approved_questions)+' / '+e(x.corpus.total_questions)+'</div></div><div class=card><b>الاختبارات المنشورة</b><div>'+e(x.corpus.published_quizzes)+'</div></div></div><h2>Sign-off Matrix</h2>'+(x.signoff||[]).map(s=>'<span class=pill>'+e(s.label)+': '+e(s.status)+'</span>').join('')+'<h2>المتبقي الخارجي/البشري</h2>'+((x.external_gates||[]).length?(x.external_gates||[]).map(g=>'<div class="card warn"><b>'+e(g.title)+'</b><br><span class=muted>'+e(g.type)+' · '+e(g.count)+'</span><br><a class=btn href="'+e(g.path)+'">فتح الإجراء</a></div>').join(''):'<div class="card ok">✅ لا توجد بوابات متبقية</div>')+'<h2>Runtime</h2>'+Object.entries(x.runtime_checks||{}).map(([k,v])=>'<div class="pill '+(v===true||v==='registered'?'ok':'warn')+'">'+e(k)+': '+e(v)+'</div>').join('')}
load();</script></main></html>'''


@app.get('/admin/project-closure', response_class=HTMLResponse)
def project_closure_page():
    return PAGE
