from __future__ import annotations

from fastapi import Depends, Query
from fastapi.responses import HTMLResponse

from .main import app
from .security import require_admin
from .services.ai_governance import governance_snapshot
from .services.ai_telemetry import usage_snapshot


@app.get("/api/admin/ai-operations/summary", dependencies=[Depends(require_admin)])
def ai_operations_summary():
    """Secret-free model routing, readiness, and safety contract."""
    return governance_snapshot()


@app.get("/api/admin/ai-operations/usage", dependencies=[Depends(require_admin)])
def ai_operations_usage(hours: int = Query(default=24, ge=1, le=24 * 31)):
    """Privacy-preserving AI usage, latency, error and optional cost aggregates."""
    return usage_snapshot(hours)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Operations · منصة الفيزياء</title>
<style>
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--soft:#f8fafc;--nav:#101828}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:1280px;margin:auto;padding:18px}.top,.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 4px 18px #1018280a}
.hero{background:linear-gradient(135deg,#101828,#344054);color:white}.hero .muted{color:#d0d5dd}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.metric{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:13px}
.metric b{display:block;font-size:26px;margin-top:5px}.muted{color:var(--muted);font-size:13px}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}
.pill{display:inline-block;border:1px solid var(--line);background:var(--soft);border-radius:999px;padding:5px 9px;margin:2px;font-size:12px}
a{color:#175cd3;text-decoration:none}.hero a{color:white}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:900px}
th,td{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top;font-size:13px}th{background:var(--soft);position:sticky;top:0}
.rec{border-right:4px solid #98a2b3;padding:10px 12px;margin:8px 0;background:var(--soft);border-radius:10px}
@media(max-width:700px){main{padding:9px}.card{border-radius:14px;padding:12px}.metric b{font-size:22px}}
</style><main>
<div class="card top"><a href="/admin/dashboard">لوحة التحكم</a><a href="/admin/research-engine">محرك المصادر</a><a href="/admin/lesson-studio/workspace">Lesson Studio</a><a href="/admin/lesson-studio/integrations">التكاملات</a><a href="/admin/e2e-content-acceptance">قبول المحتوى</a></div>
<div class="card hero"><h1>AI Operations</h1><p class=muted>خريطة تشغيل واحدة توضّح أي نموذج ينفذ كل مهمة، وما الذي يستطيع فعله، وأين تتوقف الصلاحية عند بوابة بشرية أو حتمية.</p><div id=hero class=row></div></div>
<div id=metrics class=grid></div>
<div class=card><h2>استخدام الذكاء الاصطناعي</h2><div id=usageMetrics class=grid></div><div class=table-wrap><table><thead><tr><th>المهمة</th><th>المزود / النموذج</th><th>الاستدعاءات</th><th>الفشل</th><th>Retry</th><th>التوكنات</th><th>متوسط الزمن</th><th>تكلفة تقديرية</th></tr></thead><tbody id=usageRows></tbody></table></div><div id=usagePrivacy class=muted></div></div><div class=card><h2>حالة المزودين والنماذج</h2><div id=providers class=grid></div></div>
<div class=card><h2>توزيع المهام</h2><div class=table-wrap><table><thead><tr><th>المهمة</th><th>المزود / النموذج</th><th>الوضع</th><th>جاهز</th><th>المصدر</th><th>السلطة</th><th>البوابة</th></tr></thead><tbody id=tasks></tbody></table></div></div>
<div class=card><h2>قواعد لا يجوز للنموذج تجاوزها</h2><div id=principles></div></div>
<div class=card><h2>اقتراحات التحسين الحالية</h2><div id=recommendations></div></div>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const yes=v=>v?'<span class=ok>✅ جاهز</span>':'<span class=warn>⚠️ غير جاهز</span>';
async function load(){
  let [r,u]=await Promise.all([fetch('/api/admin/ai-operations/summary'),fetch('/api/admin/ai-operations/usage?hours=24')]);
  if(r.status===401||u.status===401){location.href='/admin/login';return}
  let x=await r.json().catch(()=>null),usage=await u.json().catch(()=>null);
  if(!r.ok||!x){document.body.insertAdjacentHTML('beforeend','<div class="card bad">تعذر تحميل حالة الذكاء الاصطناعي.</div>');return}
  let s=x.summary||{},us=usage?.summary||{};
  hero.innerHTML='<span class=pill>PDF هو المرجع العلمي</span><span class=pill>لا اعتماد آلي</span><span class=pill>لا نشر آلي</span><span class=pill>التصحيح حتمي</span>';
  metrics.innerHTML=[
    ['المهام',s.task_count],['جاهزة',s.ready_tasks],['تحتاج إعداد',s.blocked_tasks],
    ['تكتب بنك الأسئلة',s.question_bank_write_tasks],['تعتمد تلقائيًا',s.auto_approval_tasks],['تنشر تلقائيًا',s.auto_publish_tasks]
  ].map(v=>'<div class=metric><span class=muted>'+esc(v[0])+'</span><b>'+esc(v[1])+'</b></div>').join('');
  usageMetrics.innerHTML=[
    ['الاستدعاءات / 24س',us.total_calls||0],['ناجحة',us.success_calls||0],['فاشلة',us.failed_calls||0],
    ['Retry / 24س',us.retried_calls||0],['محاولات إضافية',us.retry_attempts||0],['Retry %',us.retry_pct||0],
    ['إجمالي التوكنات',us.total_tokens||0],['متوسط الزمن ms',us.avg_latency_ms||0],
    ['التكلفة التقديرية $',Number(us.estimated_cost_usd||0).toFixed(4)]
  ].map(v=>'<div class=metric><span class=muted>'+esc(v[0])+'</span><b>'+esc(v[1])+'</b></div>').join('');
  usageRows.innerHTML=(usage?.groups||[]).map(g=>'<tr><td>'+esc(g.task)+'</td><td>'+esc(g.provider)+'<br><span class=muted>'+esc(g.model||'—')+'</span></td><td>'+esc(g.calls)+'</td><td>'+esc(g.failed_calls)+'</td><td>'+esc(g.retried_calls||0)+' ('+esc(g.retry_pct||0)+'%)<br><span class=muted>+'+esc(g.retry_attempts||0)+' attempts</span></td><td>'+esc(g.total_tokens)+'</td><td>'+esc(g.avg_latency_ms||'—')+' ms</td><td>$'+Number(g.estimated_cost_usd||0).toFixed(4)+'</td></tr>').join('')||'<tr><td colspan=8 class=muted>لا توجد استدعاءات مسجلة في آخر 24 ساعة.</td></tr>';
  usagePrivacy.textContent='الخصوصية: لا يتم تخزين prompts أو المخرجات أو إجابات الطلاب أو نصوص المصادر في سجل القياس. '+(usage?.pricing_configured?'التسعير التقديري مفعّل من الإعدادات.':'التسعير غير مفعّل؛ أرقام التكلفة ستظل صفرًا حتى ضبط AI_MODEL_PRICING_JSON.');
  providers.innerHTML=Object.entries(x.providers||{}).map(([name,p])=>'<div class=metric><b style="font-size:18px">'+esc(name)+'</b><div>'+yes(!!p.configured)+'</div><div class=muted>'+esc(p.role||'')+'</div>'+(p.file_search_configured!==undefined?'<div class=muted>File Search: '+(p.file_search_configured?'جاهز':'غير مفعّل')+'</div>':'')+'</div>').join('');
  tasks.innerHTML=(x.tasks||[]).map(t=>'<tr><td><b>'+esc(t.label_ar)+'</b><div class=muted>'+esc(t.notes_ar)+'</div></td><td>'+esc(t.provider)+(t.model?'<br><span class=muted>'+esc(t.model)+'</span>':'')+(t.reasoning_effort?'<br><span class=pill>reasoning '+esc(t.reasoning_effort)+'</span>':'')+'</td><td>'+esc(t.mode)+'</td><td>'+yes(t.ready)+'</td><td>'+(t.source_grounded?'PDF/source':'—')+'</td><td>'+(t.advisory_only?'<span class=warn>استشاري فقط</span>':'حتمي')+'</td><td>'+esc(t.human_gate)+'</td></tr>').join('');
  principles.innerHTML=Object.entries(x.principles||{}).map(([k,v])=>'<span class="pill '+(v?'ok':'bad')+'">'+(v?'✅ ':'⚠️ ')+esc(k)+'</span>').join('');
  recommendations.innerHTML=(x.recommendations||[]).map(a=>'<div class=rec><b>'+esc(a.title_ar)+'</b><div class=muted>'+esc(a.priority)+' · '+esc(a.reason_ar)+'</div></div>').join('')||'<span class=ok>لا توجد ملاحظات إعداد حالية.</span>';
}
load();
</script></main></html>'''


@app.get("/admin/ai-operations", response_class=HTMLResponse)
def ai_operations_page():
    return PAGE
