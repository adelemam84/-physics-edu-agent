from __future__ import annotations

import json

from fastapi.responses import HTMLResponse

from . import lesson_pack_studio_ui
from .main import app

_LINK_ANCHOR = '<div class=box><a href="/admin/lesson-pack-studio">Lesson Pack Studio</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>'


def _enhance_preview_link(html: str, job_id: str) -> str:
    if _LINK_ANCHOR not in html:
        return html
    replacement = (
        _LINK_ANCHOR[:-6]
        + f' · <a href="/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup">Source Cleanup Studio</a></div>'
    )
    return html.replace(_LINK_ANCHOR, replacement, 1)


_base_preview_page = lesson_pack_studio_ui._preview_page


def _preview_with_cleanup_link(job_id: str) -> str:
    return _enhance_preview_link(_base_preview_page(job_id), job_id)


lesson_pack_studio_ui._preview_page = _preview_with_cleanup_link


def _cleanup_page(job_id: str) -> str:
    safe_id = json.dumps(job_id)
    return r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Source Cleanup Studio</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1350px;margin:auto;padding:16px}
.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 2px 12px #0001}.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
label{font-size:12px;color:#475467}select,input,button{font:inherit;padding:9px;border:1px solid #ccd2dd;border-radius:9px;width:100%}input[type=checkbox]{width:auto}
button{cursor:pointer}.primary{background:#172033;color:#fff}.secondary{background:#f2f4f7}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions button{width:auto}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:12px}.panel{border:1px solid #e4e7ec;border-radius:12px;padding:10px}.panel img{width:100%;max-height:68vh;object-fit:contain;background:#fafafa;border-radius:8px}
.pages{display:flex;gap:7px;overflow:auto;padding:4px}.pagebtn{width:auto;white-space:nowrap}.active{outline:2px solid #2e90fa}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.muted{color:#667085;white-space:pre-wrap}
.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:8px}.metric{background:#f9fafb;border-radius:10px;padding:8px}.region-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
@media(max-width:800px){.compare{grid-template-columns:1fr}.region-grid{grid-template-columns:1fr 1fr}}
</style><main>
<div class=box><a href="/admin/lesson-pack-studio/jobs/''' + job_id + r'''/preview">العودة لمراجعة Lesson Pack</a> · <a href="/admin/lesson-pack-studio">Lesson Pack Studio</a></div>
<div class=box><h1>Source Cleanup Studio</h1><p>تحسين بصري حتمي وغير توليدي لصفحات الـScan: تنظيف noise، زيادة وضوح النص والجداول والرسومات، مع حفظ الصفحة الأصلية دون تعديل.</p><div id=globalState class=muted>جارٍ التحميل...</div></div>
<div class=box><div id=pages class=pages></div></div>
<div class=box><div class=controls>
<label>Profile<select id=profile><option value=balanced>Balanced</option><option value=text_priority>Text Priority</option><option value=tables_priority>Tables Priority</option><option value=diagrams_priority>Diagrams Priority</option><option value=safe>Low-Noise Safe</option></select></label>
<label>Contrast<input id=contrast type=range min=1 max=1.6 step=.02 value=1.18></label>
<label>Sharpness<input id=sharpness type=range min=1 max=1.8 step=.02 value=1.22></label>
<label>Background Cleanup<input id=background type=range min=0 max=.45 step=.01 value=.22></label>
<label>Bleed-through Reduction<input id=bleed type=range min=0 max=.35 step=.01 value=.12></label>
<label><input id=deskew type=checkbox> Auto Deskew</label>
<label><input id=regionAware type=checkbox checked> Region-aware safe enhancement</label>
</div>
<details style="margin-top:10px"><summary>Manual Rescue Region</summary><p class=muted>اختياري: طبّق التحسين على جزء محدد فقط دون لمس باقي الصفحة. القيم نسبية من 0 إلى 1.</p><div class=region-grid><input id=rx type=number min=0 max=.97 step=.01 placeholder="x"><input id=ry type=number min=0 max=.97 step=.01 placeholder="y"><input id=rw type=number min=.03 max=1 step=.01 placeholder="width"><input id=rh type=number min=.03 max=1 step=.01 placeholder="height"></div></details>
<div class=actions style="margin-top:12px"><button id=analyze>Analyze</button><button id=enhance class=primary>Auto Enhance</button><button id=approve>اعتماد التحسين</button><button id=verifyOcr>OCR Before/After</button><button id=remove>حذف النسخة المحسنة</button><button id=batch>Batch للصفحات منخفضة الجودة</button></div><div id=state class=muted style="margin-top:10px"></div></div>
<div class=box><h2>Quality & Fidelity</h2><div id=metrics class=metric-grid></div></div>
<div class=box><div class=compare><div class=panel><h3>Original</h3><img id=original alt="Original source"></div><div class=panel><h3>Visual Enhanced</h3><img id=visual alt="Enhanced page"></div><div class=panel><h3>OCR Enhanced</h3><img id=ocr alt="OCR enhanced page"></div><div class=panel><h3>Difference Overlay</h3><img id=diff alt="Difference overlay"></div></div></div>
<div class=box><h2>OCR Verification</h2><pre id=ocrResult class=muted>لم يتم تشغيل مقارنة OCR بعد.</pre></div>
<script>
const id=''' + safe_id + r''';let data=null,current=null;
const $=x=>document.getElementById(x),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function pageUrl(variant){return '/api/admin/lesson-pack-studio/jobs/'+encodeURIComponent(id)+'/source-cleanup/pages/'+current.id+'/preview/'+variant+'?t='+Date.now()}
function params(){let region=null;let vals=[$('rx').value,$('ry').value,$('rw').value,$('rh').value];if(vals.every(v=>v!==''))region={x:Number(vals[0]),y:Number(vals[1]),width:Number(vals[2]),height:Number(vals[3])};return {contrast:Number($('contrast').value),sharpness:Number($('sharpness').value),background_cleanup:Number($('background').value),bleed_reduction:Number($('bleed').value),deskew:$('deskew').checked,region_aware:$('regionAware').checked,region}}
function setPreset(){let p=$('profile').value,m={safe:[1.08,1.08,.10,.05],balanced:[1.18,1.22,.22,.12],text_priority:[1.28,1.34,.30,.18],tables_priority:[1.24,1.40,.20,.10],diagrams_priority:[1.18,1.45,.15,.05]}[p];if(m){$('contrast').value=m[0];$('sharpness').value=m[1];$('background').value=m[2];$('bleed').value=m[3]}}
function metric(name,val){return '<div class=metric><b>'+esc(name)+'</b><div>'+esc(val)+'</div></div>'}
function renderMetrics(enh){if(!enh){$('metrics').innerHTML='<div class=muted>شغّل Analyze أو Enhance.</div>';return}let b=enh.metrics_before||{},a=enh.metrics_after||{},f=enh.fidelity||{};$('metrics').innerHTML=metric('Before overall',b.overall??'—')+metric('After overall',a.overall??'—')+metric('Contrast',a.contrast??b.contrast??'—')+metric('Sharpness',a.sharpness??b.sharpness??'—')+metric('Noise cleanliness',a.noise_cleanliness??b.noise_cleanliness??'—')+metric('Edge overlap',f.edge_overlap_percent!=null?f.edge_overlap_percent+'%':'—')+metric('Fidelity',f.passed===true?'PASS':f.passed===false?'REVIEW':'—')+metric('Generative content','No')}
function renderPage(){if(!current)return;document.querySelectorAll('.pagebtn').forEach(b=>b.classList.toggle('active',Number(b.dataset.id)===Number(current.id)));$('original').src=pageUrl('original');let e=current.enhancement;if(e&&e.has_visual){$('visual').src=pageUrl('visual');$('ocr').src=pageUrl('ocr');$('diff').src=pageUrl('diff');$('state').className=e.teacher_approved?'ok':'warn';$('state').textContent=(e.teacher_approved?'✓ التحسين معتمد.':'التحسين غير معتمد.')+' · Profile: '+e.profile}else{$('visual').removeAttribute('src');$('ocr').removeAttribute('src');$('diff').removeAttribute('src');$('state').className='muted';$('state').textContent='لا توجد نسخة محسنة بعد.'}renderMetrics(e)}
async function load(){let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+encodeURIComponent(id)+'/source-cleanup');if(r.status===401){location.href='/admin/login';return}data=await r.json();$('globalState').textContent='الصفحات: '+data.pages.length+' · المعالجة: Non-generative · الأصل محفوظ دائمًا · بنك الأسئلة الرسمي: معزول';$('pages').innerHTML=data.pages.map(p=>'<button class=pagebtn data-id="'+p.id+'>'+p.position+'. '+esc(p.filename)+(p.enhancement?.teacher_approved?' ✓':'')+'</button>').join('');$('pages').querySelectorAll('button').forEach(b=>b.onclick=()=>{current=data.pages.find(p=>Number(p.id)===Number(b.dataset.id));renderPage()});if(!current&&data.pages.length)current=data.pages[0];else if(current)current=data.pages.find(p=>Number(p.id)===Number(current.id))||data.pages[0];renderPage()}
async function post(path,body){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});let x=await r.json();if(!r.ok)throw new Error(JSON.stringify(x.detail||x));return x}
$('profile').onchange=setPreset;
$('analyze').onclick=async()=>{if(!current)return;$('state').textContent='جارٍ تحليل الجودة...';try{let x=await post('/api/admin/lesson-pack-studio/jobs/'+id+'/source-cleanup/pages/'+current.id+'/analyze',{});renderMetrics({metrics_before:x.metrics,fidelity:{}});$('profile').value=x.suggested_profile;$('state').className=x.needs_cleanup?'warn':'ok';$('state').textContent='Quality '+x.metrics.overall+'/100 · Suggested: '+x.suggested_profile;setPreset()}catch(e){$('state').className='bad';$('state').textContent=e.message}};
$('enhance').onclick=async()=>{if(!current)return;$('state').textContent='جارٍ تحسين الصفحة بدون توليد محتوى...';try{let x=await post('/api/admin/lesson-pack-studio/jobs/'+id+'/source-cleanup/pages/'+current.id+'/enhance',{profile:$('profile').value,params:params()});$('state').className=x.fidelity.passed?'ok':'warn';$('state').textContent='تم التحسين · Fidelity '+(x.fidelity.passed?'PASS':'REVIEW')+' · الأصل لم يتغير.';await load()}catch(e){$('state').className='bad';$('state').textContent=e.message}};
$('approve').onclick=async()=>{if(!current)return;try{let x=await post('/api/admin/lesson-pack-studio/jobs/'+id+'/source-cleanup/pages/'+current.id+'/approve',{approved:true});$('state').className='ok';$('state').textContent='✓ تم اعتماد النسخة المحسنة. OCR سيستخدمها فقط عندما تكون معتمدة.';await load()}catch(e){$('state').className='bad';$('state').textContent=e.message}};
$('verifyOcr').onclick=async()=>{if(!current)return;$('ocrResult').textContent='جارٍ تشغيل OCR على النسخة المحسنة...';try{let x=await post('/api/admin/lesson-pack-studio/jobs/'+id+'/source-cleanup/pages/'+current.id+'/verify-ocr');$('ocrResult').textContent=JSON.stringify(x,null,2)}catch(e){$('ocrResult').textContent='خطأ: '+e.message}};
$('remove').onclick=async()=>{if(!current||!confirm('حذف النسخ المحسنة فقط؟ الصفحة الأصلية لن تُحذف.'))return;let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/source-cleanup/pages/'+current.id,{method:'DELETE'});let x=await r.json();if(!r.ok){$('state').textContent=JSON.stringify(x.detail||x);return}await load()};
$('batch').onclick=async()=>{if(!confirm('تطبيق الإعداد الحالي على حتى 12 صفحة منخفضة الجودة؟'))return;$('state').textContent='جارٍ Batch Enhancement...';try{let x=await post('/api/admin/lesson-pack-studio/jobs/'+id+'/source-cleanup/batch-enhance',{profile:$('profile').value,params:params(),only_low_quality:true});$('state').className='ok';$('state').textContent='تمت معالجة '+x.processed+' صفحة/نتيجة.';await load()}catch(e){$('state').className='bad';$('state').textContent=e.message}};
load();
</script></main></html>'''


@app.get(
    "/admin/lesson-pack-studio/jobs/{job_id}/source-cleanup",
    response_class=HTMLResponse,
)
def source_cleanup_workspace(job_id: str):
    return _cleanup_page(job_id)
