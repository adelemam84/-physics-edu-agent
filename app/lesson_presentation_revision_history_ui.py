from __future__ import annotations

from . import lesson_presentation_pro_editor_ui  # noqa: F401
from . import lesson_presentation_studio_ui

_STYLE = r"""
<style>
.revision-history{border:1px solid #a6f4c5;border-radius:12px;padding:12px;margin:10px 0;background:#f6fef9}
.revision-actions{display:flex;gap:7px;flex-wrap:wrap;align-items:end}.revision-actions button{width:auto}
.revision-actions label{min-width:180px;flex:1}.revision-list{display:grid;gap:7px;margin-top:10px;max-height:280px;overflow:auto}
.revision-item{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;border:1px solid #d1fadf;border-radius:10px;background:#fff;padding:9px}
.revision-item button{width:auto}.revision-meta{font-size:12px;color:#667085}.server-draft-ok{color:#067647}.server-draft-warn{color:#b54708}
@media(max-width:760px){.revision-item{grid-template-columns:1fr}}
</style>
"""

_SCRIPT = r"""
<script>
(()=>{
const editorBox=document.getElementById('editorBox');if(!editorBox)return;
const panel=document.createElement('div');panel.className='revision-history';panel.innerHTML='<h3 style="margin-top:0">Revision Timeline & Recovery</h3><p class=muted>مسودة خادم تلقائية + Checkpoints + استعادة نسخة سابقة. أي استعادة تُبطل الفحص والاعتماد السابقين.</p><div class=revision-actions><label>اسم الـCheckpoint<input id=revisionLabel maxlength=120 placeholder="مثال: بعد ضبط الرسومات"></label><button id=saveCheckpoint type=button>حفظ Checkpoint</button><button id=refreshTimeline type=button class=secondary>تحديث السجل</button><button id=clearServerDraft type=button class=secondary>مسح مسودة الخادم</button></div><div id=serverDraftState class=revision-meta>لم يتم فحص مسودة الخادم بعد.</div><div id=revisionList class=revision-list><div class=muted>لا توجد بيانات بعد.</div></div>';
const productivity=document.querySelector('.validation');if(productivity)productivity.parentNode.insertBefore(panel,productivity.nextSibling);else editorBox.appendChild(panel);

const label=document.getElementById('revisionLabel'),saveBtn=document.getElementById('saveCheckpoint'),refreshBtn=document.getElementById('refreshTimeline'),clearBtn=document.getElementById('clearServerDraft'),state=document.getElementById('serverDraftState'),list=document.getElementById('revisionList');
let serverTimer=null,serverSaving=false,lastServerDigest='',restoring=false,bootRecoveryDone=false;
const apiBase=()=>'/api/admin/lesson-pack-studio/jobs/'+encodeURIComponent(id)+'/presentation';
function localDraftMeta(){try{let raw=localStorage.getItem('lesson-presentation-draft:'+id+':'+editorBaseHash);if(!raw)return null;let d=JSON.parse(raw);return d&&d.saved_at?d:null}catch(_){return null}}
function payload(){return {edited_blueprint:blueprint,editor_base_hash:editorBaseHash,current_slide:currentSlide}}
async function jsonFetch(url,options={}){let res=await fetch(url,options);let data={};try{data=await res.json()}catch(_){}if(!res.ok)throw new Error(data?.detail?.message||data?.detail?.code||data?.detail||data?.message||('HTTP '+res.status));return data}
async function saveServerDraftNow(){if(serverSaving||restoring||!blueprint||!dirty||!editorBaseHash)return;serverSaving=true;state.className='revision-meta';state.textContent='جارٍ حفظ مسودة الخادم…';try{let data=await jsonFetch(apiBase()+'/draft',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});lastServerDigest=data.edit_digest||'';state.className='revision-meta server-draft-ok';state.textContent='✓ مسودة الخادم محفوظة تلقائيًا · '+new Date().toLocaleTimeString('ar-EG')}catch(e){state.className='revision-meta server-draft-warn';state.textContent='تعذر حفظ مسودة الخادم: '+e.message+' · المسودة المحلية ما زالت متاحة.'}finally{serverSaving=false}}
function scheduleServerDraft(){clearTimeout(serverTimer);serverTimer=setTimeout(saveServerDraftNow,1800)}
async function clearServerDraft(){try{await jsonFetch(apiBase()+'/draft',{method:'DELETE'});lastServerDigest='';state.className='revision-meta';state.textContent='تم مسح مسودة الخادم.'}catch(e){state.className='revision-meta server-draft-warn';state.textContent='تعذر مسح المسودة: '+e.message}}
async function createCheckpoint(name){if(!blueprint||!editorBaseHash)return null;saveBtn.disabled=true;try{let body={...payload(),label:(name??label.value).trim()};let data=await jsonFetch(apiBase()+'/revisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});label.value='';await loadTimeline();state.className='revision-meta server-draft-ok';state.textContent=(data.created?'✓ تم إنشاء Checkpoint جديد.':'✓ هذه الحالة محفوظة بالفعل في السجل.');return data}catch(e){state.className='revision-meta server-draft-warn';state.textContent='تعذر حفظ Checkpoint: '+e.message;return null}finally{saveBtn.disabled=false}}
function dateText(v){try{return new Date(v).toLocaleString('ar-EG')}catch(_){return String(v||'')}}
async function loadTimeline(){try{let data=await jsonFetch(apiBase()+'/revisions');let rows=data.revisions||[];if(!rows.length){list.innerHTML='<div class=muted>لا توجد Checkpoints بعد.</div>';return}list.innerHTML=rows.map(r=>'<div class=revision-item><div><b>'+(r.label?esc(r.label):('Revision #'+r.id))+'</b><div class=revision-meta>'+esc(r.action||'checkpoint')+' · '+esc(dateText(r.created_at))+' · '+esc(String(r.edit_digest||'').slice(0,12))+'</div></div><button type=button class=secondary data-restore-revision="'+r.id+'">استعادة</button></div>').join('');list.querySelectorAll('[data-restore-revision]').forEach(b=>b.onclick=()=>restoreRevision(Number(b.dataset.restoreRevision))}catch(e){list.innerHTML='<div class=server-draft-warn>تعذر تحميل السجل: '+esc(e.message)+'</div>'}}
async function restoreRevision(revisionId){if(!confirm('سيتم استعادة هذه النسخة كمسودة حالية، وسيُلغى أي فحص أو اعتماد سابق. متابعة؟'))return;restoring=true;try{let data=await jsonFetch(apiBase()+'/revisions/'+revisionId+'/restore',{method:'POST'});blueprint=clone(data.blueprint);currentSlide=Math.max(0,Math.min(Number(data.current_slide)||0,(blueprint.slides?.length||1)-1));dirty=true;validationDigest='';teacherReapproved=false;buildFilmstrip();renderCurrent();updateEditState();markDirty();state.className='revision-meta server-draft-ok';state.textContent='↻ تمت استعادة Revision #'+revisionId+' كمسودة. يلزم الفحص وإعادة الاعتماد.';await loadTimeline()}catch(e){state.className='revision-meta server-draft-warn';state.textContent='تعذر الاستعادة: '+e.message}finally{restoring=false}}
async function recoverServerDraft(){if(bootRecoveryDone||!blueprint||!editorBaseHash)return;bootRecoveryDone=true;try{let data=await jsonFetch(apiBase()+'/draft');if(!data.exists){state.textContent='لا توجد مسودة خادم محفوظة.';return}if(data.stale){state.className='revision-meta server-draft-warn';state.textContent='توجد مسودة خادم قديمة مرتبطة بقاعدة مصدر سابقة؛ لن تتم استعادتها تلقائيًا.';return}let local=localDraftMeta(),serverTime=Date.parse(data.updated_at||0)||0,localTime=Date.parse(local?.saved_at||0)||0;if(local&&localTime>serverTime){state.className='revision-meta server-draft-ok';state.textContent='تم الاحتفاظ بالمسودة المحلية لأنها أحدث من نسخة الخادم.';return}if(data.blueprint){blueprint=clone(data.blueprint);currentSlide=Math.max(0,Math.min(Number(data.current_slide)||0,(blueprint.slides?.length||1)-1));dirty=true;validationDigest='';teacherReapproved=false;buildFilmstrip();renderCurrent();updateEditState();lastServerDigest=data.edit_digest||'';state.className='revision-meta server-draft-ok';state.textContent='↻ تمت استعادة أحدث مسودة محفوظة على الخادم. يلزم الفحص وإعادة الاعتماد.'}}catch(e){state.className='revision-meta server-draft-warn';state.textContent='تعذر فحص مسودة الخادم: '+e.message}}
const oldMarkDirty=markDirty;markDirty=function(){oldMarkDirty();scheduleServerDraft()};
const oldRender=render;render=function(x){bootRecoveryDone=false;oldRender(x);setTimeout(()=>{recoverServerDraft();loadTimeline()},0)};
const resetBtn=document.getElementById('resetDeck'),oldReset=resetBtn?.onclick;if(resetBtn)resetBtn.onclick=()=>{oldReset&&oldReset();clearServerDraft();};
saveBtn.onclick=()=>createCheckpoint();refreshBtn.onclick=loadTimeline;clearBtn.onclick=clearServerDraft;
window.addEventListener('keydown',ev=>{if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;let mod=ev.ctrlKey||ev.metaKey;if(!mod)return;if(ev.key.toLowerCase()==='z'&&!ev.shiftKey){let b=document.getElementById('undoEdit');if(b&&!b.disabled){ev.preventDefault();b.click()}}else if((ev.key.toLowerCase()==='z'&&ev.shiftKey)||ev.key.toLowerCase()==='y'){let b=document.getElementById('redoEdit');if(b&&!b.disabled){ev.preventDefault();b.click()}}});
const approve=document.getElementById('approveEdits'),oldApprove=approve?.onclick;if(approve)approve.onclick=()=>{oldApprove&&oldApprove();setTimeout(()=>{if(teacherReapproved)createCheckpoint('Teacher re-approved')},0)};
loadTimeline();
})();
</script>
"""

_base_workspace = lesson_presentation_studio_ui._workspace

def _workspace_with_revision_history(job_id: str) -> str:
    html = _base_workspace(job_id)
    marker = "</main></html>"
    if marker not in html:
        return html
    return html.replace(marker, _STYLE + _SCRIPT + marker, 1)

lesson_presentation_studio_ui._workspace = _workspace_with_revision_history
