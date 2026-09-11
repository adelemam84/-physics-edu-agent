from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect, database_connection_profile
from .main import app
from .operations_readiness import build_operations_readiness
from .security import require_admin
from .services.ai_telemetry import usage_snapshot
from .services.rate_limit import policy
from .services.runtime_identity import runtime_identity


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return value if value >= 0 else float(default)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except ValueError:
        return int(default)
    return value if value >= 0 else int(default)


def _database_probe() -> dict:
    started = time.perf_counter()
    try:
        with connect() as con:
            row = con.execute("SELECT 1 ok").fetchone()
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": bool(row and int(row["ok"]) == 1),
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": exc.__class__.__name__,
        }


def _sync_probe(stale_minutes: int) -> dict:
    try:
        with connect() as con:
            exists = con.execute(
                "SELECT to_regclass('public.gemini_source_sync') name"
            ).fetchone()["name"]
            if not exists:
                return {
                    "state": "not_initialized",
                    "ok": True,
                    "total": 0,
                    "active": 0,
                    "processing": 0,
                    "failed": 0,
                    "stale_processing": 0,
                }
            row = con.execute(
                """SELECT
                     count(*) total,
                     count(*) FILTER(WHERE state='active') active,
                     count(*) FILTER(WHERE state='processing') processing,
                     count(*) FILTER(WHERE state='failed') failed,
                     count(*) FILTER(
                       WHERE state='processing'
                         AND updated_at < now() - (%s * interval '1 minute')
                     ) stale_processing
                   FROM gemini_source_sync""",
                (stale_minutes,),
            ).fetchone()
    except Exception as exc:
        return {
            "state": "probe_failed",
            "ok": False,
            "error": exc.__class__.__name__,
            "total": 0,
            "active": 0,
            "processing": 0,
            "failed": 0,
            "stale_processing": 0,
        }

    data = {k: int(row[k] or 0) for k in (
        "total", "active", "processing", "failed", "stale_processing"
    )}
    data["state"] = "active" if data["total"] else "initialized_empty"
    data["ok"] = data["failed"] == 0 and data["stale_processing"] == 0
    return data


def _ai_probe(hours: int = 24) -> dict:
    try:
        usage = usage_snapshot(hours)
    except Exception as exc:
        return {
            "ok": False,
            "state": "probe_failed",
            "error": exc.__class__.__name__,
            "calls": 0,
            "failures": 0,
            "failure_pct": 0.0,
            "avg_latency_ms": 0,
        }
    summary = usage.get("summary") or {}
    calls = int(summary.get("total_calls") or 0)
    failures = int(summary.get("failed_calls") or 0)
    return {
        "ok": True,
        "state": "observed" if calls else "no_recent_calls",
        "calls": calls,
        "failures": failures,
        "failure_pct": round(failures / calls * 100.0, 2) if calls else 0.0,
        "avg_latency_ms": int(summary.get("avg_latency_ms") or 0),
    }


RATE_LIMIT_POLICY_DEFAULTS = {
    "admin_login": (8, 900),
    "student_login": (12, 600),
    "adaptive_quiz_create": (6, 3600),
    "student_review_pdf": (20, 3600),
    "admin_ai_research": (30, 3600),
    "admin_lesson_process": (12, 3600),
    "admin_second_review": (10, 3600),
    "admin_visual_review": (30, 3600),
    "admin_visual_review_batch": (8, 3600),
    "admin_phase2_bootstrap": (2, 3600),
}


def _rate_limit_probe(near_pct: float) -> dict:
    try:
        with connect() as con:
            rows = list(con.execute(
                """SELECT scope,hits,window_start
                   FROM request_rate_limits
                   WHERE updated_at >= now() - interval '7 days'"""
            ).fetchall())
    except Exception as exc:
        return {
            "ok": False,
            "state": "probe_failed",
            "error": exc.__class__.__name__,
            "active_subjects": 0,
            "near_limit_subjects": 0,
            "blocked_subjects": 0,
            "scopes": [],
        }

    now = datetime.now(timezone.utc)
    grouped: dict[str, dict] = {}
    for raw in rows:
        scope = str(raw.get("scope") or "")
        defaults = RATE_LIMIT_POLICY_DEFAULTS.get(scope)
        if not defaults:
            continue
        limit, window_seconds = policy(
            scope,
            default_limit=defaults[0],
            default_window_seconds=defaults[1],
        )
        started = raw.get("window_start")
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if (now - started).total_seconds() >= window_seconds:
            continue
        hits = max(0, int(raw.get("hits") or 0))
        item = grouped.setdefault(scope, {
            "scope": scope,
            "limit": int(limit),
            "window_seconds": int(window_seconds),
            "active_subjects": 0,
            "near_limit_subjects": 0,
            "blocked_subjects": 0,
            "max_hits": 0,
        })
        item["active_subjects"] += 1
        item["max_hits"] = max(item["max_hits"], hits)
        near_threshold = max(1, int(math.ceil(limit * near_pct / 100.0)))
        if hits >= near_threshold:
            item["near_limit_subjects"] += 1
        if hits > limit:
            item["blocked_subjects"] += 1

    scopes = sorted(grouped.values(), key=lambda x: x["scope"])
    return {
        "ok": True,
        "state": "observed" if scopes else "idle",
        "active_subjects": sum(x["active_subjects"] for x in scopes),
        "near_limit_subjects": sum(x["near_limit_subjects"] for x in scopes),
        "blocked_subjects": sum(x["blocked_subjects"] for x in scopes),
        "scopes": scopes,
        "privacy": {
            "raw_subjects_returned": False,
            "subject_hashes_returned": False,
            "only_aggregates_returned": True,
        },
    }


