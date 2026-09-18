from __future__ import annotations

from . import lesson_presentation_revision_history_ui  # noqa: F401
from . import lesson_presentation_studio_ui

_STYLE = r"""
<style>
.approval-ledger{border:1px solid #d0d5dd;border-radius:12px;padding:12px;margin:10px 0;background:#fcfcfd}
.approval-ledger.ok{border-color:#abefc6;background:#ecfdf3}.approval-ledger.warn{border-color:#fedf89;background:#fffaeb}
.approval-head{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap}.approval-history{display:grid;gap:6px;margin-top:8px;max-height:220px;overflow:auto}
.approval-row{display:grid;grid-template-columns:1fr auto;gap:8px;padding:8px;border:1px solid #e4e7ec;border-radius:9px;background:#fff}.approval-row button{width:auto}
@media(max-width:760px){.approval-row{grid-template-columns:1fr}}
</style>
"""

_SCRIPT = r"""
<script>
(()=>{
const editorBox=document.getElementById('editorBox'),approve=document.getElementById('approveEdits');if(!editorBox||!approve)return;
let persistentApproved=false,serverApprovalId=null,approvalDigest='';
const panel=document.createElement('div');panel.id='approvalLedger';panel.className='approval-ledger warn';panel.innerHTML='<div class=approval-head><div><b>Persistent Teacher Approval</b><div id=approvalState class=muted>هذه النسخة لم تُفحص مقابل سجل الاعتماد بعد.</div></div><button id=refreshApproval type=button class=secondary>تحديث الاعتماد</button></div><details><summary>Approval History</summary><div id=approvalHistory class=approval-history><div class=muted>لا توجد بيانات بعد.</div></div></details>';
const validation=document.querySelector('#editorBox .validation');if(validation)validation.parentNode.insertBefore(panel,validation.nextSibling);else editorBox.appendChild(panel);
const state=document.getElementById('approvalState'),history=document.getElementById('approvalHistory'),refresh=document.getElementById('refreshApproval');
approve.textContent='اعتماد النسخة الحالية';

function currentBody(){
  let p=payload();
  if(dirty){
    p.edited_blueprint=blueprint;
    p.editor_base_hash=editorBaseHash;
    p.validation_digest=validationDigest;
  }
  return p;
}
function setApproval(value,item=null){
  persistentApproved=!!value;serverApprovalId=item?.id||null;approvalDigest=item?.edit_digest||'';
  panel.className='approval-ledger '+(persistentApproved?'ok':'warn');
  state.className=persistentApproved?'ok':'warn';
  state.textContent=persistentApproved
    ?'✅ اعتماد خادم دائم لهذه النسخة بالضبط · Approval #'+serverApprovalId+' · '+String(approvalDigest).slice(0,12)
    :'⚠️ لا يوجد اعتماد خادم فعال لهذه النسخة. التصدير النهائي متوقف.';
  teacherReapproved=persistentApproved;
}
async function api(url,options={}){
  let r=await fetch(url,options),x={};try{x=await r.json()}catch(_){}
  if(!r.ok)throw new Error(x?.detail?.message||x?.detail?.code||x?.detail||x?.message||('HTTP '+r.status));
  return x;
}
async function loadHistory(){
  try{
    let x=await api('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/approvals');
    let rows=x.approvals||[];
    history.innerHTML=rows.length?rows.map(a=>'<div class=approval-row><div><b>Approval #'+a.id+(a.revoked_at?' · Revoked':' · Active')+'</b><div class=muted>'+esc(String(a.edit_digest||'').slice(0,16))+' · '+esc(new Date(a.approved_at).toLocaleString('ar-EG'))+(a.approval_notes?' · '+esc(a.approval_notes):'')+'</div></div>'+(a.revoked_at?'':'<button type=button class=secondary data-revoke="'+a.id+'">إلغاء</button>')+'</div>').join(''):'<div class=muted>لا توجد اعتمادات محفوظة.</div>';
    history.querySelectorAll('[data-revoke]').forEach(b=>b.onclick=async()=>{if(!confirm('إلغاء هذا الاعتماد؟ سيُمنع تصدير النسخة المطابقة حتى اعتمادها مرة أخرى.'))return;try{await api('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/approvals/'+b.dataset.revoke+'/revoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'Revoked from Presentation Studio'})});if(Number(b.dataset.revoke)===Number(serverApprovalId))setApproval(false);await loadHistory();updateEditState()}catch(e){state.textContent='تعذر إلغاء الاعتماد: '+e.message}});
  }catch(e){history.innerHTML='<div class=bad>تعذر تحميل سجل الاعتماد: '+esc(e.message)+'</div>'}
}
async function checkApproval(){
  if(!blueprint){setApproval(false);return}
  if(dirty&&!validationDigest){setApproval(false);updateEditState();return}
  try{
    let x=await api('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/approval-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(currentBody())});
    setApproval(x.approved,x.approval);updateEditState();
  }catch(e){setApproval(false);state.textContent='⚠️ يلزم الفحص/الاعتماد الحالي: '+e.message;updateEditState()}
}
const oldUpdate=updateEditState;updateEditState=function(){
  oldUpdate();
  approve.disabled=!blueprint||(dirty&&!validationDigest)||persistentApproved;
  studentPptx.disabled=!blueprint||!persistentApproved;
  teacherPptx.disabled=!blueprint||!persistentApproved;
  if(!blueprint)return;
  if(persistentApproved){editState.className='ok';editState.textContent='✅ النسخة الحالية مفحوصة ومعتمدة على الخادم. التصدير متاح.'}
  else if(dirty&&!validationDigest){editState.className='warn';editState.textContent='⚠️ توجد تعديلات. يلزم الفحص ثم اعتماد النسخة على الخادم.'}
  else{editState.className='warn';editState.textContent='⚠️ النسخة الحالية تحتاج اعتماد مدرس دائم قبل التصدير.'}
};
const oldMark=markDirty;markDirty=function(){persistentApproved=false;serverApprovalId=null;approvalDigest='';oldMark();setApproval(false)};
const oldRender=render;render=function(x){persistentApproved=false;serverApprovalId=null;approvalDigest='';oldRender(x);setTimeout(()=>{checkApproval();loadHistory()},0)};
const oldValidate=validateEdits.onclick;validateEdits.onclick=async()=>{persistentApproved=false;setApproval(false);await oldValidate();if(validationDigest)await checkApproval();updateEditState()};
approve.onclick=async()=>{
  if(!blueprint||(dirty&&!validationDigest))return;
  approve.disabled=true;state.className='muted';state.textContent='جارٍ حفظ الاعتماد الدائم لهذه النسخة...';
  try{
    let body=currentBody();body.notes=dirty?'Teacher approved validated edited revision':'Teacher approved generated base revision';
    let x=await api('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/approvals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    setApproval(true,x.approval);validationResult.className='ok';validationResult.textContent='✅ تم تسجيل اعتماد دائم مرتبط بالـexact digest. أي تغيير جديد ينشئ digest مختلفًا ويلغي صلاحية هذا الاعتماد للتصدير.';await loadHistory();updateEditState();
  }catch(e){setApproval(false);validationResult.className='bad';validationResult.textContent='⛔ تعذر الاعتماد: '+e.message;updateEditState()}
};
refresh.onclick=()=>{checkApproval();loadHistory()};
loadHistory();updateEditState();
})();
</script>
"""

_base_workspace = lesson_presentation_studio_ui._workspace

def _workspace_with_approval_ledger(job_id: str) -> str:
    html = _base_workspace(job_id)
    marker = "</main></html>"
    if marker not in html:
        return html
    return html.replace(marker, _STYLE + _SCRIPT + marker, 1)

lesson_presentation_studio_ui._workspace = _workspace_with_approval_ledger
