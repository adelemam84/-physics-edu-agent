from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>تشغيل محركات المصادر</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1050px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.muted{color:#667085}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}button,input{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:9px}button{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;padding:12px;border-radius:10px}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/research-engine">محرك البحث</a> · <a href="/admin/current-corpus">بنك 2026/2027</a></div>
<div class=box><h1>تشغيل محركات المصادر</h1><p class=muted>المحرك الأساسي يملك القرار النهائي. Gemini للبحث وفهم المصادر فقط، ولا يكتب أو يعتمد أسئلة تلقائيًا.</p><div id=cards class=grid></div></div>
<div class=box><h2>Gemini File Search Store</h2><button onclick=ensureStore()>إنشاء / تأكيد الـStore</button><pre id=storeOut>—</pre></div>
<div class=box><h2>فهرسة مصدر</h2><div><input id=doc type=number min=1 placeholder="Document ID"><button onclick=indexDoc()>فهرسة المصدر</button><button onclick=refreshDoc()>تحديث الحالة</button></div><p class=muted>البحث الواسع يفهرس النص المستخرج بعلامات الصفحات. مراجعة الأسئلة والرسومات تظل من PDF الأصلي.</p><pre id=indexOut>—</pre></div>
<div class=box><h2>المصادر المفهرسة</h2><div id=synced class=muted>جارٍ التحميل...</div></div>
<div class=box><h2>جاهزية الإصدار القادم</h2><pre id=releaseOut>جارٍ التحميل...</pre></div>
<script>
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function j(url,opt){let r=await fetch(url,opt);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>({}));if(!r.ok)throw new Error(JSON.stringify(x.detail||x));return x}
async function load(){try{let [e,s,i,r]=await Promise.all([j('/api/admin/research-engine/status'),j('/api/admin/research-engine/file-search-store/status'),j('/api/admin/research-engine/index/status'),j('/api/admin/next-release/status')]);cards.innerHTML=[['Orchestrator',e.orchestrator?.status||'—'],['Gemini API',e.configured?'جاهز':'غير مفعّل'],['File Search',s.configured?'جاهز':'غير منشأ'],['المصادر المفهرسة',(i.synced||[]).filter(x=>x.state==='active').length],['الإصدار',r.version],['حالة الإصدار',r.release_state]].map(v=>'<div class=card><div class=muted>'+esc(v[0])+'</div><b>'+esc(v[1])+'</b></div>').join('');storeOut.textContent=JSON.stringify(s,null,2);releaseOut.textContent=JSON.stringify(r,null,2);let rows=i.synced||[];synced.innerHTML=rows.length?rows.map(x=>'<div class=card><b>#'+x.document_id+' '+esc(x.filename)+'</b><br>الحالة: '+esc(x.state)+' · الصفحات: '+x.source_pages+' · الأحرف: '+x.indexed_chars+'</div>').join(''):'لا توجد مصادر مفهرسة بعد.'}catch(e){if(e.message!=='auth')releaseOut.textContent=e.message}}
async function ensureStore(){try{storeOut.textContent='جارٍ التنفيذ...';storeOut.textContent=JSON.stringify(await j('/api/admin/research-engine/file-search-store/ensure',{method:'POST'}),null,2);await load()}catch(e){storeOut.textContent=e.message}}
async function indexDoc(){try{indexOut.textContent='جارٍ بدء الفهرسة...';indexOut.textContent=JSON.stringify(await j('/api/admin/research-engine/index/document/'+Number(doc.value),{method:'POST'}),null,2);await load()}catch(e){indexOut.textContent=e.message}}
async function refreshDoc(){try{indexOut.textContent='جارٍ تحديث الحالة...';indexOut.textContent=JSON.stringify(await j('/api/admin/research-engine/index/refresh/'+Number(doc.value),{method:'POST'}),null,2);await load()}catch(e){indexOut.textContent=e.message}}
load()
</script></main></html>'''


@router.get('/admin/research-ops',response_class=HTMLResponse)
def research_ops_page():
    return PAGE
