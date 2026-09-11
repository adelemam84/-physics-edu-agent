from __future__ import annotations

import re

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from .main import app
from .security import require_admin
from .services.ai_budget import budget_snapshot, enforce_ai_budget


# Only routes that can cause an external AI/OCR provider call belong here.
# Deterministic rendering, PDF export, file upload, grading and question selection
# intentionally stay outside this guard.
_AI_ROUTE_POLICIES: tuple[tuple[re.Pattern[str], dict[str, str | None]], ...] = (
    (
        re.compile(r"^/api/admin/research-engine/(?:query|orchestrate)$"),
        {"provider": "gemini", "task": "research_engine", "model": None},
    ),
    (
        re.compile(r"^/api/admin/current-corpus/visual-review/(?:\d+/suggest|batch-suggest)$"),
        {"provider": "gemini", "task": "visual_review", "model": None},
    ),
    (
        re.compile(r"^/api/admin/lesson-studio/jobs/[^/]+/process$"),
        {"provider": "lesson_studio", "task": "ocr_and_lesson_support", "model": None},
    ),
    (
        re.compile(r"^/api/admin/lesson-studio/jobs/[^/]+/second-review$"),
        {"provider": "openai", "task": "independent_scientific_review", "model": None},
    ),
    (
        re.compile(r"^/api/admin/lesson-studio/jobs/[^/]+/reference-review$"),
        {"provider": "gemini", "task": "scientific_reference_review", "model": None},
    ),
    (
        re.compile(r"^/api/admin/research-engine/file-search-store/ensure$"),
        {"provider": "gemini", "task": "file_search_store_admin", "model": None},
    ),
    (
        re.compile(r"^/api/admin/research-engine/index/document/\d+$"),
        {"provider": "gemini", "task": "source_indexing", "model": None},
    ),
    (
        re.compile(r"^/api/admin/research-engine/index/refresh/\d+$"),
        {"provider": "gemini", "task": "source_indexing_status", "model": None},
    ),
)


def ai_route_policy(path: str, method: str = "POST") -> dict[str, str | None] | None:
    if method.upper() != "POST":
        return None
    for pattern, policy in _AI_ROUTE_POLICIES:
        if pattern.fullmatch(path):
            return dict(policy)
    return None


@app.middleware("http")
async def ai_budget_middleware(request: Request, call_next):
    policy = ai_route_policy(request.url.path, request.method)
    if policy:
        enforce_ai_budget(
            provider=str(policy["provider"]),
            task=str(policy["task"]),
            model=policy.get("model"),
        )
    return await call_next(request)


@app.get("/api/admin/ai-operations/budget", dependencies=[Depends(require_admin)])
def ai_budget_status():
    """Return secret-free current AI budget usage and thresholds."""
    return budget_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Budget · منصة الفيزياء</title><style>
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--soft:#f8fafc}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text)}main{max-width:1000px;margin:auto;padding:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.metric{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:13px}.metric b{display:block;font-size:24px;margin-top:5px}.muted{color:var(--muted);font-size:13px}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}a{color:#175cd3;text-decoration:none}.bar{height:9px;background:#eaecf0;border-radius:999px;overflow:hidden;margin-top:8px}.bar span{display:block;height:100%;background:currentColor}.pill{display:inline-block;padding:5px 9px;border-radius:999px;background:var(--soft);border:1px solid var(--line)}
</style><main><div class=card><a href="/admin/ai-operations">← AI Operations</a> · <a href="/admin/dashboard">لوحة التحكم</a></div><div class=card><h1>AI Budget Guard</h1><p class=muted>حد أمان اختياري للاستدعاءات والتكلفة. لا يوقف أي شيء ما لم يتم ضبط سقف صريح من إعدادات البيئة.</p><div id=status></div></div><div id=cards class=grid></div><div class=card><h2>السياسة</h2><p>الحماية تشمل فقط المسارات التي تستدعي Gemini أو OpenAI أو OCR خارجيًا. التصحيح، اختيار الأسئلة، التصدير الحتمي والرسم العلمي الحتمي لا تتأثر.</p><p class=muted>ضبط التكلفة يحتاج أيضًا AI_MODEL_PRICING_JSON حتى تكون التكلفة المسجلة قابلة للحساب.</p></div><script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){let r=await fetch('/api/admin/ai-operations/budget');if(r.status===401){location.href='/admin/login';return}let x=await r.json().catch(()=>null);if(!r.ok||!x){status.innerHTML='<span class=bad>تعذر تحميل الميزانية.</span>';return}let cls=x.level==='blocked'?'bad':x.level==='warning'?'warn':'ok';status.innerHTML='<span class="pill '+cls+'">'+esc(x.level)+'</span> '+(x.configured?'الحماية مفعلة بقيم محددة.':'لا يوجد سقف محدد حاليًا؛ القياس فقط.');let names={daily_calls:'استدعاءات اليوم',daily_cost_usd:'تكلفة اليوم بالدولار',monthly_cost_usd:'تكلفة الشهر بالدولار'};cards.innerHTML=Object.entries(x.checks||{}).map(([k,v])=>{let pct=v.ratio==null?0:Math.min(100,Math.round(v.ratio*100));return '<div class=metric><span class=muted>'+esc(names[k]||k)+'</span><b>'+esc(v.used)+'</b><div class=muted>السقف: '+esc(v.limit??'غير محدد')+'</div><div class="bar '+(pct>=100?'bad':pct>=80?'warn':'ok')+'"><span style="width:'+pct+'%"></span></div></div>'}).join('')}
load();</script></main></html>'''


@app.get("/admin/ai-budget", response_class=HTMLResponse)
def ai_budget_page():
    return PAGE
