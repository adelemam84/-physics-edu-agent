from __future__ import annotations

from fastapi.responses import HTMLResponse

from .main import app


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>المراجع العلمية</title><style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui;background:#f5f7fb;color:#172033}main{max-width:1100px;margin:auto;padding:14px}.card{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:14px;margin:10px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,button{font:inherit;padding:9px;border:1px solid #d0d5dd;border-radius:8px}input[type=text]{min-width:180px;flex:1}button{cursor:pointer}.primary{background:#101828;color:white}.muted{color:#667085}.ref{border-top:1px solid #eaecf0;padding:12px 0}.pill{display:inline-block;border-radius:999px;padding:3px 8px;background:#f2f4f7;font-size:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style><main>
<div class=card><a href="/admin/lesson-studio">Lesson Studio</a> · <a href="/admin/lesson-studio/tools">أدوات الدرس</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>
<div class="card grid"><div><h1>مكتبة المراجع العلمية</h1><p class=muted>ارفع مرجع PDF لكل مادة/صف. المرجع يُستخدم للتحقق وفهم نطاق الدروس ولا يغيّر شرح المدرس تلقائيًا.</p></div><form id=form><input name=title type=text placeholder="اسم المرجع" required><div class=row><select name=subject required><option value=physics>فيزياء</option><option value=chemistry>كيمياء</option><option value=science>علوم</option></select><input name=grade_label type=text placeholder="الصف/المرحلة"><input name=academic_year type=text placeholder="العام الدراسي"></div><p><input name=file type=file accept="application/pdf" required></p><button class=primary>رفع وفهرسة المرجع</button><p id=msg class=muted></p></form></div>
<div class=card><div class=row><h2 style="flex:1">المراجع الحالية</h2><select id=filter><option value="">كل المواد</option><option value=physics>فيزياء</option><option value=chemistry>كيمياء</option><option value=science>علوم</option></select><button id=reload>تحديث</button></div><div id=list></div></div>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));async function api(url,opt){let r=await fetch(url,opt);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(JSON.stringify(x?.detail||x||r.status));return x}
async function load(){let s=$('#filter').value;let x=await api('/api/admin/lesson-studio/references'+(s?'?subject='+encodeURIComponent(s):''));$('#list').innerHTML=x.references.map(r=>`<div class=ref><b>${esc(r.title)}</b> <span class=pill>${esc(r.subject)}</span> <span class=pill>${esc(r.grade_label||'كل الصفوف')}</span><div class=muted>${esc(r.filename)} · ${r.page_count} صفحة · ${r.active?'نشط':'موقوف'}</div><button onclick="toggleRef('${r.id}',${!r.active})">${r.active?'إيقاف':'تفعيل'}</button></div>`).join('')||'<p class=muted>لا توجد مراجع مضافة.</p>'}
async function toggleRef(id,active){let fd=new FormData();fd.append('active',String(active));await api('/api/admin/lesson-studio/references/'+id+'/active',{method:'POST',body:fd});load()}
$('#form').onsubmit=async e=>{e.preventDefault();let b=e.submitter;b.disabled=true;$('#msg').textContent='جارٍ الفهرسة...';try{let x=await api('/api/admin/lesson-studio/references',{method:'POST',body:new FormData(e.target)});$('#msg').textContent=x.duplicate?'المرجع موجود بالفعل.':'تم رفع وفهرسة المرجع بنجاح.';e.target.reset();load()}catch(err){$('#msg').textContent=err.message}finally{b.disabled=false}};$('#reload').onclick=load;$('#filter').onchange=load;load();
</script></main></html>'''


@app.get('/admin/lesson-studio/references', response_class=HTMLResponse)
def science_reference_library_page():
    return PAGE