def _signal(
    signal_id: str,
    name: str,
    severity: str,
    ok: bool,
    detail: str,
    path: str,
    evidence: dict | None = None,
) -> dict:
    return {
        "id": signal_id,
        "name": name,
        "severity": severity,
        "ok": bool(ok),
        "detail": detail,
        "path": path,
        "evidence": evidence or {},
    }


def technical_observability_snapshot(*, readiness_snapshot: dict | None = None) -> dict:
    db_warn_ms = _int_env("TECH_OBSERVABILITY_DB_WARN_MS", 500)
    db_error_ms = _int_env("TECH_OBSERVABILITY_DB_ERROR_MS", 2000)
    ai_min_calls = _int_env("TECH_OBSERVABILITY_AI_MIN_CALLS", 5)
    ai_failure_warn_pct = _float_env("TECH_OBSERVABILITY_AI_FAILURE_WARN_PCT", 10.0)
    ai_failure_error_pct = _float_env("TECH_OBSERVABILITY_AI_FAILURE_ERROR_PCT", 25.0)
    ai_latency_warn_ms = _int_env("TECH_OBSERVABILITY_AI_LATENCY_WARN_MS", 15000)
    sync_stale_minutes = _int_env("TECH_OBSERVABILITY_SYNC_STALE_MINUTES", 30)
    rate_limit_near_pct = min(
        100.0,
        max(1.0, _float_env("TECH_OBSERVABILITY_RATE_LIMIT_NEAR_PCT", 80.0)),
    )
    rate_limit_blocked_error_subjects = max(
        1,
        _int_env("TECH_OBSERVABILITY_RATE_LIMIT_BLOCKED_ERROR_SUBJECTS", 5),
    )

    readiness = readiness_snapshot if readiness_snapshot is not None else build_operations_readiness()
    db = _database_probe()
    ai = _ai_probe(24)
    sync = _sync_probe(sync_stale_minutes)
    rate_limits = _rate_limit_probe(rate_limit_near_pct)
    identity = runtime_identity(application_version=app.version)
    database_profile = database_connection_profile()

    signals: list[dict] = []

    if not db["ok"]:
        signals.append(_signal(
            "database_probe", "Database probe", "error", False,
            "تعذر تنفيذ SELECT 1 على قاعدة البيانات",
            "/admin/diagnostics", db,
        ))
    elif db["latency_ms"] >= db_error_ms:
        signals.append(_signal(
            "database_latency", "Database latency", "error", False,
            f'زمن فحص قاعدة البيانات {db["latency_ms"]}ms يتجاوز حد الخطأ {db_error_ms}ms',
            "/admin/diagnostics", db,
        ))
    elif db["latency_ms"] >= db_warn_ms:
        signals.append(_signal(
            "database_latency", "Database latency", "warning", False,
            f'زمن فحص قاعدة البيانات {db["latency_ms"]}ms يتجاوز حد التحذير {db_warn_ms}ms',
            "/admin/diagnostics", db,
        ))
    else:
        signals.append(_signal(
            "database_probe", "Database probe", "info", True,
            f'قاعدة البيانات تستجيب في {db["latency_ms"]}ms',
            "/admin/diagnostics", db,
        ))

    if not database_profile.get("migration_safe"):
        signals.append(_signal(
            "database_migration_path", "Database connection strategy", "error", False,
            "مسار migrations ليس Direct وآمنًا؛ لا يجب تشغيل DDL عبر PgBouncer",
            "/admin/technical-observability", database_profile,
        ))
    elif (
        database_profile.get("on_vercel")
        and database_profile.get("is_neon")
        and database_profile.get("runtime_mode") != "pooled"
    ):
        signals.append(_signal(
            "database_runtime_pooling", "Database connection strategy", "warning", False,
            "Runtime على Vercel يستخدم اتصال Neon مباشر؛ PgBouncer موصى به لتقليل ضغط الاتصالات",
            "/admin/technical-observability", database_profile,
        ))
    else:
        signals.append(_signal(
            "database_connection_strategy", "Database connection strategy", "info", True,
            (
                f'Runtime={database_profile.get("runtime_mode")} · '
                f'Migrations={database_profile.get("migration_mode")} · '
                f'Policy={database_profile.get("pooling_policy")}'
            ),
            "/admin/technical-observability", database_profile,
        ))

    if not ai["ok"]:
        signals.append(_signal(
            "ai_telemetry_probe", "AI telemetry", "error", False,
            "تعذر قراءة AI telemetry",
            "/admin/ai-operations", ai,
        ))
    elif ai["calls"] >= ai_min_calls and ai["failure_pct"] >= ai_failure_error_pct:
        signals.append(_signal(
            "ai_failure_rate", "AI failure rate", "error", False,
            f'معدل فشل AI خلال 24 ساعة = {ai["failure_pct"]}%',
            "/admin/ai-operations", ai,
        ))
    elif ai["calls"] >= ai_min_calls and ai["failure_pct"] >= ai_failure_warn_pct:
        signals.append(_signal(
            "ai_failure_rate", "AI failure rate", "warning", False,
            f'معدل فشل AI خلال 24 ساعة = {ai["failure_pct"]}%',
            "/admin/ai-operations", ai,
        ))
    elif ai["avg_latency_ms"] >= ai_latency_warn_ms and ai["calls"]:
        signals.append(_signal(
            "ai_latency", "AI latency", "warning", False,
            f'متوسط زمن AI خلال 24 ساعة = {ai["avg_latency_ms"]}ms',
            "/admin/ai-operations", ai,
        ))
    else:
        signals.append(_signal(
            "ai_telemetry", "AI telemetry", "info", True,
            (
                f'{ai["calls"]} استدعاء خلال 24 ساعة · فشل {ai["failure_pct"]}%'
                if ai["calls"]
                else "لا توجد استدعاءات AI حديثة؛ لا يوجد إنذار"
            ),
            "/admin/ai-operations", ai,
        ))

    if not sync["ok"] and sync["state"] == "probe_failed":
        signals.append(_signal(
            "source_sync_probe", "Gemini source sync", "error", False,
            "تعذر قراءة حالة Gemini source sync",
            "/admin/research-engine", sync,
        ))
    elif sync["failed"]:
        signals.append(_signal(
            "source_sync_failed", "Gemini source sync", "warning", False,
            f'{sync["failed"]} عملية فهرسة فاشلة',
            "/admin/research-engine", sync,
        ))
    elif sync["stale_processing"]:
        signals.append(_signal(
            "source_sync_stale", "Gemini source sync", "warning", False,
            f'{sync["stale_processing"]} عملية processing أقدم من {sync_stale_minutes} دقيقة',
            "/admin/research-engine", sync,
        ))
    else:
        signals.append(_signal(
            "source_sync", "Gemini source sync", "info", True,
            (
                "لم يبدأ Source Indexing بعد؛ هذه حالة طبيعية وليست خطأ"
                if sync["state"] == "not_initialized"
                else f'{sync["active"]} active · {sync["processing"]} processing'
            ),
            "/admin/research-engine", sync,
        ))

    if not rate_limits["ok"]:
        signals.append(_signal(
            "rate_limit_probe", "Rate-limit telemetry", "error", False,
            "تعذر قراءة ضغط Rate Limits",
            "/admin/technical-observability", rate_limits,
        ))
    elif rate_limits["blocked_subjects"] >= rate_limit_blocked_error_subjects:
        signals.append(_signal(
            "rate_limit_pressure", "Rate-limit pressure", "error", False,
            f'{rate_limits["blocked_subjects"]} subjects تجاوزت الحدود الحالية',
            "/admin/technical-observability", rate_limits,
        ))
    elif rate_limits["blocked_subjects"] > 0:
        signals.append(_signal(
            "rate_limit_pressure", "Rate-limit pressure", "warning", False,
            f'{rate_limits["blocked_subjects"]} subject محجوب مؤقتًا بسبب 429',
            "/admin/technical-observability", rate_limits,
        ))
    elif rate_limits["near_limit_subjects"] > 0:
        signals.append(_signal(
            "rate_limit_near", "Rate-limit pressure", "warning", False,
            f'{rate_limits["near_limit_subjects"]} subject قريب من الحد المؤقت',
            "/admin/technical-observability", rate_limits,
        ))
    else:
        signals.append(_signal(
            "rate_limit_health", "Rate-limit pressure", "info", True,
            (
                f'{rate_limits["active_subjects"]} subject نشط بدون ضغط'
                if rate_limits["active_subjects"]
                else "لا يوجد ضغط Rate Limit نشط"
            ),
            "/admin/technical-observability", rate_limits,
        ))

    if (
        identity.get("provider") == "vercel"
        and identity.get("production_environment")
        and not identity.get("current_runtime_is_production_main")
    ):
        signals.append(_signal(
            "deployment_drift", "Deployment provenance", "error", False,
            "Production runtime لا يثبت أنه منشور من main مع commit SHA صالح",
            "/admin/project-closure", identity,
        ))
    elif identity.get("provider") == "vercel" and identity.get("production_environment"):
        signals.append(_signal(
            "deployment_identity", "Deployment provenance", "info", True,
            f'Production main · {identity.get("git_commit_short") or "sha unavailable"} · v{app.version}',
            "/admin/project-closure", identity,
        ))
    else:
        signals.append(_signal(
            "deployment_identity", "Deployment provenance", "info", True,
            f'{identity.get("drift_state")} · v{app.version}',
            "/admin/project-closure", identity,
        ))

    if not readiness.get("ready_for_technical_handoff"):
        signals.append(_signal(
            "technical_readiness", "Technical readiness", "error", False,
            f'{len(readiness.get("technical_blockers") or [])} technical blocker(s)',
            "/admin/operations-readiness",
            {"technical_blockers": readiness.get("technical_blockers") or []},
        ))
    else:
        signals.append(_signal(
            "technical_readiness", "Technical readiness", "info", True,
            "المنصة جاهزة تقنيًا؛ بوابات المحتوى منفصلة",
            "/admin/operations-readiness",
            {"content_gates": readiness.get("content_gates") or []},
        ))

    error_count = sum(1 for item in signals if not item["ok"] and item["severity"] == "error")
    warning_count = sum(1 for item in signals if not item["ok"] and item["severity"] == "warning")
    state = "unhealthy" if error_count else "degraded" if warning_count else "healthy"
    return {
        "state": state,
        "healthy": state == "healthy",
        "error_count": error_count,
        "warning_count": warning_count,
        "signals": signals,
        "thresholds": {
            "db_warn_ms": db_warn_ms,
            "db_error_ms": db_error_ms,
            "ai_min_calls": ai_min_calls,
            "ai_failure_warn_pct": ai_failure_warn_pct,
            "ai_failure_error_pct": ai_failure_error_pct,
            "ai_latency_warn_ms": ai_latency_warn_ms,
            "sync_stale_minutes": sync_stale_minutes,
            "rate_limit_near_pct": rate_limit_near_pct,
            "rate_limit_blocked_error_subjects": rate_limit_blocked_error_subjects,
        },
        "runtime_identity": identity,
        "database_connection": database_profile,
        "content_gates_are_not_technical_errors": True,
    }


