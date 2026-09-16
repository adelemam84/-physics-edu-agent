from __future__ import annotations

import json

from fastapi.responses import HTMLResponse

from .main import app


HOME_PAGE = r"""<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lesson Pack Studio</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1000px;margin:auto;padding:18px}
.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 2px 12px #0001}.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
input,select,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:10px;width:100%}button{cursor:pointer;background:#172033;color:#fff}
.muted{color:#667085;white-space:pre-wrap}.ok{color:#067647}.warn{color:#b54708}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/lesson-studio">Lesson Studio</a></div>
<div class=box><h1>Lesson Pack Studio</h1><p>حوّل PDF أو Scan إلى ملزمة شرح منظمة ورسومات وتدريبات مولدة من المصدر، مع نسختين للطالب والمدرس.</p><div id=status class=muted>جارٍ تحميل الحالة...</div></div>
<form id=f class=box><div class=row><input name=title placeholder="عنوان الدرس" required><select name=subject><option value=physics>فيزياء</option><option value=chemistry>كيمياء</option><option value=science>علوم</option></select><input name=grade_label placeholder="الصف"><select name=pack_mode><option value=balanced>متوازن</option><option value=exam_revision>مراجعة امتحان</option><option value=concept_mastery>إتقان المفاهيم</option></select></div><p><input name=files type=file accept=".pdf,image/*" multiple required></p><button>إنشاء الملزمة</button></form>
<div class=box><div id=out class=muted>لم تبدأ عملية بعد.</div></div>
<script>
async function boot(){let r=await fetch('/api/admin/lesson-pack-studio/status');if(r.status===401){location.href='/admin/login';return}let x=await r.json();status.textContent='الرفع: '+(x.ingestion_enabled?'مفعل':'متوقف')+' · OCR: '+x.ocr_provider+' · التخزين: '+(x.storage_configured?'جاهز':'غير مهيأ')+' · بنك الأسئلة الرسمي: معزول';}
async function processAll(id,total){let done=false;while(!done){let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/process-next',{method:'POST'});let x=await r.json();if(!r.ok)throw new Error(JSON.stringify(x.detail||x));done=!!x.done;out.textContent='OCR: '+x.processed+' / '+total+' · صفحات تحتاج مراجعة: '+x.review_pages;}let fd=new FormData();fd.append('question_count','12');let g=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/generate',{method:'POST',body:fd});let y=await g.json();if(!g.ok)throw new Error(JSON.stringify(y.detail||y));location.href='/admin/lesson-pack-studio/jobs/'+id+'/preview';}
f.addEventListener('submit',async e=>{e.preventDefault();out.textContent='جارٍ تجهيز الصفحات...';try{let r=await fetch('/api/admin/lesson-pack-studio/jobs',{method:'POST',body:new FormData(f)});let x=await r.json();if(!r.ok)throw new Error(JSON.stringify(x.detail||x));out.textContent='تم إنشاء المشروع. بدء OCR صفحة بصفحة...';await processAll(x.id,x.source_page_count)}catch(err){out.textContent='خطأ: '+err.message}});boot();
</script></main></html>"""


@app.get("/admin/lesson-pack-studio", response_class=HTMLResponse)
def lesson_pack_home():
    return HOME_PAGE


