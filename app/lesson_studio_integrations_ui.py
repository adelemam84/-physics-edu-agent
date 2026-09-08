from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .canva_diagnostics import canva_readiness_snapshot
from .external_creative_integrations import integration_status
from .main import app
from .security import require_admin
from .services.canva_master_contract import CANVA_MASTER_DESIGN_ID, CANVA_MASTER_TEXT_FIELDS


def integration_control_snapshot() -> dict:
    """Return a secret-free activation view for optional creative integrations."""
    status = integration_status()
    canva = canva_readiness_snapshot(check_remote=False)
    return {
        'canva': {
            **canva,
            'master_design_id': CANVA_MASTER_DESIGN_ID,
            'master_field_count': len(CANVA_MASTER_TEXT_FIELDS),
            'oauth_start_url': '/api/admin/integrations/canva/oauth/start',
            'oauth_status_url': '/api/admin/integrations/canva/oauth/status',
            'remote_diagnostics_url': '/api/admin/integrations/canva/diagnostics?remote=true',
        },
        'providers': status,
        'actions': {
            'canva': '/api/admin/lesson-studio/jobs/{job_id}/external-artifacts/canva',
            'google_slides': '/api/admin/lesson-studio/jobs/{job_id}/external-artifacts/google_slides',
            'gemini_notebook_enterprise': '/api/admin/lesson-studio/jobs/{job_id}/external-artifacts/gemini_notebook_enterprise',
        },
        'policy': {
            'source_grounded_payload_only': True,
            'external_integrations_optional': True,
            'external_failure_does_not_block_internal_exports': True,
            'no_oauth_tokens_or_client_secrets_exposed': True,
            'canva_autofill_never_approves_scientific_content': True,
            'external_artifacts_bound_to_lesson_content_hash': True,
        },
    }