@app.get("/api/admin/technical-observability", dependencies=[Depends(require_admin)])
def technical_observability_api():
    return technical_observability_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Technical Observability</title><style>
:root{--bg:#f5f7fb;--card:#fff;--line:#e4e7ec;--text:#172033;--muted:#667085;--ok:#067647;--warn:#b54708;--bad:#b42318}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif}main{max-width:1100px;margin:auto;padding:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.signal{border:1px solid var(--line);border-radius:12px;padding:12px}.ok{color:var(--ok)}.warning{color:var(--warn)}.error{color:var(--bad)}.muted{color:var(--muted);font-size:13px}a{text-decoration:none;color:#175cd3}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:6px 10px;margin:3px}
</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/operations-readiness">Operations Readiness</a> · <a href="/admin/alerts">التنبيهات</a> · <a href="/admin/ai-operations">AI Operations</a></div>
<div class=box><h1>Technical Observability</h1><div id=status class=muted>جارٍ القياس...</div></div>
<div id=signals class="box grid"></div>
<div class=box><h2>Thresholds</h2><div id=thresholds class=muted></div></div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){let r=await fetch('/api/admin/technical-observability');if(r.status===401){location.href='/admin/login';return}let x=await r.json().catch(()=>null);if(!r.ok||!x){status.innerHTML='<span class=error>تعذر تحميل القياس.</span>';return}let cls=x.state==='healthy'?'ok':x.state==='degraded'?'warning':'error';status.innerHTML='<span class="pill '+cls+'">'+e(x.state)+'</span> · أخطاء '+e(x.error_count)+' · تحذيرات '+e(x.warning_count);signals.innerHTML=(x.signals||[]).map(s=>'<div class="signal '+(s.ok?'ok':e(s.severity))+'"><b>'+e(s.name)+'</b><div>'+e(s.detail)+'</div><a href="'+e(s.path)+'">فتح التفاصيل</a></div>').join('');thresholds.textContent=Object.entries(x.thresholds||{}).map(([k,v])=>k+'='+v).join(' · ')}
load()
</script></main></html>'''


@app.get("/admin/technical-observability", response_class=HTMLResponse)
def technical_observability_page():
    return PAGE