def _preview_page(job_id: str) -> str:
    safe_id = json.dumps(job_id)
    return r"""<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>مراجعة Lesson Pack</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:16px}
.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.page{border:1px solid #e4e7ec;border-radius:12px;padding:10px}.page img{width:100%;max-height:360px;object-fit:contain;background:#fafafa}
textarea{width:100%;min-height:180px;font:inherit;padding:10px}button,input{font:inherit;padding:9px;border:1px solid #ccd2dd;border-radius:9px}button{cursor:pointer}.primary{background:#172033;color:#fff}
.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.muted{color:#667085;white-space:pre-wrap}.q{border:1px solid #e4e7ec;border-radius:10px;padding:10px;margin:8px 0}details{margin-top:8px}
</style><main><div class=box><a href="/admin/lesson-pack-studio">Lesson Pack Studio</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>
<div id=head class=box>جارٍ التحميل...</div><div id=pack class=box></div><div class=box><h2>مراجعة صفحات المصدر</h2><div id=pages class=grid></div></div>
<div class=box><h2>إجراءات الجودة</h2><div class=grid><button id=regen>إعادة توليد الملزمة</button><button id=sci>المراجعة العلمية المستقلة</button><button id=approve class=primary>اعتماد نهائي</button></div><p id=action class=muted></p><p><a id=studentPdf href="#">Student PDF</a> · <a id=teacherPdf href="#">Teacher PDF</a></p></div>
<script>
const id=""" + safe_id + r"""; const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data;
async function load(){let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id);if(r.status===401){location.href='/admin/login';return}data=await r.json();if(!r.ok){head.textContent=JSON.stringify(data);return}
head.innerHTML='<h1>'+esc(data.title)+'</h1><p class=muted>'+esc(data.subject)+' · '+esc(data.grade_label)+' · الحالة: '+esc(data.status)+'</p><p>OCR: '+data.progress.transcribed_pages+'/'+data.progress.total_pages+' · مراجعة مطلوبة: '+data.progress.review_pages+' · اعتماد المدرس: '+(data.teacher_approved?'✅':'⏳')+'</p>';
let p=data.pack_json||{};let qs=p.practice_questions||[];pack.innerHTML='<h2>معاينة الملزمة</h2><p>'+esc(p.summary||'لم يتم التوليد بعد')+'</p>'+((p.sections||[]).map(s=>'<div><h3>'+esc(s.heading)+'</h3><p>'+esc(s.body)+'</p><small>'+esc((s.source_refs||[]).join('، '))+'</small></div>').join(''))+'<h3>التدريبات ('+qs.length+')</h3>'+qs.map((q,i)=>'<div class=q><b>'+(i+1)+') '+esc(q.prompt)+'</b><div class=muted>'+esc((q.source_refs||[]).join('، '))+'</div><details><summary>الإجابة والتفسير</summary><p>'+esc(q.answer)+'</p><p>'+esc(q.explanation)+'</p></details></div>').join('');
pages.innerHTML=data.pages.map(pg=>'<div class=page><h3>'+esc(pg.source_ref)+'</h3><img src="'+esc(pg.image_url)+'"><textarea id="t'+pg.id+'">'+esc(pg.extracted_text||'')+'</textarea><p class="'+(pg.requires_review?'warn':'ok')+'">'+(pg.requires_review?'تحتاج اعتماد OCR':'معتمدة')+'</p><button data-page="'+pg.id+'">اعتماد النص الظاهر</button></div>').join('');
pages.querySelectorAll('button[data-page]').forEach(b=>b.onclick=async()=>{let fd=new FormData();fd.append('corrected_text',document.getElementById('t'+b.dataset.page).value);let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/pages/'+b.dataset.page+'/approve',{method:'POST',body:fd});let x=await r.json();action.textContent=r.ok?'تم اعتماد الصفحة'+(x.pack_invalidated?' — يلزم إعادة توليد الملزمة.':''):JSON.stringify(x.detail||x);await load()});
studentPdf.href='/api/admin/lesson-pack-studio/jobs/'+id+'/export-pdf?edition=student';teacherPdf.href='/api/admin/lesson-pack-studio/jobs/'+id+'/export-pdf?edition=teacher';}
regen.onclick=async()=>{let fd=new FormData();fd.append('question_count','12');let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/generate',{method:'POST',body:fd});let x=await r.json();action.textContent=r.ok?'تمت إعادة التوليد.':JSON.stringify(x.detail||x);await load()};
sci.onclick=async()=>{let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/scientific-review',{method:'POST'});let x=await r.json();action.textContent=r.ok?'اكتملت المراجعة العلمية: '+JSON.stringify(x.review):JSON.stringify(x.detail||x);await load()};
approve.onclick=async()=>{let fd=new FormData();fd.append('confirm_source_grounded','true');fd.append('accept_reviewer_findings','true');fd.append('notes','Approved from Lesson Pack Studio workspace');let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/approve',{method:'POST',body:fd});let x=await r.json();action.textContent=r.ok?'✅ تم الاعتماد النهائي. يمكن تنزيل نسختي PDF.':JSON.stringify(x.detail||x);await load()};load();
</script></main></html>"""


@app.get(
    "/admin/lesson-pack-studio/jobs/{job_id}/preview",
    response_class=HTMLResponse,
)
def lesson_pack_preview(job_id: str):
    return _preview_page(job_id)