@app.get('/api/admin/lesson-studio/integrations/summary', dependencies=[Depends(require_admin)])
def lesson_studio_integrations_summary():
    return integration_control_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lesson Studio Integrations</title><style>
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:14px}.card{background:#fff;border:1px solid #e4e7ec;border-radius:15px;padding:15px;margin:10px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}input,button{font:inherit;padding:10px;border:1px solid #d0d5dd;border-radius:9px}input{min-width:230px;flex:1}button{cursor:pointer;background:#fff}.primary{background:#101828;color:#fff}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}.muted{color:#667085}.pill{display:inline-block;padding:4px 9px;border-radius:999px;background:#f2f4f7;margin:2px;font-size:12px}.result{white-space:pre-wrap;word-break:break-word;background:#f8fafc;border-radius:10px;padding:10px;margin-top:9px}.actions button:disabled{cursor:not-allowed;opacity:.45}.artifact{border-top:1px solid #eaecf0;padding:10px 0}a{color:#175cd3}@media(max-width:650px){main{padding:9px}.row>*{width:100%}}
</style><main>
<div class="card row"><a href="/admin/dashboard">لوحة التحكم</a><a href="/admin/lesson-studio/workspace">مساحة الدرس</a><a href="/admin/lesson-studio/tools">أدوات الدرس</a><a href="/admin/lesson-studio/release-readiness">جاهزية الإصدار</a></div>
<div class=card><h1>مركز التكاملات الإبداعية</h1><p class=muted>تشغيل Canva وGoogle Slides وGemini Notebook من المحتوى المعتمد في Lesson Studio. كل مخرج خارجي يُربط ببصمة محتوى الدرس، وأي تعديل لاحق يجعله قديمًا تلقائيًا.</p><div class=row><input id=jid placeholder="رقم مشروع الدرس"><button id=refresh>تحديث الحالة</button></div></div>
<div id=summary class=grid></div>
<div class=card><h2>Canva Autofill</h2><div id=canva></div><div class="row actions"><button id=authorize>تفويض / إعادة تفويض Canva</button><button id=remote>فحص Dataset الحقيقي</button><button id=createCanva class=primary>إنشاء Visual Summary في Canva</button></div><div id=canvaResult class=result></div></div>
<div class=grid><div class=card><h2>Google Slides</h2><div id=slides></div><button id=createSlides>إنشاء Google Slides</button><div id=slidesResult class=result></div></div><div class=card><h2>Gemini Notebook Enterprise</h2><div id=notebook></div><button id=createNotebook>إنشاء Notebook</button><div id=notebookResult class=result></div></div></div>
<div class=card><h2>سجل المخرجات الخارجية</h2><p class=muted>المخرجات القديمة تظل محفوظة للتدقيق، لكنها لا تُعتبر نسخة حالية إذا تغير محتوى الدرس.</p><div id=artifacts class=muted>أدخل رقم مشروع الدرس لعرض السجل.</div></div>
<div class=card><h2>قواعد الأمان</h2><div id=policy class=muted></div></div>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));let state=null;
async function api(u,o){let r=await fetch(u,o);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(typeof x?.detail==='string'?x.detail:JSON.stringify(x?.detail||x||r.status));return x}
function yes(v){return v?'<span class=ok>✅ جاهز</span>':'<span class=warn>⚠️ غير مكتمل</span>'}function jid(){return $('#jid').value.trim()}
function providerCard(name,x){return `<div class=card><h3>${esc(name)}</h3><p>${yes(!!x?.configured)}</p><div class=muted>${esc(x?.mode||'')}</div></div>`}
function render(){let c=state.canva,p=state.providers;$('#summary').innerHTML=providerCard('Canva',p.canva)+providerCard('Google Slides',p.google_slides)+providerCard('Gemini Notebook',p.gemini_notebook_enterprise);let scopes=(c.missing_scopes||[]).map(x=>`<span class=pill>${esc(x)}</span>`).join('');$('#canva').innerHTML=`<p><b>الإعداد:</b> ${yes(c.configured)} · <b>OAuth:</b> ${yes(c.authorized_for_requested_scopes)} · <b>المصدر:</b> ${esc(c.source_type)} / ${esc(c.source_id)}</p><p><b>Master fields:</b> ${esc(c.master_field_count)} · <b>إعادة التفويض:</b> ${c.needs_reauthorization?'مطلوبة':'لا'}</p>${scopes?'<p class=warn>الصلاحيات الناقصة: '+scopes+'</p>':''}<p class=muted>لن يتم إرسال إلا حقول مشتقة من محتوى الدرس المحفوظ؛ الحقول غير المدعومة تظل فارغة.</p>`;$('#createCanva').disabled=!c.ready;$('#remote').disabled=!c.configured||!c.authorized_for_requested_scopes;$('#createSlides').disabled=!p.google_slides?.configured;$('#createNotebook').disabled=!p.gemini_notebook_enterprise?.configured;$('#slides').innerHTML=yes(!!p.google_slides?.configured)+'<p class=muted>'+esc((p.google_slides?.requires||[]).join(' · '))+'</p>';$('#notebook').innerHTML=yes(!!p.gemini_notebook_enterprise?.configured)+'<p class=muted>'+esc((p.gemini_notebook_enterprise?.requires||[]).join(' · '))+'</p>';$('#policy').innerHTML=Object.entries(state.policy).map(([k,v])=>`<div>${v?'✅':'⚠️'} ${esc(k)}</div>`).join('')}
async function load(){try{state=await api('/api/admin/lesson-studio/integrations/summary');render();await loadArtifacts()}catch(e){$('#canvaResult').textContent=e.message}}
function resultLink(x){let u=x?.design?.urls?.edit_url||x?.design?.edit_url||x?.design?.url||x?.file?.webViewLink||x?.url||'';return /^https:\/\//.test(u)?u:''}
async function loadArtifacts(){if(!jid()){ $('#artifacts').textContent='أدخل رقم مشروع الدرس لعرض السجل.';return}try{let x=await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(jid())}/external-artifacts`),rows=x.artifacts||[];$('#artifacts').innerHTML=rows.length?rows.map(a=>`<div class=artifact><b>${esc(a.provider)}</b> · ${esc(a.status)} · ${a.fresh_for_current_content?'<span class=ok>حالي</span>':'<span class=warn>قديم بعد تعديل المحتوى</span>'}<br><span class=muted>${esc(a.created_at||'')} · ${esc((a.source_hash||'').slice(0,12))}</span>${/^https:\/\//.test(a.external_url||'')?`<br><a href="${esc(a.external_url)}" target=_blank rel="noopener">فتح المخرج الخارجي</a>`:''}${a.error?`<div class=bad>${esc(a.error)}</div>`:''}</div>`).join(''):'لا توجد مخرجات خارجية لهذا الدرس بعد.'}catch(e){$('#artifacts').textContent=e.message}}
async function runExternal(provider,out){if(!jid()){alert('أدخل رقم مشروع الدرس أولًا');return}out.textContent='جارٍ التنفيذ...';try{let x=await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(jid())}/external-artifacts/${provider}`,{method:'POST'}),result=x.result||x,u=resultLink(result);out.innerHTML=(u?`<a href="${esc(u)}" target=_blank rel="noopener">فتح النتيجة</a><br>`:'')+`<span class=muted>تم تسجيل المخرج وربطه ببصمة محتوى الدرس.</span>`;await loadArtifacts()}catch(e){out.textContent=e.message;await loadArtifacts()}}
$('#refresh').onclick=load;$('#authorize').onclick=()=>{location.href='/api/admin/integrations/canva/oauth/start'};$('#remote').onclick=async()=>{let o=$('#canvaResult');o.textContent='جارٍ فحص Dataset...';try{let x=await api('/api/admin/integrations/canva/diagnostics?remote=true');o.textContent=JSON.stringify(x,null,2);await load()}catch(e){o.textContent=e.message}};$('#createCanva').onclick=()=>runExternal('canva',$('#canvaResult'));$('#createSlides').onclick=()=>runExternal('google_slides',$('#slidesResult'));$('#createNotebook').onclick=()=>runExternal('gemini_notebook_enterprise',$('#notebookResult'));let q=new URLSearchParams(location.search).get('job_id');if(q)$('#jid').value=q;load();
</script></main></html>'''


@app.get('/admin/lesson-studio/integrations', response_class=HTMLResponse)
def lesson_studio_integrations_page():
    return PAGE
