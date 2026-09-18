from __future__ import annotations

from . import lesson_presentation_layout_toolkit_ui  # noqa: F401
from . import lesson_presentation_studio_ui

_STYLE = r"""
<style>
.pro-editor{border:1px solid #b2ddff;border-radius:12px;padding:12px;margin:10px 0;background:#f5fbff}
.pro-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:8px}
.pro-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.pro-actions button{width:auto}
.pro-selected{outline:3px solid #2e90fa!important;outline-offset:2px}.pro-grouped{box-shadow:0 0 0 2px #12b76a inset}
.inspector-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}.inspector-grid input{width:100%}
.pro-stage-viewport{overflow:auto;max-height:70vh}.pro-status{font-size:12px;color:#475467;margin-top:7px}
@media(max-width:760px){.pro-grid{grid-template-columns:1fr 1fr}.inspector-grid{grid-template-columns:1fr 1fr}}
</style>
"""

_SCRIPT = r"""
<script>
(()=>{
const form=document.getElementById('editorForm'),stage=document.getElementById('stage');if(!form||!stage)return;
const panel=document.createElement('div');panel.className='pro-editor';panel.innerHTML='<h3 style="margin-top:0">Pro Editor Tools</h3><p class=muted>Multi-select، Group/Ungroup، Align/Distribute، تحريك بالكيبورد، Zoom/Pan، وElement Inspector.</p><div class=pro-grid><label>Zoom <input id=proZoom type=range min=50 max=180 value=100 step=10></label><label>Pan X <input id=proPanX type=range min=-50 max=50 value=0 step=5></label><label>Pan Y <input id=proPanY type=range min=-50 max=50 value=0 step=5></label><label>Selected <span id=proCount>0</span></label></div><div class=pro-actions><button id=proGroup type=button class=secondary>Group</button><button id=proUngroup type=button class=secondary>Ungroup</button><button id=alignLeft type=button class=secondary>Align Left</button><button id=alignCenter type=button class=secondary>Align Center</button><button id=alignRight type=button class=secondary>Align Right</button><button id=alignTop type=button class=secondary>Align Top</button><button id=alignMiddle type=button class=secondary>Align Middle</button><button id=alignBottom type=button class=secondary>Align Bottom</button><button id=distH type=button class=secondary>Distribute H</button><button id=distV type=button class=secondary>Distribute V</button></div><div class=inspector-grid><label>X<input id=insX type=number min=0 max=100 step=.5></label><label>Y<input id=insY type=number min=0 max=100 step=.5></label><label>W<input id=insW type=number min=5 max=100 step=.5></label><label>H<input id=insH type=number min=5 max=100 step=.5></label></div><div id=proStatus class=pro-status>اضغط على عنصر لاختياره. استخدم Ctrl/⌘/Shift لتحديد أكثر من عنصر.</div>';
const toolkit=document.querySelector('.layout-toolkit');if(toolkit)toolkit.parentNode.insertBefore(panel,toolkit.nextSibling);else form.insertBefore(panel,form.firstChild);

const selected=new Set(),count=document.getElementById('proCount'),status=document.getElementById('proStatus'),zoom=document.getElementById('proZoom'),panX=document.getElementById('proPanX'),panY=document.getElementById('proPanY');
const fields={x:document.getElementById('insX'),y:document.getElementById('insY'),w:document.getElementById('insW'),h:document.getElementById('insH')};
function slideObj(){return blueprint?.slides?.[currentSlide]||null}
function design(){let s=slideObj();if(!s)return null;if(!s.design_spec&&typeof ensureDesign==='function')return ensureDesign();return s.design_spec||null}
function editor(){let d=design();if(!d)return null;if(!d.editor)d.editor={grid_size:2.5,snap_to_grid:true,show_guides:true,template_id:'custom',groups:[],layers:{title:{z:3,locked:false},body:{z:2,locked:false},visual:{z:1,locked:false}}};if(!Array.isArray(d.editor.groups))d.editor.groups=[];return d.editor}
function rect(role){return design()?.elements?.[role]||null}
function locked(role){return !!editor()?.layers?.[role]?.locked}
function roles(){return [...selected].filter(r=>rect(r))}
function grouped(role){return (editor()?.groups||[]).some(g=>g.includes(role))}
function refreshSelection(){document.querySelectorAll('#stage .advanced-layer').forEach(el=>{let r=el.dataset.designRole;el.classList.toggle('pro-selected',selected.has(r));el.classList.toggle('pro-grouped',grouped(r));el.onclick=(ev)=>{if(ev.target.classList?.contains('resize-handle'))return;ev.stopPropagation();if(ev.ctrlKey||ev.metaKey||ev.shiftKey){selected.has(r)?selected.delete(r):selected.add(r)}else{selected.clear();selected.add(r)}syncInspector();refreshSelection()}});count.textContent=String(roles().length)}
function syncInspector(){let rs=roles();if(rs.length!==1){Object.values(fields).forEach(f=>f.value='');status.textContent=rs.length?('تم تحديد '+rs.length+' عناصر.'):'لم يتم تحديد عنصر.';return}let r=rect(rs[0]);for(const k of ['x','y','w','h'])fields[k].value=Number(r[k]).toFixed(1);status.textContent=rs[0]+(locked(rs[0])?' · Locked':'')}
function mutate(fn){let rs=roles().filter(r=>!locked(r));if(!rs.length)return;fn(rs);let d=design();if(d)d.layout='custom';markDirty();renderCurrent();refreshSelection();syncInspector()}
function boundsClamp(r){r.w=Math.max(5,Math.min(100,r.w));r.h=Math.max(5,Math.min(100,r.h));r.x=Math.max(0,Math.min(100-r.w,r.x));r.y=Math.max(0,Math.min(100-r.h,r.y))}
for(const k of ['x','y','w','h'])fields[k].onchange=()=>mutate(rs=>{if(rs.length!==1)return;let r=rect(rs[0]),v=Number(fields[k].value);if(Number.isFinite(v))r[k]=v;boundsClamp(r)});
function align(kind){mutate(rs=>{if(rs.length<2)return;let rr=rs.map(rect);if(kind==='left'){let v=Math.min(...rr.map(r=>r.x));rr.forEach(r=>r.x=v)}if(kind==='right'){let v=Math.max(...rr.map(r=>r.x+r.w));rr.forEach(r=>r.x=v-r.w)}if(kind==='center'){let v=rr.reduce((a,r)=>a+r.x+r.w/2,0)/rr.length;rr.forEach(r=>r.x=v-r.w/2)}if(kind==='top'){let v=Math.min(...rr.map(r=>r.y));rr.forEach(r=>r.y=v)}if(kind==='bottom'){let v=Math.max(...rr.map(r=>r.y+r.h));rr.forEach(r=>r.y=v-r.h)}if(kind==='middle'){let v=rr.reduce((a,r)=>a+r.y+r.h/2,0)/rr.length;rr.forEach(r=>r.y=v-r.h/2)}rr.forEach(boundsClamp)})}
function distribute(axis){mutate(rs=>{if(rs.length<3)return;let rr=rs.map(r=>({role:r,r:rect(r)}));rr.sort((a,b)=>axis==='h'?a.r.x-b.r.x:a.r.y-b.r.y);let first=rr[0].r,last=rr[rr.length-1].r;if(axis==='h'){let a=first.x+first.w/2,b=last.x+last.w/2,step=(b-a)/(rr.length-1);rr.forEach((o,i)=>o.r.x=a+i*step-o.r.w/2)}else{let a=first.y+first.h/2,b=last.y+last.h/2,step=(b-a)/(rr.length-1);rr.forEach((o,i)=>o.r.y=a+i*step-o.r.h/2)}rr.forEach(o=>boundsClamp(o.r))})}
document.getElementById('alignLeft').onclick=()=>align('left');document.getElementById('alignCenter').onclick=()=>align('center');document.getElementById('alignRight').onclick=()=>align('right');document.getElementById('alignTop').onclick=()=>align('top');document.getElementById('alignMiddle').onclick=()=>align('middle');document.getElementById('alignBottom').onclick=()=>align('bottom');document.getElementById('distH').onclick=()=>distribute('h');document.getElementById('distV').onclick=()=>distribute('v');
document.getElementById('proGroup').onclick=()=>{let rs=roles();if(rs.length<2)return;let e=editor();e.groups=e.groups.filter(g=>!g.some(r=>rs.includes(r)));e.groups.push(rs.slice().sort());markDirty();renderCurrent();refreshSelection();status.textContent='تم تجميع العناصر المحددة.'};
document.getElementById('proUngroup').onclick=()=>{let rs=roles(),e=editor();e.groups=e.groups.filter(g=>!g.some(r=>rs.includes(r)));markDirty();renderCurrent();refreshSelection();status.textContent='تم فك التجميع.'};
function transformStage(){stage.style.transformOrigin='top left';stage.style.transform='translate('+panX.value+'px,'+panY.value+'px) scale('+(Number(zoom.value)/100)+')';status.textContent='Zoom '+zoom.value+'% · Pan '+panX.value+','+panY.value}
zoom.oninput=transformStage;panX.oninput=transformStage;panY.oninput=transformStage;
stage.addEventListener('click',ev=>{if(ev.target===stage){selected.clear();refreshSelection();syncInspector()}});
window.addEventListener('keydown',ev=>{if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;let dx=0,dy=0,step=ev.shiftKey?2.5:.5;if(ev.key==='ArrowLeft')dx=-step;if(ev.key==='ArrowRight')dx=step;if(ev.key==='ArrowUp')dy=-step;if(ev.key==='ArrowDown')dy=step;if(!dx&&!dy)return;if(!roles().length)return;ev.preventDefault();mutate(rs=>rs.forEach(role=>{let r=rect(role);r.x+=dx;r.y+=dy;boundsClamp(r)}))});
const prevRender=renderCurrent;renderCurrent=function(){prevRender();refreshSelection();syncInspector();transformStage()};
const prevLoad=loadEditor;loadEditor=function(){selected.clear();prevLoad();refreshSelection();syncInspector()};
refreshSelection();syncInspector();
})();
</script>
"""

_base_workspace = lesson_presentation_studio_ui._workspace

def _workspace_with_pro_editor(job_id: str) -> str:
    html = _base_workspace(job_id)
    marker = "</main></html>"
    if marker not in html:
        return html
    return html.replace(marker, _STYLE + _SCRIPT + marker, 1)

lesson_presentation_studio_ui._workspace = _workspace_with_pro_editor
