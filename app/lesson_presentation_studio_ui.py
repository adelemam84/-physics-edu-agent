from __future__ import annotations

import json

from fastapi.responses import HTMLResponse

from . import lesson_pack_studio_ui
from .main import app


_PREVIEW_LINK_ANCHOR = '<div class=box><a href="/admin/lesson-pack-studio">Lesson Pack Studio</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>'


def _enhance_pack_preview(html: str, job_id: str) -> str:
    if _PREVIEW_LINK_ANCHOR not in html:
        return html
    link = (
        _PREVIEW_LINK_ANCHOR[:-6]
        + f' · <a href="/admin/lesson-pack-studio/jobs/{job_id}/presentation">Presentation Studio</a></div>'
    )
    return html.replace(_PREVIEW_LINK_ANCHOR, link, 1)


_base_preview_page = lesson_pack_studio_ui._preview_page


def _preview_page_with_presentation_link(job_id: str) -> str:
    return _enhance_pack_preview(_base_preview_page(job_id), job_id)


lesson_pack_studio_ui._preview_page = _preview_page_with_presentation_link


def _workspace(job_id: str) -> str:
    safe_id = json.dumps(job_id)
    return r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lesson Presentation Studio</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1250px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 2px 12px #0001}.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}select,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:10px;width:100%}button{cursor:pointer;background:#172033;color:#fff}.muted{color:#667085;white-space:pre-wrap}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.actions{display:flex;gap:10px;flex-wrap:wrap}.actions button{width:auto}.pill{display:inline-block;background:#f2f4f7;border-radius:999px;padding:3px 9px;font-size:12px}.features{display:flex;gap:6px;flex-wrap:wrap}.features span{background:#eef4ff;border-radius:999px;padding:4px 8px;font-size:12px}
