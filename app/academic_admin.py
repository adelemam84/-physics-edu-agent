from fastapi.responses import HTMLResponse
from .main import app

PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>الهيكل الأكاديمي</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1100px;margin:auto;padding:18px}.box{background:#fff;padding:15px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}select,input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #eee;text-align:right}.muted{color:#667085;font-size:13px}</style><main>
<h1>الهيكل الأكاديمي متعدد المواد</h1>
<div class="box row"><input id=key type=password placeholder="ADMIN_API_KEY"><button onclick=save()>حفظ المفتاح</button><a href="/admin/dashboard">لوحة التحكم</a></div>
<div class=box><h2>إنشاء إصدار منهج</h2><div class=row><select id=subj></select><select id=grade></select><input id=year value="2026/2027"><button onclick=createCurriculum()>إنشاء المنهج والترمين</button></div><div id=msg class=muted></div></div>
<div class=box><h2>المناهج</h2><div id=curricula></div></div>
<div class=box><h2>تغطية المنهج</h2><button onclick=coverage()>تحديث</button><div id=cov></div></div>
<script>
key.value=localStorage.pk||'';const H=()=>({'X-Admin-Key':localStorage.pk||''});function save(){localStorage.pk=key.value;load()}
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function jf(u,o={}){let r=await fetch(u,o),x=await r.json();if(!r.ok)throw new Error(typeof x.detail==='string'?x.detail:JSON.stringify(x.detail));return x}
async function load(){try{let x=await jf('/api/academic/catalog');subj.innerHTML=x.subjects.map(s=>`<option value="${s.id}">${e(s.name_ar)}</option>`).join('');grade.innerHTML=x.grades.map(g=>`<option value="${g.id}">${e(g.name_ar)}</option>`).join('');curricula.innerHTML=x.curricula.length?'<table><tr><th>المادة</th><th>الصف</th><th>السنة</th><th>الإصدار</th></tr>'+x.curricula.map(c=>`<tr><td>${e(c.subject_name)}</td><td>${e(c.grade_name)}</td><td>${e(c.academic_year)}</td><td>${e(c.version_label)}</td></tr>`).join('')+'</table>':'لا توجد مناهج بعد';coverage()}catch(err){msg.textContent=err.message}}
async function createCurriculum(){try{let x=await jf('/api/academic/curricula',{method:'POST',headers:{...H(),'Content-Type':'application/json'},body:JSON.stringify({subject_id:Number(subj.value),grade_level_id:Number(grade.value),academic_year:year.value,version_label:'official'})});for(let n of [1,2])await jf('/api/academic/terms',{method:'POST',headers:{...H(),'Content-Type':'application/json'},body:JSON.stringify({curriculum_version_id:x.id,term_number:n,name_ar:n===1?'الترم الأول':'الترم الثاني'})});msg.textContent='تم إنشاء المنهج والترمين';load()}catch(err){msg.textContent=err.message}}
async function coverage(){try{let x=await jf('/api/academic/coverage',{headers:H()});cov.innerHTML=x.length?'<table><tr><th>المادة</th><th>الصف</th><th>الوحدة</th><th>الدرس</th><th>الأسئلة</th><th>المعتمد</th></tr>'+x.map(r=>`<tr><td>${e(r.subject||'غير محدد')}</td><td>${e(r.grade||'غير محدد')}</td><td>${e(r.unit||'—')}</td><td>${e(r.lesson)}</td><td>${r.total_questions}</td><td>${r.approved_questions}</td></tr>`).join('')+'</table>':'لا توجد بيانات مصنفة بعد'}catch(err){cov.textContent=err.message}}load()
</script></main></html>'''
@app.get("/admin/academic",response_class=HTMLResponse)
def academic_admin(): return PAGE
