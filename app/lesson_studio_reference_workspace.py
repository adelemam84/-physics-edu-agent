from __future__ import annotations

from fastapi.responses import HTMLResponse

from .main import app


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مراجعة المرجع العلمي</title><style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f5f7fb;color:#172033}main{max-width:1180px;margin:auto;padding:14px}.card{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:14px;margin:10px 0}.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.bar input{flex:1;min-width:220px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}input,button{font:inherit;padding:9px;border:1px solid #d0d5dd;border-radius:8px}button{cursor:pointer}.primary{background:#101828;color:#fff}.muted{color:#667085}.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#f2f4f7;font-size:12px}.ok{background:#ecfdf3;border-right:4px solid #12b76a}.warn{background:#fffaeb;border-right:4px solid #f79009}.bad{background:#fef3f2;border-right:4px solid #f04438}.finding{padding:10px;margin:8px 0;border-radius:10px;border:1px solid #e4e7ec}.refpage{padding:10px;border-top:1px solid #eaecf0}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style><main>
<div class="card bar"><a href="/admin/lesson-studio/workspace">مساحة العمل</a><a href="/admin/lesson-studio/references">المراجع العلمية</a><a href="/admin/lesson-studio/tools">أدوات الدرس</a><input id=jid placeholder="رقم مشروع الدرس"><button id=load class=primary>تحميل</button></div>
<div id=summary class=card>أدخل رقم المشروع لعرض حالة مطابقته بالمراجع العلمية.</div>
<div class="grid"><div id=status class=card></div><div class=card><h2>تشغيل المراجعة المرجعية</h2><p class=muted>تُقارن النسخة الحالية فقط بالمراجع المرفوعة لنفس المادة/الصف. لا يتم تعديل شرح المدرس تلقائيًا.</p><button id=run class=primary>تشغيل/إعادة المراجعة</button><p id=msg class=muted></p></div></div>
<div id=findings class=card></div><div id=pages class=card></div>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function id(){return $('#jid').value.trim()}async function api(url,opt){let r=await fetch(url,opt);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(JSON.stringify(x?.detail||x||r.status));return x}
function severityClass(s){return s==='critical'?'bad':s==='review'?'warn':'ok'}
async function load(){if(!id())return;try{let x=await api('/api/admin/lesson-studio/jobs/'+encodeURIComponent(id())+'/reference-review');render(x)}catch(e){$('#summary').textContent=e.message}}
function render(x){$('#summary').innerHTML=`<b>مراجعة المرجع العلمي</b> · ${x.available?'موجودة':'لم تُشغّل بعد'} · ${x.fresh?'حديثة':'غير حديثة'} · الحكم: <span class=pill>${esc(x.verdict||'—')}</span>`;$('#status').innerHTML=`<h2>الحالة</h2><p>مطلوبة قبل الاعتماد: <b>${x.configured_as_required?'نعم':'لا'}</b></p><p>متوافقة وواضحة: <b>${x.clear?'نعم':'لا'}</b></p><p>Critical: ${x.counts.critical} · Review: ${x.counts.review} · Info: ${x.counts.info}</p><p class=muted>السياسة: المرجع سياق تحقق فقط وليس مصدر تأليف تلقائي.</p>`;let r=x.review||{};let fs=r.findings||[];$('#findings').innerHTML='<h2>النتائج</h2>'+(fs.length?fs.map(f=>`<div class="finding ${severityClass(f.severity)}"><b>${esc(f.category)} · ${esc(f.severity)}</b><p>${esc(f.description)}</p><div class=muted>موضع الدرس: ${esc(f.lesson_location||'—')}<br>المرجع: ${esc(f.reference_document||'—')} · صفحة ${esc(f.reference_page||'—')}<br>الدليل: ${esc(f.reference_evidence||'—')}</div></div>`).join(''):'<p class=muted>لا توجد نتائج مسجلة.</p>');let ps=r.reference_pages||[];$('#pages').innerHTML='<h2>الصفحات المرجعية المستخدمة</h2>'+(ps.length?ps.map(p=>`<div class=refpage><b>${esc(p.document_title)}</b> · صفحة ${esc(p.page_number)} · score ${esc(p.score)}</div>`).join(''):'<p class=muted>لا توجد صفحات مرجعية مرتبطة بهذه المراجعة.</p>')}
$('#load').onclick=load;$('#run').onclick=async()=>{if(!id())return;$('#run').disabled=true;$('#msg').textContent='جارٍ إجراء المطابقة المرجعية...';try{await api('/api/admin/lesson-studio/jobs/'+encodeURIComponent(id())+'/reference-review',{method:'POST'});$('#msg').textContent='تمت المراجعة المرجعية.';await load()}catch(e){$('#msg').textContent=e.message}finally{$('#run').disabled=false}};let p=new URLSearchParams(location.search).get('job_id');if(p){$('#jid').value=p;load()}
</script></main></html>'''


@app.get('/admin/lesson-studio/reference-workspace', response_class=HTMLResponse)
def lesson_studio_reference_workspace():
    return PAGE