.viewer{background:#101828;border-radius:18px;padding:12px;position:relative}.stage{aspect-ratio:16/9;background:#fff;border-radius:12px;overflow:auto;padding:5.5%;position:relative;box-shadow:0 14px 42px #0005}.stage h2{font-size:clamp(22px,3vw,42px);margin:0 0 20px}.stage p{font-size:clamp(15px,1.7vw,24px);line-height:1.65}.stage .ref{position:absolute;right:4%;left:4%;bottom:2%;font-size:11px;color:#667085;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.viewer-toolbar{display:flex;align-items:center;gap:8px;justify-content:center;margin-top:10px;flex-wrap:wrap}.viewer-toolbar button{width:auto;min-width:96px;background:#344054}.counter{color:#fff;min-width:100px;text-align:center}.filmstrip{display:flex;gap:8px;overflow:auto;padding:10px 0 2px}.thumb{min-width:150px;width:150px;aspect-ratio:16/9;border:2px solid transparent;border-radius:9px;background:#fff;color:#172033;padding:8px;text-align:right;overflow:hidden}.thumb.active{border-color:#84adff}.thumb strong{font-size:12px;display:block}.thumb small{font-size:10px;color:#667085}.notes{margin-top:10px;border:1px dashed #98a2b3;border-radius:10px;padding:10px;background:#f9fafb}.hidden{display:none!important}.diagram{display:flex;align-items:center;gap:8px;justify-content:center;flex-wrap:wrap;margin:20px 0}.node{border:2px solid #98a2b3;border-radius:12px;padding:12px 16px;min-width:130px;text-align:center;font-weight:700;background:#f8fafc}.arrow{font-size:28px}.table-wrap{overflow:auto}.smart-table{border-collapse:collapse;width:100%;margin-top:16px}.smart-table th,.smart-table td{border:1px solid #d0d5dd;padding:8px;text-align:right}.smart-table th{background:#f2f4f7}.fullscreen-stage:fullscreen{background:#101828;padding:3vh}.fullscreen-stage:fullscreen .stage{height:88vh;aspect-ratio:auto}.fullscreen-stage:fullscreen .filmstrip{display:none}
</style><main>
<div class=box><a href="/admin/lesson-pack-studio/jobs/''' + job_id + r'''/preview">العودة إلى الملزمة</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>
<div class=box><h1>Lesson Presentation Studio</h1><p>حوّل الملزمة الحالية إلى عرض تعليمي Source-Grounded مع معاينة تفاعلية ورسومات قابلة للتحرير داخل PowerPoint.</p><div id=policy class=muted>جارٍ تحميل مواصفات العرض...</div></div>
<div class=box><h2>إعداد العرض</h2><div class=controls>
<label>النمط<select id=mode></select></label><label>الجمهور<select id=audience><option value=student>طالب</option><option value=teacher>مدرس</option><option value=classroom>فصل دراسي</option></select></label><label>اللغة<select id=language><option value=ar>عربي</option><option value=en>English</option><option value=bilingual>عربي + English</option></select></label><label>الطول<select id=length><option value=short>قصير</option><option value=medium selected>متوسط</option><option value=full>كامل</option></select></label><label>القالب<select id=theme><option value=clean_academic>Clean Academic</option><option value=exam_night>Exam Night</option><option value=visual_concept>Visual Concept</option><option value=dark_classroom>Dark Classroom</option></select></label>
</div><p class=actions><button id=generate>إنشاء Blueprint</button><button id=studentPptx>تنزيل Student PPTX</button><button id=teacherPptx>تنزيل Teacher PPTX</button></p><p id=status class=muted>لم يتم إنشاء العرض بعد.</p></div>
<div class=box><h2>معاينة تفاعلية</h2><p class=muted>استخدم الأسهم من لوحة المفاتيح أو الشريط السفلي للتنقل. وضع المدرس يعرض Speaker Notes فقط عند الطلب.</p><div id=viewer class="viewer fullscreen-stage"><div id=stage class=stage><h2>أنشئ Blueprint لبدء المعاينة</h2></div><div class=viewer-toolbar><button id=prevSlide type=button>السابق</button><span id=slideCounter class=counter>— / —</span><button id=nextSlide type=button>التالي</button><button id=toggleNotes type=button>ملاحظات المدرس</button><button id=fullScreen type=button>ملء الشاشة</button></div><div id=filmstrip class=filmstrip></div></div></div>
<div class=box><h2>القدرات المفعلة</h2><div id=features class=features></div></div>
<script>
const id=''' + safe_id + r''';let blueprint=null,currentSlide=0,notesVisible=false;const $=x=>document.getElementById(x);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mode=$('mode'),audience=$('audience'),language=$('language'),length=$('length'),theme=$('theme'),status=$('status'),features=$('features'),policy=$('policy'),stage=$('stage'),filmstrip=$('filmstrip'),slideCounter=$('slideCounter');
function payload(audienceOverride=null){return {mode:mode.value,audience:audienceOverride||audience.value,language:language.value,length:length.value,theme:theme.value,include:{examples:true,laws:true,visuals:true,tables:true,activities:true,checkpoints:true,speaker_notes:(audienceOverride||audience.value)!=='student'}}}
async function boot(){let r=await fetch('/api/admin/lesson-pack-studio/presentation/feature-specs');if(r.status===401){location.href='/admin/login';return}let x=await r.json();mode.innerHTML=x.modes.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');features.innerHTML=x.features.map(f=>'<span>'+f.card+'. '+esc(f.title)+(f.enabled?'':' · مؤجل')+'</span>').join('');policy.textContent='20 بطاقة → '+x.features.length+' مواصفة · بنك الأسئلة الرسمي: معزول · Content Ingestion: بدون تغيير';}
function visualLabels(v){let out=[];['nodes','steps','items','labels'].forEach(k=>{if(Array.isArray(v[k]))v[k].forEach(n=>{let t=typeof n==='object'?(n.label||n.title||n.text):n;if(t)out.push(String(t))})});if(!out.length&&v.description)out=String(v.description).replaceAll('→','|').replaceAll('->','|').split('|').map(x=>x.trim()).filter(Boolean);if(!out.length)out=[v.title||v.kind||'رسم توضيحي'];return out.slice(0,6)}
function renderDiagram(v){let labels=visualLabels(v);return '<div class=diagram>'+labels.map((t,i)=>'<div class=node>'+esc(t)+'</div>'+(i<labels.length-1?'<span class=arrow>←</span>':'')).join('')+'</div><div class=muted>'+esc(v.kind||'diagram')+(v.generated?' · generated_visual':' · source_visual')+'</div>'}
function renderTable(t){let cols=t.columns||[],rows=t.rows||[];if(!cols.length||!rows.length)return '';return '<div class=table-wrap><table class=smart-table><thead><tr>'+cols.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.slice(0,7).map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c]||'')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'}
function renderCurrent(){if(!blueprint||!blueprint.slides||!blueprint.slides.length){stage.innerHTML='<h2>لا توجد شرائح</h2>';return}currentSlide=Math.max(0,Math.min(currentSlide,blueprint.slides.length-1));let s=blueprint.slides[currentSlide];let blocks=(s.content_blocks||[]).filter(b=>audience.value!=='student'||!b.teacher_only);let body=blocks.map(b=>'<p>'+esc(b.text)+'</p>').join('');let visuals=(s.visual_specs||[]).map(renderDiagram).join('');let tables=(s.table_specs||[]).map(renderTable).join('');let notes=(s.speaker_notes||[]).map(n=>'<div>• '+esc(n)+'</div>').join('');stage.innerHTML='<span class=pill>'+esc(s.kind)+'</span><h2>'+esc(s.title)+'</h2>'+body+visuals+tables+(notesVisible&&audience.value!=='student'&&notes?'<div class=notes><b>Speaker Notes</b>'+notes+'</div>':'')+'<div class=ref>'+esc((s.source_refs||[]).join(' · '))+'</div>';slideCounter.textContent=(currentSlide+1)+' / '+blueprint.slides.length;filmstrip.querySelectorAll('.thumb').forEach((el,i)=>el.classList.toggle('active',i===currentSlide));let active=filmstrip.children[currentSlide];if(active)active.scrollIntoView({behavior:'smooth',block:'nearest',inline:'center'});}
function buildFilmstrip(){filmstrip.innerHTML=(blueprint.slides||[]).map((s,i)=>'<button type=button class="thumb '+(i===currentSlide?'active':'')+'" data-i="'+i+'"><strong>'+(i+1)+'. '+esc(s.title)+'</strong><small>'+esc(s.kind)+'</small></button>').join('');filmstrip.querySelectorAll('.thumb').forEach(b=>b.onclick=()=>{currentSlide=Number(b.dataset.i);renderCurrent()})}
function render(x){blueprint=x;currentSlide=0;notesVisible=false;let pre=x.preflight||{};status.className=pre.ready?'ok':'warn';status.textContent=(pre.ready?'✅ Blueprint جاهز':'⛔ يحتاج استكمال')+' · عدد الشرائح: '+(pre.slide_count||0)+(pre.blocking_failures&&pre.blocking_failures.length?' · '+pre.blocking_failures.join('، '):'');buildFilmstrip();renderCurrent()}
$('generate').onclick=async()=>{status.textContent='جارٍ إنشاء Blueprint...';let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/blueprint',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});let x=await r.json();if(!r.ok){status.className='bad';status.textContent=JSON.stringify(x.detail||x);return}render(x)};
$('prevSlide').onclick=()=>{if(blueprint){currentSlide--;renderCurrent()}};$('nextSlide').onclick=()=>{if(blueprint){currentSlide++;renderCurrent()}};$('toggleNotes').onclick=()=>{notesVisible=!notesVisible;renderCurrent()};$('fullScreen').onclick=()=>{let v=$('viewer');if(document.fullscreenElement)document.exitFullscreen();else if(v.requestFullscreen)v.requestFullscreen()};audience.onchange=()=>renderCurrent();
document.addEventListener('keydown',e=>{if(!blueprint)return;if(e.key==='ArrowLeft'){currentSlide++;renderCurrent()}else if(e.key==='ArrowRight'){currentSlide--;renderCurrent()}else if(e.key==='Home'){currentSlide=0;renderCurrent()}else if(e.key==='End'){currentSlide=blueprint.slides.length-1;renderCurrent()}});
async function download(edition){status.textContent='جارٍ تجهيز '+edition+' PPTX...';let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/export-pptx/'+edition,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload(edition))});if(!r.ok){let x=await r.json();status.className='bad';status.textContent=JSON.stringify(x.detail||x);return}let blob=await r.blob();let url=URL.createObjectURL(blob);let a=document.createElement('a');a.href=url;a.download='lesson-presentation-'+edition+'-'+id+'.pptx';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);status.className='ok';status.textContent='✅ تم تجهيز '+edition+' PPTX بنجاح.'}
$('studentPptx').onclick=()=>download('student');$('teacherPptx').onclick=()=>download('teacher');boot();
</script></main></html>'''


@app.get("/admin/lesson-pack-studio/jobs/{job_id}/presentation", response_class=HTMLResponse)
def lesson_presentation_workspace(job_id: str):
    return _workspace(job_id)
