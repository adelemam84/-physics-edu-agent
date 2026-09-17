from __future__ import annotations

from . import lesson_presentation_editor_productivity_ui  # noqa: F401
from . import lesson_presentation_studio_ui

_STYLE = r"""
<style>
.design-panel{border:1px solid #d0d5dd;border-radius:12px;padding:12px;margin:10px 0;background:#fcfcfd}.design-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}.design-grid label{font-size:13px;font-weight:700}.design-grid input,.design-grid select{margin-top:5px}.design-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.design-actions button{width:auto}.drag-on{background:#7f56d9!important}.advanced-layer{border:1px dashed transparent}.drag-on-stage .advanced-layer{border-color:#7f56d9;cursor:move}.drag-on-stage .advanced-layer:before{content:attr(data-role-label);position:absolute;top:2px;left:4px;font-size:9px;color:#7f56d9;background:#fff;padding:1px 4px;border-radius:4px;z-index:4}.design-readout{font-size:12px;color:#667085;margin-top:8px}.stage.design-active{overflow:hidden}.stage .advanced-title-layer,.stage .advanced-body-layer,.stage .advanced-visual-layer{position:absolute;overflow:auto;padding:4px;z-index:2}.stage .advanced-title-layer h2{margin:0}.stage .advanced-body-layer p{margin:0 0 8px}.stage .advanced-visual-layer .diagram{margin:0}.stage .advanced-visual-layer .table-wrap{height:100%}.stage .advanced-visual-layer .smart-table{margin-top:0}.stage .ref{z-index:5}@media(max-width:760px){.design-grid{grid-template-columns:1fr 1fr}}
</style>
"""

