from __future__ import annotations

import os

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .content_phase_guard import content_ingestion_enabled
from .external_creative_integrations import integration_status
from .main import app
from .security import require_admin


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _has(prefix: str) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for path in _paths())


def _whatsapp_configured() -> bool:
    required = (
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_GRAPH_VERSION",
        "WHATSAPP_RESULT_TEMPLATE",
        "WHATSAPP_LOW_SCORE_TEMPLATE",
        "WHATSAPP_WEEKLY_TEMPLATE",
        "WHATSAPP_WEBHOOK_VERIFY_TOKEN",
        "META_APP_SECRET",
    )
    return all(bool(os.getenv(name, "").strip()) for name in required)


def feature_status_snapshot() -> dict:
    routes = _paths()
    creative = integration_status()
    items = [
        {
            "id": "admin_command_center",
            "name": "لوحة الإدارة وتسجيل الدخول",
            "state": "active" if {"/api/admin/login", "/admin/dashboard"} <= routes else "needs_attention",
            "path": "/admin/dashboard",
            "detail": "جلسة HttpOnly ومركز قيادة الإدارة",
        },
        {
            "id": "student_sessions",
            "name": "جلسات الطلاب",
            "state": "active" if _has("/api/student/session") else "needs_attention",
            "path": "/student",
            "detail": "جلسات طالب آمنة بدل تمرير كود الطالب في الروابط",
        },
        {
            "id": "quiz_lifecycle",
            "name": "إدارة الاختبارات",
            "state": "active" if _has("/api/admin/quizzes/lifecycle") else "needs_attention",
            "path": "/admin/quizzes",
            "detail": "دورة حياة الاختبار والنشر المنضبط",
        },
        {
            "id": "adaptive_learning",
            "name": "التعلم والتدريب التكيفي",
            "state": "active" if _has("/api/student/adaptive-practice") else "needs_attention",
            "path": "/student/learning-suite",
            "detail": "تدريب موجه من الأسئلة المعتمدة",
        },
        {
            "id": "personal_exam_engine",
            "name": "محرك الامتحانات الشخصي",
            "state": "active" if _has("/api/admin/exams") or _has("/admin/exam-engine") else "deferred",
            "path": "/admin/quizzes",
            "detail": "أكواد دخول وجدولة ونزاهة الامتحان؛ يبقى مؤجلاً حتى دمج مسار الاختبارات المتقدم",
        },
        {
            "id": "lesson_studio",
            "name": "Lesson Studio",
            "state": "active" if _has("/api/admin/lesson-studio") else "needs_attention",
            "path": "/admin/lesson-studio/workspace",
            "detail": "إعداد الدروس والمراجعة والإصدارات",
        },
        {
            "id": "creative_integrations",
            "name": "التكاملات الإبداعية",
            "state": "active" if _has("/api/admin/lesson-studio/integrations") else "needs_attention",
            "path": "/admin/lesson-studio/integrations",
            "detail": "المسار الداخلي يعمل حتى لو كانت التكاملات الخارجية غير مضبوطة",
        },
        {
            "id": "canva",
            "name": "Canva Autofill",
            "state": "configured" if creative["canva"]["configured"] else "optional",
            "path": "/admin/lesson-studio/integrations",
            "detail": "اختياري؛ يستخدم OAuth وDesign Autofill عند توفر الإعدادات",
        },
        {
            "id": "google_slides",
            "name": "Google Slides",
            "state": "configured" if creative["google_slides"]["configured"] else "optional",
            "path": "/admin/lesson-studio/integrations",
            "detail": "اختياري؛ الاستيراد إلى Drive لا يمنع التصدير الداخلي",
        },
        {
            "id": "gemini_notebook_enterprise",
            "name": "Gemini Notebook Enterprise",
            "state": "deferred" if creative["gemini_notebook_enterprise"].get("blocked_by_free_only_policy") else ("configured" if creative["gemini_notebook_enterprise"]["configured"] else "optional"),
            "path": "/admin/lesson-studio/integrations",
            "detail": "مؤجل تلقائيًا أثناء سياسة AI_FREE_ONLY" if creative["gemini_notebook_enterprise"].get("blocked_by_free_only_policy") else "تكامل اختياري",
        },
        {
            "id": "ai_operations",
            "name": "AI Operations",
            "state": "active" if _has("/api/admin/ai-operations") else "needs_attention",
            "path": "/admin/ai-operations",
            "detail": "حوكمة المزودات والتكلفة والفشل والاسترجاع",
        },
        {
            "id": "whatsapp",
            "name": "WhatsApp لأولياء الأمور",
            "state": "configured" if _whatsapp_configured() else "optional",
            "path": "/admin/whatsapp-monitor",
            "detail": "التكامل اختياري ويحتاج مفاتيح Meta عند تفعيله",
        },
        {
            "id": "content_ingestion",
            "name": "رفع الأسئلة والمحتوى",
            "state": "active" if content_ingestion_enabled() else "locked",
            "path": "/admin/readiness",
            "detail": "يبقى مغلقًا ومؤجلاً حسب خطة المشروع الحالية",
        },
    ]
    counts = {}
    for item in items:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {"items": items, "counts": counts, "content_ingestion_locked": not content_ingestion_enabled()}


@app.get("/api/admin/feature-status", dependencies=[Depends(require_admin)])
def feature_status_api():
    return feature_status_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>حالة مميزات المنصة</title><style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--ok:#067647;--warn:#b54708;--bad:#b42318;--brand:#2447a8}*{box-sizing:border-box}body{font-family:system-ui;background:var(--bg);color:var(--text);margin:0}main{max-width:1150px;margin:auto;padding:18px}.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}.item{border:1px solid var(--line);border-radius:13px;padding:14px}.muted{color:var(--muted);font-size:13px}.active,.configured{color:var(--ok)}.optional,.deferred,.locked{color:var(--warn)}.needs_attention{color:var(--bad)}a{color:var(--brand);text-decoration:none}.pill{display:inline-block;padding:5px 9px;border-radius:999px;border:1px solid var(--line);font-size:12px;font-weight:700}</style><main><div class=box><a href="/admin/dashboard">← لوحة التحكم</a><h1>حالة مميزات المنصة</h1><p class=muted>فحص تشغيلي للمميزات المسجلة حاليًا بدون كشف أي مفاتيح أو أسرار.</p><div id=summary></div></div><div id=grid class=grid></div><script>
const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const labels={active:'مفعّل',configured:'مضبوط',optional:'اختياري',deferred:'مؤجل',locked:'مغلق',needs_attention:'يحتاج مراجعة'};async function load(){let r=await fetch('/api/admin/feature-status'),x=await r.json().catch(()=>null);if(r.status===401){location.href='/admin/login';return}if(!r.ok||!x){summary.textContent='تعذر تحميل حالة المميزات';return}summary.innerHTML=Object.entries(x.counts||{}).map(([k,v])=>'<span class="pill '+e(k)+'">'+e(labels[k]||k)+': '+e(v)+'</span>').join(' ');grid.innerHTML=(x.items||[]).map(v=>'<div class=item><div class="'+e(v.state)+'"><b>'+e(v.name)+'</b> · '+e(labels[v.state]||v.state)+'</div><p class=muted>'+e(v.detail)+'</p><a href="'+e(v.path)+'">فتح الميزة</a></div>').join('')}load();</script></main></html>'''


@app.get("/admin/feature-status", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def feature_status_page():
    return PAGE
