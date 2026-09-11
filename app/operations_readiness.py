from __future__ import annotations

import os

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .main import app
from .security import admin_configured, require_admin
from .system_readiness import system_readiness
from .services.ai_governance import governance_snapshot
from .services.ai_budget import budget_snapshot
from .services.ai_telemetry import usage_snapshot
from .services.storage import storage_configured
from .teacher_intervention_cases import intervention_summary


def _database_configured() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


def _release_status() -> dict:
    from .release_hardening import next_release_status
    return next_release_status()


def _student_session_configured() -> bool:
    """Controlled launch requires a dedicated student-session signing secret.

    Runtime fallback keys remain available for local/backward compatibility, but
    production readiness must not couple student sessions to admin or database
    credentials.
    """
    return bool(os.getenv("STUDENT_SESSION_SECRET", "").strip())


def build_operations_readiness() -> dict:
    """Aggregate release-critical and optional operational gates without secrets."""
    core = system_readiness()
    ai = governance_snapshot()
    budget = budget_snapshot()
    usage = usage_snapshot(24)
    interventions = intervention_summary()
    release = _release_status()

    deterministic_ok = bool(ai["principles"].get("grading_final_decision_is_deterministic"))
    no_ai_publish_ok = bool(
        ai["summary"].get("auto_approval_tasks") == 0
        and ai["summary"].get("auto_publish_tasks") == 0
        and ai["summary"].get("question_bank_write_tasks") == 0
    )
    budget_ok = not bool(budget.get("hard_block_active"))
    runtime_blockers = list(release.get("runtime_blockers") or [])
    content_gates = list(release.get("content_gates") or [])

    technical_checks = [
        {
            "id": "database_runtime",
            "name": "قاعدة البيانات",
            "ok": _database_configured(),
            "detail": "DATABASE_URL مفعّل والاتصال التشغيلي متاح" if _database_configured() else "DATABASE_URL غير مضبوط",
            "path": "/admin/diagnostics",
        },
        {
            "id": "admin_access",
            "name": "حماية الإدارة",
            "ok": admin_configured(),
            "detail": "ADMIN_API_KEY مفعّل" if admin_configured() else "ADMIN_API_KEY غير مضبوط",
            "path": "/admin/login",
        },
        {
            "id": "student_session",
            "name": "جلسة الطالب الآمنة",
            "ok": _student_session_configured(),
            "detail": "STUDENT_SESSION_SECRET مستقل ومفعّل" if _student_session_configured() else "يلزم ضبط STUDENT_SESSION_SECRET مستقل",
            "path": "/student",
        },
        {
            "id": "object_storage",
            "name": "تخزين ملفات المصدر",
            "ok": storage_configured(),
            "detail": "Object Storage credentials مكتملة" if storage_configured() else "إعدادات Object Storage غير مكتملة",
            "path": "/admin/readiness",
        },
        {
            "id": "runtime_activation",
            "name": "Runtime / AI activation",
            "ok": not runtime_blockers,
            "detail": "لا توجد Runtime blockers" if not runtime_blockers else " · ".join(runtime_blockers),
            "path": "/api/admin/next-release/status",
        },
        {
            "id": "deterministic_grading",
            "name": "التصحيح الحتمي",
            "ok": deterministic_ok,
            "detail": "الدرجة النهائية لا تعتمد على LLM",
            "path": "/admin/ai-operations",
        },
        {
            "id": "no_ai_auto_publish",
            "name": "حماية الاعتماد والنشر",
            "ok": no_ai_publish_ok,
            "detail": "لا يوجد نموذج يكتب البنك أو يعتمد أو ينشر تلقائيًا",
            "path": "/admin/ai-operations",
        },
        {
            "id": "ai_budget",
            "name": "سلامة ميزانية الذكاء",
            "ok": budget_ok,
            "detail": "AI budget غير محجوب" if budget_ok else "تم بلوغ سقف AI hard block",
            "path": "/admin/ai-budget",
        },
    ]
    technical_blockers = [x for x in technical_checks if not x["ok"]]
    ready_for_technical_handoff = not technical_blockers
    content_release_ready = bool(core["ready"]) and not content_gates

    required = [
        {
            "id": "core_content",
            "name": "المحتوى والبنك والاختبارات",
            "ok": bool(core["ready"]),
            "detail": "كل بوابات المحتوى الأساسية سليمة" if core["ready"] else "توجد بوابة محتوى أساسية غير مكتملة",
            "path": "/admin/readiness",
        },
        {
            "id": "technical_runtime",
            "name": "الجاهزية التقنية",
            "ok": ready_for_technical_handoff,
            "detail": "كل بوابات التقنية والأمان والتخزين جاهزة" if ready_for_technical_handoff else "توجد بوابة تقنية تحتاج إصلاحًا",
            "path": "/admin/operations-readiness",
        },
        {
            "id": "release_content_gates",
            "name": "بوابات محتوى الإصدار",
            "ok": not content_gates,
            "detail": "لا توجد بوابات محتوى إضافية" if not content_gates else " · ".join(content_gates),
            "path": "/api/admin/next-release/status",
        },
        {
            "id": "ai_budget",
            "name": "سلامة ميزانية الذكاء",
            "ok": budget_ok,
            "detail": (
                "لا يوجد سقف مفعّل؛ القياس فقط"
                if not budget.get("configured")
                else "داخل السقف المحدد"
                if budget.get("level") != "blocked"
                else "تم بلوغ سقف الاستخدام"
            ),
            "path": "/admin/ai-budget",
        },
    ]

    optional = [
        {
            "id": "gemini",
            "name": "Gemini Source Engine",
            "ok": bool(ai["providers"]["gemini"]["configured"]),
            "detail": "مفعّل للمصادر والمرئيات" if ai["providers"]["gemini"]["configured"] else "اختياري لبعض أدوات AI؛ المسارات الحتمية تظل تعمل",
            "path": "/admin/ai-operations",
        },
        {
            "id": "openai_reviewer",
            "name": "المراجع العلمي الثاني",
            "ok": bool(ai["providers"]["openai"]["configured"]),
            "detail": "GPT reviewer مفعّل" if ai["providers"]["openai"]["configured"] else "اختياري؛ لا يمنع المسار الأساسي",
            "path": "/admin/ai-operations",
        },
        {
            "id": "mathpix",
            "name": "Mathpix OCR verifier",
            "ok": bool(ai["providers"]["mathpix"]["configured"]),
            "detail": "مراجع OCR ثانٍ متاح" if ai["providers"]["mathpix"]["configured"] else "اختياري للتحقق الإضافي من STEM OCR",
            "path": "/admin/ai-operations",
        },
        {
            "id": "whatsapp",
            "name": "WhatsApp / أولياء الأمور",
            "ok": bool(all(core["whatsapp"].values())),
            "detail": "التكامل مكتمل" if all(core["whatsapp"].values()) else "اختياري حتى تشغيل إشعارات أولياء الأمور",
            "path": "/admin/parents",
        },
    ]

    blockers = [x for x in required if not x["ok"]]
    warnings = [x for x in optional if not x["ok"]]
    ai_summary = usage.get("summary") or {}
    return {
        "ready_for_technical_handoff": ready_for_technical_handoff,
        "technical_checks": technical_checks,
        "technical_blockers": technical_blockers,
        "content_release_ready": content_release_ready,
        "content_gates": content_gates,
        "release_state": release.get("release_state"),
        "ready_for_controlled_launch": not blockers,
        "required_checks": required,
        "optional_checks": optional,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {
            "ai_calls_24h": int(ai_summary.get("total_calls") or 0),
            "ai_failures_24h": int(ai_summary.get("failed_calls") or 0),
            "ai_tokens_24h": int(ai_summary.get("total_tokens") or 0),
            "open_interventions": int(interventions.get("open") or 0),
            "planned_interventions": int(interventions.get("planned") or 0),
            "completed_interventions": int(interventions.get("done") or 0),
            "interventions_improved": int(interventions.get("improved") or 0),
        },
        "launch_policy": {
            "technical_handoff_excludes_content_completeness": True,
            "controlled_launch_requires_all_required_checks": True,
            "optional_integrations_do_not_block_launch": True,
            "pdf_remains_scientific_source_of_truth": True,
            "teacher_remains_final_for_interventions": True,
            "ai_models_remain_advisory_for_scientific_content": True,
        },
        "next_actions": core.get("next_actions") or [],
    }


