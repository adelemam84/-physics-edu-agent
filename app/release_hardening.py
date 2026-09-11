from __future__ import annotations

from fastapi import Depends

from .db import connect
from .exam_blueprint import blueprint_readiness
from .file_search_store import configured_store_name
from .main import app
from .research_engine import research_engine_status
from .security import require_admin

NEXT_RELEASE = app.version


def _sync_summary() -> dict:
    try:
        with connect() as con:
            exists=con.execute("SELECT to_regclass('public.gemini_source_sync') name").fetchone()['name']
            if not exists:
                return {'total':0,'active':0,'processing':0,'failed':0}
            row=con.execute("""SELECT count(*) total,
              count(*) FILTER(WHERE state='active') active,
              count(*) FILTER(WHERE state='processing') processing,
              count(*) FILTER(WHERE state='failed') failed
              FROM gemini_source_sync""").fetchone()
        return {k:int(row[k] or 0) for k in ('total','active','processing','failed')}
    except Exception:
        return {'total':0,'active':0,'processing':0,'failed':0}


def _classify_release_state(runtime_blockers: list[str], content_gates: list[str]) -> str:
    if runtime_blockers:
        return 'code_ready_pending_runtime_activation'
    if content_gates:
        return 'runtime_ready_content_gate_open'
    return 'runtime_ready'


def next_release_status() -> dict:
    research=research_engine_status()
    blueprint=blueprint_readiness()
    sync=_sync_summary()
    checks={
        'database_configured': True,
        'pdf_only_policy': True,
        'gemini_api_key_configured': bool(research.get('configured')),
        'file_search_store_configured': bool(configured_store_name()),
        'orchestrator_active': research.get('orchestrator',{}).get('status') == 'active',
        'question_bank_auto_write_disabled': research.get('guardrails',{}).get('question_bank_auto_write') is False,
        'exam_blueprint_23_23_active': blueprint.get('blueprint',{}).get('objective_questions') == 23 and blueprint.get('blueprint',{}).get('essay_questions') == 23,
    }
    runtime_blockers=[]
    content_gates=[]
    if not checks['gemini_api_key_configured']:
        runtime_blockers.append('GEMINI_API_KEY is not visible to the deployed runtime yet')
    if not checks['file_search_store_configured']:
        runtime_blockers.append('Gemini File Search Store has not been provisioned yet')
    if not blueprint.get('active_shape_feasible',False):
        gaps=blueprint.get('gaps',{})
        content_gates.append(f"23+23 exam bank gap: objective={gaps.get('objective',0)}, essay={gaps.get('essay',0)}")
    return {
        'version':NEXT_RELEASE,
        'release_state':_classify_release_state(runtime_blockers,content_gates),
        'checks':checks,
        'runtime_blockers':runtime_blockers,
        'content_gates':content_gates,
        'blockers':runtime_blockers+content_gates,
        'gemini_source_sync':sync,
        'exam_blueprint':{
            'total_questions':46,
            'objective_questions':23,
            'essay_questions':23,
            'feasible':bool(blueprint.get('active_shape_feasible')),
            'gaps':blueprint.get('gaps',{}),
        },
        'deployment_policy':'promote only a green main commit after CI and production smoke checks pass',
    }


@app.get('/api/next-release/status')
def public_next_release_status():
    data=next_release_status()
    return {
        'version':data['version'],
        'release_state':data['release_state'],
        'orchestrator_active':data['checks']['orchestrator_active'],
        'pdf_only_policy':True,
        'exam_blueprint':data['exam_blueprint'],
    }


@app.get('/api/admin/next-release/status',dependencies=[Depends(require_admin)])
def admin_next_release_status():
    return next_release_status()
