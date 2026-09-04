from __future__ import annotations

from fastapi.responses import HTMLResponse

from .main import app


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>استعادة وتصنيف ملفات PDF القديمة</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1150px;margin:auto;padding:18px}
.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}
.grid{display:grid;grid-template-columns:320px 1fr;gap:14px}.doc{padding:11px;border-bottom:1px solid #eee;cursor:pointer}.doc.active{background:#eef4ff}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}select,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}button{cursor:pointer}
.preview{max-width:100%;max-height:65vh;border-radius:10px;background:#eee}.muted{color:#667085}.ok{color:#067647}.bad{color:#b42318}
@media(max-width:850px){.grid{grid-template-columns:1fr}.preview{max-height:none}}
</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/academic">الهيكل الأكاديمي</a> · <a href="/admin/workflow">مراجعة الأسئلة</a></div>
<div class=grid><div class=box><h2>ملفات غير مصنفة</h2><div id=docs>جارٍ التحميل...</div></div>
<div class=box><h2 id=title>اختر ملفًا</h2><p class=muted>افتح الـPDF أو راجع الصفحة الأولى قبل اختيار المادة والصف. لن يغيّر النظام محتوى الملف أو نص الأسئلة.</p>
<div class=row><button id=openBtn onclick=openPdf() disabled>فتح PDF</button><button id=previewBtn onclick=previewFirst() disabled>معاينة الصفحة الأولى</button></div>
<img id=img class=preview>
<div id=contextCheck class=muted>اختر المادة والصف.</div><div class=row><select id=subject><option value="">المادة</option></select><select id=grade><option value="">الصف</option></select></div>
<div class=row><select id=curriculum><option value="">إصدار المنهج</option></select><select id=term><option value="">الترم</option></select></div>
<div class=row><button id=assignBtn onclick=assign() disabled>حفظ التصنيف الأكاديمي</button><button id=extractBtn onclick=reextract() disabled>إعادة استخراج الأسئلة</button></div>
<div id=msg class=muted></div></div></div>
<script>
let allDocs=[],catalog=null,selected=null;
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function opt(el,rows,label,empty){el.innerHTML='<option value="">'+empty+'</option>'+rows.map(x=>'<option value="'+x.id+'">'+esc(x[label])+'</option>').join('')}
async function jf(url,opt={}){let r=await fetch(url,opt),x=null;try{x=await r.json()}catch(e){}if(r.status===401){location.href='/admin/login';throw new Error('Authentication required')}if(!r.ok)throw new Error((x&&typeof x.detail==='string'&&x.detail)||('HTTP '+r.status));return x}
async function load(){catalog=await jf('/api/academic/catalog');allDocs=await jf('/api/documents');let rows=allDocs.filter(d=>!d.subject_id||!d.grade_level_id||!d.curriculum_version_id||!d.term_id);docs.innerHTML=rows.length?rows.map(d=>'<div class="doc '+(selected&&selected.id==d.id?'active':'')+'" onclick="pick('+d.id+')"><b>#'+d.id+' '+esc(d.filename)+'</b><br><span class=muted>'+esc(d.kind)+' · '+(d.page_count||0)+' صفحة · '+(d.question_count||0)+' سؤال</span></div>').join(''):'<p class=ok>✅ لا توجد ملفات قديمة غير مصنفة.</p>';opt(subject,catalog.subjects,'name_ar','المادة');opt(grade,catalog.grades,'name_ar','الصف');filterCurricula()}
function pick(id){selected=allDocs.find(d=>d.id==id);title.textContent='#'+selected.id+' '+selected.filename;openBtn.disabled=false;previewBtn.disabled=false;assignBtn.disabled=true;extractBtn.disabled=true;img.removeAttribute('src');subject.value='';grade.value='';curriculum.value='';term.value='';filterCurricula();msg.className='muted';msg.textContent='راجع الملف ثم اختر السياق الأكاديمي الصحيح.';document.querySelectorAll('.doc').forEach(x=>x.classList.remove('active'));validateContext()}
function filterCurricula(){let sid=+subject.value||0,gid=+grade.value||0;let rows=(catalog?.curricula||[]).filter(x=>(!sid||x.subject_id==sid)&&(!gid||x.grade_level_id==gid));opt(curriculum,rows,'academic_year','إصدار المنهج');filterTerms()}
function filterTerms(){let cid=+curriculum.value||0;let rows=cid?(catalog?.terms||[]).filter(x=>x.curriculum_version_id==cid):[];opt(term,rows,'name_ar','الترم');validateContext()}
function validateContext(){let sid=+subject.value||0,gid=+grade.value||0,cid=+curriculum.value||0,tid=+term.value||0;let cv=(catalog?.curricula||[]).find(x=>x.id==cid),tm=(catalog?.terms||[]).find(x=>x.id==tid);let ok=!!(sid&&gid&&cv&&tm&&cv.subject_id==sid&&cv.grade_level_id==gid&&tm.curriculum_version_id==cid);contextCheck.className=ok?'ok':'muted';contextCheck.textContent=ok?'✅ السياق الأكاديمي متسق وجاهز للحفظ.':'اختر المادة ← الصف ← إصدار المنهج ← الترم بالترتيب.';assignBtn.disabled=!selected||!ok;return ok}
subject.onchange=()=>{grade.value='';curriculum.value='';term.value='';filterCurricula()};grade.onchange=()=>{curriculum.value='';term.value='';filterCurricula()};curriculum.onchange=()=>{term.value='';filterTerms()};term.onchange=validateContext;
async function openPdf(){if(!selected)return;let x=await jf('/api/documents/'+selected.id+'/pdf-url');window.open(x.url,'_blank')}
async function previewFirst(){if(!selected)return;let ps=await jf('/api/documents/'+selected.id+'/pages');if(!ps.length){msg.textContent='لا توجد صفحات مفهرسة';return}let r=await fetch('/api/documents/'+selected.id+'/page/'+ps[0].page_number+'/preview');if(!r.ok){msg.textContent='تعذر عرض الصفحة';return}if(img.dataset.url)URL.revokeObjectURL(img.dataset.url);let u=URL.createObjectURL(await r.blob());img.dataset.url=u;img.src=u}
async function assign(){if(!selected)return;if(!validateContext()){msg.className='bad';msg.textContent='السياق الأكاديمي غير مكتمل أو غير متسق';return}msg.className='muted';msg.textContent='جارٍ حفظ التصنيف...';let x=await jf('/api/documents/'+selected.id+'/academic-context',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject_id:+subject.value,grade_level_id:+grade.value,curriculum_version_id:+curriculum.value,term_id:+term.value})});msg.className='ok';msg.textContent='تم حفظ التصنيف. يمكنك الآن إعادة استخراج الأسئلة من الصفحات المفهرسة.';extractBtn.disabled=false}
async function reextract(){if(!selected)return;extractBtn.disabled=true;msg.className='muted';msg.textContent='جارٍ إعادة استخراج الأسئلة مع منع التكرار...';try{let x=await jf('/api/documents/'+selected.id+'/reextract-questions',{method:'POST'});msg.className='ok';msg.textContent='تمت المعالجة: أضيف '+x.added+' سؤال · تم تخطي '+x.duplicates_skipped+' مكرر · صفحات فارغة '+x.empty_pages;await load()}catch(e){msg.className='bad';msg.textContent=e.message}finally{extractBtn.disabled=false}}
load().catch(e=>{msg.className='bad';msg.textContent=e.message})
</script></main></html>'''


@app.get("/admin/document-recovery", response_class=HTMLResponse)
def document_recovery_page():
    return PAGE