@app.get("/api/admin/operations-readiness", dependencies=[Depends(require_admin)])
def operations_readiness_api():
    return build_operations_readiness()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>جاهزية التشغيل النهائي</title><style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--good:#067647;--warn:#b54708;--bad:#b42318;--brand:#2447a8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif}main{max-width:1150px;margin:auto;padding:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}.hero{background:linear-gradient(135deg,#fff,#eef3ff)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card,.check{border:1px solid var(--line);border-radius:13px;padding:13px}.big{font-size:27px;font-weight:800}.muted{color:var(--muted);font-size:13px}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}a{color:var(--brand);text-decoration:none}.check{margin:8px 0}.pill{display:inline-block;padding:6px 10px;border-radius:999px;border:1px solid var(--line);font-weight:700}@media(max-width:650px){main{padding:9px}.box{padding:13px;border-radius:14px}.grid{grid-template-columns:1fr 1fr}}@media(max-width:390px){.grid{grid-template-columns:1fr}}</style><main>
<div class="box hero"><div><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/readiness">تفاصيل جاهزية المحتوى</a> · <a href="/admin/ai-operations">AI Operations</a> · <a href="/admin/interventions">تدخلات المدرس</a></div><h1>جاهزية التشغيل النهائي</h1><div id=status class=muted>جارٍ تجميع الحالة...</div></div><div id=metrics class=grid></div><div class=box><h2>الجاهزية التقنية</h2><div id=technical></div></div><div class=box><h2>بوابات المحتوى</h2><div id=contentGates></div></div><div class=box><h2>بوابات مطلوبة للتشغيل</h2><div id=required></div></div><div class=box><h2>تكاملات اختيارية</h2><div id=optional></div></div><div class=box><h2>الخطوات المتبقية</h2><div id=actions></div></div><script>
const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function renderCheck(v,optional=false){return '<div class="check '+(v.ok?'good':optional?'warn':'bad')+'">'+(v.ok?'✅ ':optional?'○ ':'⚠️ ')+'<b>'+e(v.name)+'</b><div class=muted>'+e(v.detail)+'</div><a href="'+e(v.path)+'">فتح التفاصيل</a></div>'}async function load(){let r=await fetch('/api/admin/operations-readiness'),x=await r.json().catch(()=>null);if(r.status===401){location.href='/admin/login';return}if(!r.ok||!x){status.innerHTML='<span class=bad>تعذر تجميع الجاهزية.</span>';return}status.innerHTML=(x.ready_for_technical_handoff?'<span class="pill good">✅ Technical Ready</span>':'<span class="pill bad">⚠️ Technical Blockers</span>')+' '+(x.ready_for_controlled_launch?'<span class="pill good">✅ Controlled Launch Ready</span>':'<span class="pill warn">○ Content/Launch Gates Open</span>');technical.innerHTML=(x.technical_checks||[]).map(v=>renderCheck(v,false)).join('');contentGates.innerHTML=(x.content_gates||[]).length?(x.content_gates||[]).map(v=>'<div class="check warn">○ '+e(v)+'</div>').join(''):'<div class="check good">✅ لا توجد بوابات محتوى مفتوحة.</div>';let m=x.metrics||{};metrics.innerHTML=[['AI / 24 ساعة',m.ai_calls_24h],['أخطاء AI',m.ai_failures_24h],['توكنات AI',m.ai_tokens_24h],['تدخلات مفتوحة',m.open_interventions],['تدخلات مكتملة',m.completed_interventions],['تحسن بعد تدخل',m.interventions_improved]].map(v=>'<div class=card><div class=muted>'+e(v[0])+'</div><div class=big>'+e(v[1]??0)+'</div></div>').join('');required.innerHTML=(x.required_checks||[]).map(v=>renderCheck(v,false)).join('');optional.innerHTML=(x.optional_checks||[]).map(v=>renderCheck(v,true)).join('');actions.innerHTML=(x.next_actions||[]).length?(x.next_actions||[]).map(v=>'<div class=check><a href="'+e(v.path)+'"><b>'+e(v.title)+'</b></a><div class=muted>'+(v.owner==='user'?'يتطلب بيانات/إجراء خارجي':'يُستكمل داخل النظام')+'</div></div>').join(''):'<div class="check good">✅ لا توجد خطوة إعداد أساسية متبقية.</div>'}load();</script></main></html>'''


@app.get("/admin/operations-readiness", response_class=HTMLResponse)
def operations_readiness_page():
    return PAGE