_SCRIPT = r"""
<script>
(()=>{
const form=document.getElementById('editorForm');if(!form)return;
const panel=document.createElement('div');panel.className='design-panel';panel.innerHTML=`<h3 style="margin-top:0">Advanced Slide Design</h3><p class=muted>اختر Layout أو حرّك عناصر الشريحة بالسحب. كل تعديل تصميم يخضع للفحص وإعادة اعتماد المدرس قبل التصدير.</p><div class=design-grid>
<label>Layout<select id=designLayout><option value=standard>Standard</option><option value=title_left>Title Left</option><option value=two_column>Two Column</option><option value=visual_focus>Visual Focus</option><option value=split_40_60>Split 40/60</option><option value=custom>Custom</option></select></label>
<label>الخط<select id=designFont><option>Aptos</option><option>Arial</option><option>Noto Sans Arabic</option></select></label>
<label>محاذاة العنوان<select id=designTitleAlign><option value=right>يمين</option><option value=center>وسط</option><option value=left>يسار</option></select></label>
<label>محاذاة النص<select id=designBodyAlign><option value=right>يمين</option><option value=center>وسط</option><option value=left>يسار</option></select></label>
<label>الخلفية<input id=designBackground type=color value=#ffffff></label><label>Accent<input id=designAccent type=color value=#344054></label><label>لون العنوان<input id=designTitleColor type=color value=#172033></label><label>لون النص<input id=designTextColor type=color value=#344054></label>
<label>حجم المحتوى <span id=designScaleValue>100%</span><input id=designScale type=range min=75 max=135 value=100 step=5></label></div>
<div class=design-actions><button id=applyDesign type=button>تطبيق التصميم</button><button id=dragDesign type=button class=secondary>وضع السحب</button><button id=resetDesign type=button class=secondary>إرجاع التصميم</button></div><div id=designReadout class=design-readout>مواضع العناصر محفوظة كنسب داخل الشريحة.</div>`;
const titleField=document.getElementById('editTitle')?.closest('.field');if(titleField)titleField.parentNode.insertBefore(panel,titleField.nextSibling);else form.insertBefore(panel,form.firstChild);
const stage=document.getElementById('stage');const layout=document.getElementById('designLayout'),font=document.getElementById('designFont'),titleAlign=document.getElementById('designTitleAlign'),bodyAlign=document.getElementById('designBodyAlign'),bg=document.getElementById('designBackground'),accent=document.getElementById('designAccent'),titleColor=document.getElementById('designTitleColor'),textColor=document.getElementById('designTextColor'),scale=document.getElementById('designScale'),scaleValue=document.getElementById('designScaleValue'),applyBtn=document.getElementById('applyDesign'),dragBtn=document.getElementById('dragDesign'),resetBtn=document.getElementById('resetDesign'),readout=document.getElementById('designReadout');
let dragMode=false,dragState=null;
const defaults=()=>({layout:'standard',theme:{background:'#FFFFFF',accent:'#344054',title_color:'#172033',text_color:'#344054',font_family:'Aptos',content_scale:1,title_align:'right',body_align:'right'},elements:{title:{x:6,y:5,w:88,h:13},body:{x:6,y:21,w:88,h:28},visual:{x:10,y:52,w:80,h:34}}});
const layouts={standard:{title:{x:6,y:5,w:88,h:13},body:{x:6,y:21,w:88,h:28},visual:{x:10,y:52,w:80,h:34}},title_left:{title:{x:52,y:8,w:42,h:20},body:{x:52,y:32,w:42,h:52},visual:{x:5,y:12,w:42,h:72}},two_column:{title:{x:6,y:5,w:88,h:13},body:{x:52,y:23,w:42,h:62},visual:{x:5,y:23,w:42,h:62}},visual_focus:{title:{x:6,y:4,w:88,h:12},body:{x:8,y:76,w:84,h:18},visual:{x:8,y:19,w:84,h:53}},split_40_60:{title:{x:6,y:5,w:88,h:13},body:{x:44,y:22,w:50,h:64},visual:{x:5,y:22,w:35,h:64}}};
function current(){return blueprint?.slides?.[currentSlide]||null}function ensure(){let s=current();if(!s)return null;if(!s.design_spec)s.design_spec=defaults();if(!s.design_spec.theme)s.design_spec.theme=defaults().theme;if(!s.design_spec.elements)s.design_spec.elements=defaults().elements;return s.design_spec}
function setControls(){let d=ensure();if(!d)return;layout.value=d.layout||'standard';let t=d.theme||{};font.value=t.font_family||'Aptos';titleAlign.value=t.title_align||'right';bodyAlign.value=t.body_align||'right';bg.value=(t.background||'#FFFFFF').toLowerCase();accent.value=(t.accent||'#344054').toLowerCase();titleColor.value=(t.title_color||'#172033').toLowerCase();textColor.value=(t.text_color||'#344054').toLowerCase();scale.value=Math.round(Number(t.content_scale||1)*100);scaleValue.textContent=scale.value+'%';updateReadout()}
function updateReadout(){let d=current()?.design_spec;if(!d){readout.textContent='التصميم الافتراضي.';return}let e=d.elements||{};readout.textContent=['title','body','visual'].map(k=>{let r=e[k]||{};return k+': '+Math.round(r.x||0)+','+Math.round(r.y||0)+' · '+Math.round(r.w||0)+'×'+Math.round(r.h||0)}).join(' | ')}
function applyPreset(d,name){if(layouts[name])d.elements=clone(layouts[name]);d.layout=name}
function captureControls(){let d=ensure();if(!d)return;let chosen=layout.value;if(chosen!=='custom')applyPreset(d,chosen);else d.layout='custom';d.theme={background:bg.value.toUpperCase(),accent:accent.value.toUpperCase(),title_color:titleColor.value.toUpperCase(),text_color:textColor.value.toUpperCase(),font_family:font.value,content_scale:Number(scale.value)/100,title_align:titleAlign.value,body_align:bodyAlign.value};markDirty();renderCurrent();setControls()}
function styleLayer(el,rect,role,d){if(!el)return;el.classList.add('advanced-layer');el.dataset.designRole=role;el.dataset.roleLabel=role;Object.assign(el.style,{left:rect.x+'%',top:rect.y+'%',width:rect.w+'%',height:rect.h+'%',position:'absolute',boxSizing:'border-box'});let t=d.theme||{};el.style.fontFamily=t.font_family||'Aptos';if(role==='title'){el.style.color=t.title_color||'#172033';el.style.textAlign=t.title_align||'right'}else{el.style.color=t.text_color||'#344054';el.style.textAlign=t.body_align||'right';el.style.fontSize=(Number(t.content_scale||1)*100)+'%'}}
function applyStageDesign(){let s=current();if(!s||!stage)return;let d=s.design_spec;if(!d){stage.classList.remove('design-active','drag-on-stage');stage.style.background='';return}let direct=[...stage.children],title=stage.querySelector(':scope > h2'),ref=stage.querySelector(':scope > .ref'),notes=stage.querySelector(':scope > .notes');let visualNodes=direct.filter(x=>x.classList?.contains('diagram')||x.classList?.contains('table-wrap')||(x.classList?.contains('muted')&&direct.some(v=>v.classList?.contains('diagram'))));let bodyNodes=direct.filter(x=>x!==title&&x!==ref&&x!==notes&&!visualNodes.includes(x));let body=document.createElement('div');body.className='advanced-body-layer';bodyNodes.forEach(n=>body.appendChild(n));if(body.childNodes.length)stage.appendChild(body);let visual=document.createElement('div');visual.className='advanced-visual-layer';visualNodes.forEach(n=>visual.appendChild(n));if(visual.childNodes.length)stage.appendChild(visual);if(title){let wrap=document.createElement('div');wrap.className='advanced-title-layer';title.parentNode.insertBefore(wrap,title);wrap.appendChild(title);title=wrap}stage.classList.add('design-active');stage.classList.toggle('drag-on-stage',dragMode);stage.style.background=d.theme?.background||'#FFFFFF';styleLayer(title,d.elements?.title||defaults().elements.title,'title',d);styleLayer(body.childNodes.length?body:null,d.elements?.body||defaults().elements.body,'body',d);styleLayer(visual.childNodes.length?visual:null,d.elements?.visual||defaults().elements.visual,'visual',d);[title,body,visual].filter(Boolean).forEach(el=>{el.onpointerdown=beginDrag});updateReadout()}
function beginDrag(ev){if(!dragMode||!current())return;let role=ev.currentTarget.dataset.designRole;if(!role)return;ev.preventDefault();let d=ensure(),r=d.elements[role],box=stage.getBoundingClientRect();dragState={role,startX:ev.clientX,startY:ev.clientY,x:r.x,y:r.y,box,el:ev.currentTarget};ev.currentTarget.setPointerCapture?.(ev.pointerId)}
window.addEventListener('pointermove',ev=>{if(!dragState)return;let dx=(ev.clientX-dragState.startX)/dragState.box.width*100,dy=(ev.clientY-dragState.startY)/dragState.box.height*100,r=ensure().elements[dragState.role];r.x=Math.max(0,Math.min(100-r.w,dragState.x+dx));r.y=Math.max(0,Math.min(100-r.h,dragState.y+dy));dragState.el.style.left=r.x+'%';dragState.el.style.top=r.y+'%';ensure().layout='custom';layout.value='custom';updateReadout()});
window.addEventListener('pointerup',()=>{if(!dragState)return;dragState=null;markDirty();updateReadout()});
applyBtn.onclick=captureControls;dragBtn.onclick=()=>{dragMode=!dragMode;dragBtn.classList.toggle('drag-on',dragMode);dragBtn.textContent=dragMode?'إنهاء السحب':'وضع السحب';applyStageDesign()};resetBtn.onclick=()=>{let s=current();if(!s)return;delete s.design_spec;markDirty();renderCurrent();setControls()};scale.oninput=()=>scaleValue.textContent=scale.value+'%';layout.onchange=()=>{if(layout.value!=='custom'){let d=ensure();applyPreset(d,layout.value);renderCurrent();updateReadout()}};
const oldRenderCurrent=renderCurrent;renderCurrent=function(){oldRenderCurrent();applyStageDesign()};const oldLoadEditor=loadEditor;loadEditor=function(){oldLoadEditor();setControls()};
setControls();applyStageDesign();
})();
</script>
"""

_base_workspace = lesson_presentation_studio_ui._workspace


def _workspace_with_advanced_design(job_id: str) -> str:
    html = _base_workspace(job_id)
    marker = "</main></html>"
    if marker not in html:
        return html
    return html.replace(marker, _STYLE + _SCRIPT + marker, 1)


lesson_presentation_studio_ui._workspace = _workspace_with_advanced_design
