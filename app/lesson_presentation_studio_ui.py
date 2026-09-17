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
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 2px 12px #0001}.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}select,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:10px;width:100%}button{cursor:pointer;background:#172033;color:#fff}.slides{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.slide{border:1px solid #e4e7ec;border-radius:14px;padding:14px;background:#fcfcfd}.slide h3{margin-top:0}.muted{color:#667085;white-space:pre-wrap}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.actions{display:flex;gap:10px;flex-wrap:wrap}.actions button{width:auto}.pill{display:inline-block;background:#f2f4f7;border-radius:999px;padding:3px 9px;font-size:12px}.features{display:flex;gap:6px;flex-wrap:wrap}.features span{background:#eef4ff;border-radius:999px;padding:4px 8px;font-size:12px}
</style><main>
<div class=box><a href="/admin/lesson-pack-studio/jobs/''' + job_id + r'''/preview">العودة إلى الملزمة</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>
<div class=box><h1>Lesson Presentation Studio</h1><p>حوّل الملزمة الحالية إلى مخطط عرض تعليمي Source-Grounded. كل شريحة تحتفظ بمراجع المصدر، وأسئلة العرض تظل تدريبية وغير رسمية.</p><div id=policy class=muted>جارٍ تحميل مواصفات العرض...</div></div>
<div class=box><h2>إعداد العرض</h2><div class=controls>
<label>النمط<select id=mode></select></label><label>الجمهور<select id=audience><option value=student>طالب</option><option value=teacher>مدرس</option><option value=classroom>فصل دراسي</option></select></label><label>اللغة<select id=language><option value=ar>عربي</option><option value=en>English</option><option value=bilingual>عربي + English</option></select></label><label>الطول<select id=length><option value=short>قصير</option><option value=medium selected>متوسط</option><option value=full>كامل</option></select></label><label>القالب<select id=theme><option value=clean_academic>Clean Academic</option><option value=exam_night>Exam Night</option><option value=visual_concept>Visual Concept</option><option value=dark_classroom>Dark Classroom</option></select></label>
</div><p class=actions><button id=generate>إنشاء Blueprint</button><button id=studentPptx>تنزيل Student PPTX</button><button id=teacherPptx>تنزيل Teacher PPTX</button></p><p id=status class=muted>لم يتم إنشاء العرض بعد.</p></div>
<div class=box><h2>القدرات المفعلة</h2><div id=features class=features></div></div>
<div class=box><h2>معاينة الشرائح</h2><div id=slides class=slides></div></div>
<script>
const id=''' + safe_id + r''';let blueprint=null;const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function payload(audienceOverride=null){return {mode:mode.value,audience:audienceOverride||audience.value,language:language.value,length:length.value,theme:theme.value,include:{examples:true,laws:true,visuals:true,tables:true,activities:true,checkpoints:true,speaker_notes:(audienceOverride||audience.value)!=='student'}}}
async function boot(){let r=await fetch('/api/admin/lesson-pack-studio/presentation/feature-specs');if(r.status===401){location.href='/admin/login';return}let x=await r.json();mode.innerHTML=x.modes.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');features.innerHTML=x.features.map(f=>'<span>'+f.card+'. '+esc(f.title)+(f.enabled?'':' · مؤجل')+'</span>').join('');policy.textContent='20 بطاقة → '+x.features.length+' مواصفة · بنك الأسئلة الرسمي: معزول · Content Ingestion: بدون تغيير';}
function render(x){blueprint=x;let pre=x.preflight||{};status.className=pre.ready?'ok':'warn';status.textContent=(pre.ready?'✅ Blueprint جاهز':'⛔ يحتاج استكمال')+' · عدد الشرائح: '+(pre.slide_count||0)+(pre.blocking_failures&&pre.blocking_failures.length?' · '+pre.blocking_failures.join('، '):'');slides.innerHTML=(x.slides||[]).map(s=>'<div class=slide><span class=pill>'+esc(s.kind)+'</span><h3>'+s.order+'. '+esc(s.title)+'</h3>'+((s.content_blocks||[]).filter(b=>!b.teacher_only).map(b=>'<p>'+esc(b.text)+'</p>').join(''))+'<small class=muted>'+esc((s.source_refs||[]).join(' · '))+'</small></div>').join('')}
generate.onclick=async()=>{status.textContent='جارٍ إنشاء Blueprint...';let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/blueprint',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())});let x=await r.json();if(!r.ok){status.className='bad';status.textContent=JSON.stringify(x.detail||x);return}render(x)};
async function download(edition){status.textContent='جارٍ تجهيز '+edition+' PPTX...';let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/presentation/export-pptx/'+edition,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload(edition))});if(!r.ok){let x=await r.json();status.className='bad';status.textContent=JSON.stringify(x.detail||x);return}let blob=await r.blob();let url=URL.createObjectURL(blob);let a=document.createElement('a');a.href=url;a.download='lesson-presentation-'+edition+'-'+id+'.pptx';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);status.className='ok';status.textContent='✅ تم تجهيز '+edition+' PPTX بنجاح.'}
studentPptx.onclick=()=>download('student');teacherPptx.onclick=()=>download('teacher');boot();
</script></main></html>'''


@app.get("/admin/lesson-pack-studio/jobs/{job_id}/presentation", response_class=HTMLResponse)
def lesson_presentation_workspace(job_id: str):
    return _workspace(job_id)
