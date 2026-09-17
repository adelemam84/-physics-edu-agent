from __future__ import annotations

from . import lesson_presentation_studio_ui


_STYLE = r"""
<style>
.productivity-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}.productivity-bar button{width:auto}.draft-state{font-size:13px;color:#667085}.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.compare-card{border:1px solid #e4e7ec;border-radius:12px;padding:10px;background:#fff}.compare-card h4{margin:0 0 8px}.compare-body{white-space:pre-wrap;max-height:220px;overflow:auto;font-size:13px}.table-editor{border:1px solid #e4e7ec;border-radius:10px;padding:10px;margin:8px 0;overflow:auto}.table-editor table{border-collapse:collapse;width:100%;min-width:520px}.table-editor th,.table-editor td{border:1px solid #d0d5dd;padding:6px}.table-editor input{min-width:120px}.source-lock{font-size:11px;color:#667085}.productivity-badge{display:inline-block;padding:3px 8px;border-radius:999px;background:#ecfdf3;color:#067647;font-size:12px}@media(max-width:760px){.compare-grid{grid-template-columns:1fr}}
</style>
"""

_SCRIPT = r"""
<script>
(()=>{
const editorBox=document.getElementById('editorBox');if(!editorBox)return;
const productivity=document.createElement('div');productivity.className='validation';productivity.innerHTML='<div class="productivity-bar"><button id=undoEdit type=button class=secondary disabled>↶ تراجع</button><button id=redoEdit type=button class=secondary disabled>↷ إعادة</button><button id=duplicateSlide type=button class=secondary disabled>نسخ الشريحة</button><button id=clearDraft type=button class=secondary disabled>مسح المسودة</button><span class=productivity-badge>Autosave Draft</span><span id=draftState class=draft-state>لا توجد مسودة محفوظة.</span></div><div class=compare-grid><div class=compare-card><h4>قبل التعديل</h4><div id=compareBefore class=compare-body>—</div></div><div class=compare-card><h4>بعد التعديل</h4><div id=compareAfter class=compare-body>—</div></div></div>';
editorBox.insertBefore(productivity,editorBox.children[2]||null);
const notesField=document.getElementById('editNotes')?.closest('.field');if(notesField){const tf=document.createElement('div');tf.className='field';tf.innerHTML='<label>Smart Tables</label><div id=editTables class=muted>لا توجد جداول في هذه الشريحة.</div>';notesField.parentNode.insertBefore(tf,notesField)}
const undoBtn=document.getElementById('undoEdit'),redoBtn=document.getElementById('redoEdit'),duplicateBtn=document.getElementById('duplicateSlide'),clearDraftBtn=document.getElementById('clearDraft'),draftState=document.getElementById('draftState'),beforeBox=document.getElementById('compareBefore'),afterBox=document.getElementById('compareAfter');
let undoStack=[],redoStack=[],lastSnapshot=null,suspendHistory=false,draftTimer=null;const MAX_HISTORY=50;
const canonical=x=>JSON.stringify(x||null);const draftKey=()=>editorBaseHash?'lesson-presentation-draft:'+id+':'+editorBaseHash:'';
function safeStorage(op,key,value){try{if(op==='get')return localStorage.getItem(key);if(op==='set')localStorage.setItem(key,value);if(op==='remove')localStorage.removeItem(key)}catch(_){return null}}
function visibleText(s){if(!s)return '—';let lines=[s.title||''];(s.content_blocks||[]).forEach(b=>{if(b&&b.text)lines.push('• '+b.text)});(s.table_specs||[]).forEach((t,i)=>{lines.push('جدول '+(i+1)+':');(t.rows||[]).slice(0,4).forEach(r=>lines.push('  '+(t.columns||[]).map(c=>String(r[c]??'')).join(' | ')))});return lines.join('\n')}
function renderComparison(){if(!blueprint||!blueprint.slides?.length){beforeBox.textContent='—';afterBox.textContent='—';return}let s=blueprint.slides[currentSlide],base=(baseBlueprint?.slides||[]).find(x=>x.slide_id===s.slide_id);if(!base&&s.duplicate_of)base=(baseBlueprint?.slides||[]).find(x=>x.slide_id===s.duplicate_of);beforeBox.textContent=(s.duplicate_of?'[الأصل الذي نُسخت منه]\n':'')+visibleText(base);afterBox.textContent=(s.duplicate_of?'[نسخة جديدة]\n':'')+visibleText(s)}
function hasDraft(){let k=draftKey();return !!(k&&safeStorage('get',k))}
function updateTools(){undoBtn.disabled=!undoStack.length;redoBtn.disabled=!redoStack.length;duplicateBtn.disabled=!blueprint||!blueprint.slides?.length||blueprint.slides.length>=40;clearDraftBtn.disabled=!hasDraft();if(!blueprint){draftState.textContent='لا توجد مسودة محفوظة.';return}draftState.textContent=hasDraft()?'المسودة محفوظة تلقائيًا على هذا المتصفح.':'لا توجد مسودة محفوظة.'}
function saveDraftNow(){let k=draftKey();if(!k||!blueprint||!dirty){if(k&&!dirty)safeStorage('remove',k);updateTools();return}let doc={version:1,job_id:id,base_hash:editorBaseHash,saved_at:new Date().toISOString(),current_slide:currentSlide,blueprint:blueprint};safeStorage('set',k,JSON.stringify(doc));draftState.textContent='تم الحفظ تلقائيًا · '+new Date().toLocaleTimeString('ar-EG');clearDraftBtn.disabled=false}
function scheduleDraft(){clearTimeout(draftTimer);draftTimer=setTimeout(saveDraftNow,250)}
function recomputeDirty(){dirty=!!(blueprint&&baseBlueprint&&canonical(blueprint)!==canonical(baseBlueprint));validationDigest='';teacherReapproved=false;updateEditState();if(!dirty){let k=draftKey();if(k)safeStorage('remove',k)}}
function setDeck(next,index){suspendHistory=true;blueprint=clone(next);currentSlide=Math.max(0,Math.min(index??currentSlide,(blueprint.slides?.length||1)-1));recomputeDirty();buildFilmstrip();renderCurrent();lastSnapshot=clone(blueprint);suspendHistory=false;scheduleDraft();updateTools()}
const baseMarkDirty=markDirty;markDirty=function(){baseMarkDirty();if(!suspendHistory&&blueprint){let now=canonical(blueprint);if(lastSnapshot&&canonical(lastSnapshot)!==now){undoStack.push(lastSnapshot);if(undoStack.length>MAX_HISTORY)undoStack.shift();redoStack=[]}lastSnapshot=clone(blueprint)}scheduleDraft();updateTools();renderComparison()};
const baseRenderCurrent=renderCurrent;renderCurrent=function(){baseRenderCurrent();renderComparison();updateTools()};
function renderTableEditor(){let root=document.getElementById('editTables');if(!root)return;let s=blueprint?.slides?.[currentSlide],tables=s?.table_specs||[];if(!tables.length){root.className='muted';root.innerHTML='لا توجد جداول في هذه الشريحة.';return}root.className='';root.innerHTML=tables.map((t,ti)=>{let cols=t.columns||[],rows=t.rows||[];return '<div class=table-editor data-ti="'+ti+'"><b>'+esc(t.kind||('جدول '+(ti+1)))+'</b><table><thead><tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.map((r,ri)=>'<tr>'+cols.map(c=>'<td><input data-table-cell="1" data-ti="'+ti+'" data-ri="'+ri+'" data-col="'+esc(c)+'" value="'+esc(r[c]??'')+'"></td>').join('')+'</tr>').join('')+'</tbody></table><div class=source-lock>🔒 بنية الجدول، أسماء الأعمدة ومراجع المصدر غير قابلة للتغيير.</div></div>'}).join('')}
const baseLoadEditor=loadEditor;loadEditor=function(){baseLoadEditor();renderTableEditor();duplicateBtn.disabled=!blueprint||!blueprint.slides?.length||blueprint.slides.length>=40};
const originalApply=document.getElementById('applySlide').onclick;document.getElementById('applySlide').onclick=()=>{let s=blueprint?.slides?.[currentSlide];if(s){document.querySelectorAll('[data-table-cell="1"]').forEach(el=>{let ti=Number(el.dataset.ti),ri=Number(el.dataset.ri),col=el.dataset.col,t=s.table_specs?.[ti],r=t?.rows?.[ri];if(r&&Object.prototype.hasOwnProperty.call(r,col))r[col]=el.value.trim()})}originalApply&&originalApply()};
const baseRender=render;render=function(x){baseRender(x);undoStack=[];redoStack=[];lastSnapshot=clone(blueprint);let k=draftKey(),raw=k&&safeStorage('get',k);if(raw){try{let d=JSON.parse(raw);if(d&&d.base_hash===editorBaseHash&&d.blueprint?.deck_id===blueprint?.deck_id){blueprint=clone(d.blueprint);currentSlide=Math.max(0,Math.min(Number(d.current_slide)||0,blueprint.slides.length-1));dirty=true;validationDigest='';teacherReapproved=false;lastSnapshot=clone(blueprint);buildFilmstrip();renderCurrent();updateEditState();validationResult.className='warn';validationResult.textContent='↻ تمت استعادة المسودة المحفوظة تلقائيًا. يلزم الفحص وإعادة اعتماد المدرس قبل التصدير.'}}catch(_){safeStorage('remove',k)}}renderComparison();updateTools()};
undoBtn.onclick=()=>{if(!undoStack.length||!blueprint)return;redoStack.push(clone(blueprint));setDeck(undoStack.pop(),currentSlide)};redoBtn.onclick=()=>{if(!redoStack.length||!blueprint)return;undoStack.push(clone(blueprint));setDeck(redoStack.pop(),currentSlide)};
duplicateBtn.onclick=()=>{if(!blueprint||!blueprint.slides?.length||blueprint.slides.length>=40)return;let s=blueprint.slides[currentSlide],root=s.duplicate_of||s.slide_id,a=new Uint32Array(2);crypto.getRandomValues(a);let hex=Array.from(a).map(n=>n.toString(16).padStart(8,'0')).join('');let copy=clone(s);copy.slide_id='dup-'+String(root).slice(0,72)+'-'+hex;copy.duplicate_of=root;copy.title=(copy.title||'شريحة')+' — نسخة';copy.hidden=false;blueprint.slides.splice(currentSlide+1,0,copy);blueprint.slides.forEach((x,i)=>x.order=i+1);currentSlide++;markDirty();buildFilmstrip();renderCurrent()};
clearDraftBtn.onclick=()=>{let k=draftKey();if(k)safeStorage('remove',k);draftState.textContent='تم مسح المسودة المحفوظة.';updateTools()};
const oldReset=document.getElementById('resetDeck').onclick;document.getElementById('resetDeck').onclick=()=>{oldReset&&oldReset();undoStack=[];redoStack=[];lastSnapshot=blueprint?clone(blueprint):null;let k=draftKey();if(k)safeStorage('remove',k);renderComparison();updateTools()};
window.addEventListener('beforeunload',()=>{if(dirty)saveDraftNow()});
updateTools();renderComparison();
})();
</script>
"""


_base_workspace = lesson_presentation_studio_ui._workspace


def _workspace_with_productivity(job_id: str) -> str:
    html = _base_workspace(job_id)
    marker = "</main></html>"
    if marker not in html:
        return html
    return html.replace(marker, _STYLE + _SCRIPT + marker, 1)


lesson_presentation_studio_ui._workspace = _workspace_with_productivity
