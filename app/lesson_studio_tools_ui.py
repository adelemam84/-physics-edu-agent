from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .lesson_studio_enhancements import _enhancement_schema, _style_profile
from .lesson_studio_second_reviewer import _schema_review, reviewer_status


def _tools_schema() -> None:
    _enhancement_schema()
    _schema_review()


@app.get('/api/admin/lesson-studio/jobs/{job_id}/studio-tools', dependencies=[Depends(require_admin)])
def lesson_studio_tools_state(job_id: str):
    _tools_schema()
    with connect() as con:
        job = con.execute('''SELECT id,title,subject,grade_label,output_mode,status,
          ai_suggestions,approved_additions,second_review,second_review_provider,
          second_review_at,second_review_source_hash,teacher_approved
          FROM science_lesson_jobs WHERE id=%s''', (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, 'Lesson studio job not found')
        editions = list(con.execute('''SELECT id,output_mode,grade_label,created_at
          FROM science_lesson_editions WHERE job_id=%s ORDER BY created_at DESC''', (job_id,)).fetchall())
    return {
        'job': dict(job),
        'style_profile': _style_profile(),
        'second_reviewer': reviewer_status(),
        'editions': [dict(x) for x in editions],
        'policies': {
            'suggestions_are_advisory': True,
            'teacher_style_never_changes_scientific_meaning': True,
            'second_reviewer_cannot_modify_or_approve': True,
        },
    }


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lesson Studio Tools</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1050px;margin:auto;padding:14px}.card{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:15px;margin:10px 0}.row{display:flex;gap:8px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}input,select,textarea,button{font:inherit;padding:9px;border:1px solid #d0d5dd;border-radius:8px}input,textarea{width:100%}textarea{min-height:90px}button{cursor:pointer}.primary{background:#101828;color:white}.muted{color:#667085}.ok{color:#027a48}.warn{color:#b54708}.suggestion{border-top:1px solid #eaecf0;padding:10px 0}.finding{background:#f9fafb;border-radius:8px;padding:9px;margin:6px 0}@media(max-width:720px){.grid{grid-template-columns:1fr}}
</style><main>
<div class=card><a href="/admin/lesson-studio/workspace">مساحة المراجعة</a> · <a href="/admin/lesson-studio">رفع درس</a> · <a href="/admin/dashboard">لوحة التحكم</a></div>
<div class=card><h1>أدوات الدرس الذكية</h1><div class=row><input id=jid placeholder="رقم مشروع الدرس"><button id=load class=primary>تحميل</button></div><p id=meta class=muted></p></div>
<div class=grid><div class=card><h2>أسلوب المدرس</h2><label>أسلوب العناوين<input id=heading></label><label>طريقة الأمثلة<input id=example></label><label>طريقة الملخص<input id=sumstyle></label><label>كثافة الرسومات<select id=density><option>balanced</option><option>light</option><option>rich</option></select></label><label>نبرة اللغة<input id=tone></label><label>ملاحظات خاصة<textarea id=notes></textarea></label><button id=saveStyle>حفظ النمط</button></div>
<div class=card><h2>المراجع العلمي الثاني</h2><div id=reviewer class=muted></div><button id=runReview class=primary>تشغيل المراجعة المستقلة</button><div id=reviewOut></div></div></div>
<div class=card><h2>اقتراحات تحسين الشرح</h2><p class=muted>الاقتراحات منفصلة عن كلام المدرس، ولا تدخل النسخة النهائية إلا بعد اعتمادك.</p><button id=genSuggestions>توليد اقتراحات</button><div id=suggestions></div></div>
<div class=card><h2>إنشاء نسخ من نفس المصدر</h2><div class=row><select id=mode><option value=teacher_notes>مذكرة مدرس</option><option value=student_simple>شرح مبسط للطالب</option><option value=quick_revision>مراجعة سريعة</option></select><input id=grade placeholder="الصف/المرحلة"><button id=createEdition>إنشاء النسخة</button></div><div id=editions class=muted></div></div>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let state=null;function id(){return $('#jid').value.trim()}
async function api(u,o){let r=await fetch(u,o);if(r.status===401){location.href='/admin/login';throw new Error('auth')}let x=await r.json().catch(()=>null);if(!r.ok)throw new Error(JSON.stringify(x?.detail||x||r.status));return x}
async function load(){if(!id())return;try{state=await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(id())}/studio-tools`);render()}catch(e){$('#meta').textContent=e.message}}
function render(){let j=state.job,p=state.style_profile,r=state.second_reviewer;$('#meta').textContent=`${j.title} · ${j.subject} · ${j.grade_label||''} · ${j.status}`;$('#heading').value=p.heading_style||'';$('#example').value=p.example_style||'';$('#sumstyle').value=p.summary_style||'';$('#density').value=p.visual_density||'balanced';$('#tone').value=p.language_tone||'';$('#notes').value=p.custom_notes||'';$('#reviewer').innerHTML=r.configured?`<span class=ok>جاهز · ${esc(r.model)}</span>`:'<span class=warn>غير مهيأ بعد — سيظل اختياريًا حتى إضافة OPENAI_API_KEY.</span>';$('#runReview').disabled=!r.configured;renderSuggestions();renderReview();$('#editions').innerHTML=(state.editions||[]).map(e=>`<div>${esc(e.output_mode)} · ${esc(e.grade_label||'')} · ${esc(e.created_at)}</div>`).join('')||'لا توجد نسخ إضافية بعد.'}
function renderSuggestions(){let xs=(state.job.ai_suggestions||{}).suggestions||[];$('#suggestions').innerHTML=xs.map((x,i)=>`<div class=suggestion><b>${esc(x.type)}</b> — ${esc(x.location)}<p>${esc(x.proposal)}</p><div class=muted>${esc(x.reason)}</div><button onclick="approveSuggestion(${i})">اعتماد الاقتراح</button></div>`).join('')||'<p class=muted>لا توجد اقتراحات بعد.</p>'}
function renderReview(){let r=state.job.second_review;if(!r){$('#reviewOut').innerHTML='<p class=muted>لم تُجر مراجعة مستقلة بعد.</p>';return}let fs=(r.findings||[]).map(x=>`<div class=finding><b>${esc(x.severity)} · ${esc(x.category)}</b><br>${esc(x.description)}<br><span class=muted>${esc(x.source_evidence||'')}</span></div>`).join('');$('#reviewOut').innerHTML=`<p>الحكم: <b>${esc(r.verdict)}</b></p>${fs}<p class=muted>${esc(r.summary||'')}</p>`}
$('#load').addEventListener('click',load);$('#saveStyle').addEventListener('click',async()=>{let body={heading_style:$('#heading').value,example_style:$('#example').value,summary_style:$('#sumstyle').value,visual_density:$('#density').value,language_tone:$('#tone').value,preferred_callouts:['definition','law','example','warning'],custom_notes:$('#notes').value};try{await api('/api/admin/lesson-studio/style-profile',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});await load()}catch(e){alert(e.message)}});$('#genSuggestions').addEventListener('click',async()=>{try{await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(id())}/suggestions`,{method:'POST'});await load()}catch(e){alert(e.message)}});window.approveSuggestion=async i=>{let fd=new FormData();fd.append('teacher_note','تمت المراجعة والاعتماد من المدرس');try{await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(id())}/suggestions/${i}/approve`,{method:'POST',body:fd});await load()}catch(e){alert(e.message)}};$('#runReview').addEventListener('click',async()=>{try{$('#reviewOut').textContent='جارٍ إجراء المراجعة المستقلة...';await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(id())}/second-review`,{method:'POST'});await load()}catch(e){alert(e.message)}});$('#createEdition').addEventListener('click',async()=>{let fd=new FormData();fd.append('output_mode',$('#mode').value);fd.append('grade_label',$('#grade').value);try{await api(`/api/admin/lesson-studio/jobs/${encodeURIComponent(id())}/editions`,{method:'POST',body:fd});await load()}catch(e){alert(e.message)}});let q=new URLSearchParams(location.search).get('job_id');if(q){$('#jid').value=q;load()}
</script></main></html>'''


@app.get('/admin/lesson-studio/tools', response_class=HTMLResponse)
def lesson_studio_tools_page():
    return PAGE
