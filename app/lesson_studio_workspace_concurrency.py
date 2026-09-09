from __future__ import annotations

import logging

from . import lesson_studio_workspace as workspace


log = logging.getLogger(__name__)

_API_OLD = "async function api(url,opt){let r=await fetch(url,opt);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(JSON.stringify(x?.detail||x||r.status));return x}"
_API_NEW = """async function api(url,opt){let options={...(opt||{})};let method=String(options.method||'GET').toUpperCase();if(method!=='GET'&&url.includes('/api/admin/lesson-studio/jobs/')&&state?.approval?.content_hash){let headers=new Headers(options.headers||{});headers.set('X-Lesson-Content-Hash',state.approval.content_hash);options.headers=headers}let r=await fetch(url,options);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(JSON.stringify(x?.detail||x||r.status));return x}"""

_APPROVE_SOURCE_OLD = "async function approveSource(sid){let fd=new FormData();fd.append('approved_text',$(`#src-${sid}`).value);try{await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(jobId())}/sources/${sid}/approve`,{method:'POST',body:fd});await load()}catch(e){alert(e.message)}}"
_APPROVE_SOURCE_NEW = """async function approveSource(sid){let fd=new FormData();let source=(state?.review?.sources||[]).find(x=>Number(x.id)===Number(sid));fd.append('approved_text',$(`#src-${sid}`).value);fd.append('expected_source_hash',source?.source_hash||'');try{await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(jobId())}/sources/${sid}/approve`,{method:'POST',body:fd});await load()}catch(e){alert(e.message)}}"""

if _API_OLD not in workspace.WORKSPACE:
    log.warning('Lesson Studio Workspace API helper marker not found; content-hash precondition patch skipped')
else:
    workspace.WORKSPACE = workspace.WORKSPACE.replace(_API_OLD, _API_NEW, 1)

if _APPROVE_SOURCE_OLD not in workspace.WORKSPACE:
    log.warning('Lesson Studio Workspace source-approval marker not found; source-hash patch skipped')
else:
    workspace.WORKSPACE = workspace.WORKSPACE.replace(_APPROVE_SOURCE_OLD, _APPROVE_SOURCE_NEW, 1)
