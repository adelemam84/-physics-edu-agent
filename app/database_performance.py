from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin


APP_QUERY_MARKERS = (
    "questions",
    "documents",
    "lessons",
    "quizzes",
    "attempts",
    "students",
    "guardians",
    "parent_notifications",
    "science_",
    "ai_usage_events",
    "request_rate_limits",
)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _signal(signal_id: str, severity: str, detail: str, evidence: dict) -> dict:
    return {
        "id": signal_id,
        "severity": severity,
        "detail": detail,
        "evidence": evidence,
    }


def evaluate_database_performance(
    summary: dict,
    tables: list[dict],
    queries: list[dict],
    *,
    query_stats_available: bool,
) -> dict:
    """Classify performance only when scale + latency justify attention."""
    signals: list[dict] = []

    connections = _int(summary.get("connections"))
    max_connections = max(1, _int(summary.get("max_connections")))
    pressure_pct = round(connections * 100.0 / max_connections, 1)
    if pressure_pct >= 90:
        signals.append(_signal(
            "connection_pressure",
            "error",
            f"ضغط الاتصالات {pressure_pct}% من الحد الأقصى",
            {"connections": connections, "max_connections": max_connections},
        ))
    elif pressure_pct >= 70:
        signals.append(_signal(
            "connection_pressure",
            "warning",
            f"ضغط الاتصالات {pressure_pct}% من الحد الأقصى",
            {"connections": connections, "max_connections": max_connections},
        ))

    sequential_candidates = []
    maintenance_candidates = []
    for raw in tables:
        table = str(raw.get("table_name") or "")
        size_bytes = _int(raw.get("table_bytes"))
        seq_scan = _int(raw.get("seq_scan"))
        idx_scan = _int(raw.get("idx_scan"))
        live = max(0, _int(raw.get("live_tuples")))
        dead = max(0, _int(raw.get("dead_tuples")))

        # Sequential scans are normal and often optimal on small tables.
        if (
            size_bytes >= 5 * 1024 * 1024
            and seq_scan >= 500
            and seq_scan > max(50, idx_scan * 2)
        ):
            sequential_candidates.append({
                "table": table,
                "size_bytes": size_bytes,
                "seq_scan": seq_scan,
                "idx_scan": idx_scan,
            })

        dead_ratio = dead / max(1, live + dead)
        if live >= 1000 and dead >= 500 and dead_ratio >= 0.25:
            maintenance_candidates.append({
                "table": table,
                "live_tuples": live,
                "dead_tuples": dead,
                "dead_ratio_pct": round(dead_ratio * 100, 1),
            })

    if sequential_candidates:
        signals.append(_signal(
            "large_sequential_scans",
            "warning",
            f"{len(sequential_candidates)} جدول كبير يحتاج مراجعة خطة الاستعلام",
            {"tables": sequential_candidates[:10]},
        ))
    if maintenance_candidates:
        signals.append(_signal(
            "vacuum_pressure",
            "warning",
            f"{len(maintenance_candidates)} جدول يحتاج مراجعة VACUUM/autovacuum",
            {"tables": maintenance_candidates[:10]},
        ))

    slow_queries = []
    severe_queries = []
    for raw in queries:
        calls = _int(raw.get("calls"))
        mean_ms = _float(raw.get("mean_exec_time_ms"))
        total_ms = _float(raw.get("total_exec_time_ms"))
        item = {
            "query": str(raw.get("query") or "")[:600],
            "calls": calls,
            "mean_exec_time_ms": round(mean_ms, 2),
            "total_exec_time_ms": round(total_ms, 2),
            "rows": _int(raw.get("rows")),
        }
        if calls >= 3 and mean_ms >= 2000:
            severe_queries.append(item)
        elif calls >= 3 and mean_ms >= 500:
            slow_queries.append(item)

    if severe_queries:
        signals.append(_signal(
            "slow_queries",
            "error",
            f"{len(severe_queries)} استعلام متكرر متوسطه ≥ 2s",
            {"queries": severe_queries[:10]},
        ))
    elif slow_queries:
        signals.append(_signal(
            "slow_queries",
            "warning",
            f"{len(slow_queries)} استعلام متكرر متوسطه ≥ 500ms",
            {"queries": slow_queries[:10]},
        ))

    errors = sum(1 for x in signals if x["severity"] == "error")
    warnings = sum(1 for x in signals if x["severity"] == "warning")
    state = "unhealthy" if errors else "degraded" if warnings else "healthy"
    return {
        "state": state,
        "healthy": state == "healthy",
        "error_count": errors,
        "warning_count": warnings,
        "signals": signals,
        "summary": {
            **summary,
            "connections": connections,
            "max_connections": max_connections,
            "connection_pressure_pct": pressure_pct,
            "table_count": len(tables),
            "query_stats_available": bool(query_stats_available),
            "app_query_sample_count": len(queries),
        },
        "tables": tables[:25],
        "queries": queries[:20],
        "policy": {
            "small_table_seq_scans_are_not_alerts": True,
            "query_warning_requires_calls": 3,
            "query_warning_mean_ms": 500,
            "query_error_mean_ms": 2000,
            "large_table_min_bytes": 5 * 1024 * 1024,
            "transaction_query_literals_expected_normalized": True,
        },
    }


def database_performance_snapshot() -> dict:
    try:
        with connect() as con:
            summary = dict(con.execute(
                """SELECT
                     pg_database_size(current_database())::bigint db_bytes,
                     current_setting('max_connections')::int max_connections,
                     (SELECT count(*) FROM pg_stat_activity
                       WHERE datname=current_database())::int connections"""
            ).fetchone())

            tables = [
                dict(row)
                for row in con.execute(
                    """SELECT
                         relname table_name,
                         pg_table_size(relid)::bigint table_bytes,
                         seq_scan::bigint,
                         idx_scan::bigint,
                         n_live_tup::bigint live_tuples,
                         n_dead_tup::bigint dead_tuples,
                         last_autovacuum
                       FROM pg_stat_user_tables
                       ORDER BY pg_table_size(relid) DESC, relname"""
                ).fetchall()
            ]

            ext = con.execute(
                """SELECT EXISTS(
                     SELECT 1 FROM pg_extension
                     WHERE extname='pg_stat_statements'
                   ) available"""
            ).fetchone()
            query_stats_available = bool(ext and ext["available"])
            queries: list[dict] = []
            if query_stats_available:
                rows = con.execute(
                    """SELECT query,calls::bigint,
                              total_exec_time::double precision total_exec_time_ms,
                              mean_exec_time::double precision mean_exec_time_ms,
                              rows::bigint
                       FROM pg_stat_statements s
                       JOIN pg_database d ON d.oid=s.dbid
                       WHERE d.datname=current_database()
                         AND (
                           lower(query) LIKE '%questions%'
                           OR lower(query) LIKE '%documents%'
                           OR lower(query) LIKE '%lessons%'
                           OR lower(query) LIKE '%quizzes%'
                           OR lower(query) LIKE '%attempts%'
                           OR lower(query) LIKE '%students%'
                           OR lower(query) LIKE '%guardians%'
                           OR lower(query) LIKE '%parent_notifications%'
                           OR lower(query) LIKE '%science_%'
                           OR lower(query) LIKE '%ai_usage_events%'
                           OR lower(query) LIKE '%request_rate_limits%'
                         )
                         AND lower(query) NOT LIKE '%pg_stat_%'
                       ORDER BY total_exec_time DESC
                       LIMIT 20"""
                ).fetchall()
                queries = [dict(row) for row in rows]
        return evaluate_database_performance(
            summary,
            tables,
            queries,
            query_stats_available=query_stats_available,
        )
    except Exception as exc:
        return {
            "state": "unhealthy",
            "healthy": False,
            "error_count": 1,
            "warning_count": 0,
            "signals": [{
                "id": "performance_probe",
                "severity": "error",
                "detail": "تعذر قراءة مؤشرات أداء PostgreSQL",
                "evidence": {"error": exc.__class__.__name__},
            }],
            "summary": {
                "connections": 0,
                "max_connections": 0,
                "connection_pressure_pct": 0,
                "table_count": 0,
                "query_stats_available": False,
                "app_query_sample_count": 0,
            },
            "tables": [],
            "queries": [],
            "policy": {},
        }


@app.get("/api/admin/database-performance", dependencies=[Depends(require_admin)])
def database_performance_api():
    return database_performance_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Database Performance</title><style>
:root{--bg:#f5f7fb;--card:#fff;--line:#e4e7ec;--text:#172033;--muted:#667085;--ok:#067647;--warn:#b54708;--bad:#b42318}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif}main{max-width:1150px;margin:auto;padding:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid var(--line);border-radius:12px;padding:12px}.big{font-size:26px;font-weight:700}.muted{color:var(--muted);font-size:13px}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:right;font-size:13px}pre{white-space:pre-wrap;word-break:break-word;font-size:12px}a{text-decoration:none;color:#175cd3}
</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/technical-observability">Technical Observability</a> · <a href="/admin/diagnostics">سلامة البيانات</a></div>
<div class=box><h1>Database Performance</h1><div id=status class=muted>جارٍ القياس...</div></div>
<div id=cards class="box grid"></div>
<div class=box><h2>Performance signals</h2><div id=signals></div></div>
<div class=box><h2>أكبر الجداول</h2><div id=tables></div></div>
<div class=box><h2>App query sample</h2><div id=queries></div></div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kb=n=>Math.round(Number(n||0)/1024)+' KB';
async function load(){let r=await fetch('/api/admin/database-performance');if(r.status===401){location.href='/admin/login';return}let x=await r.json().catch(()=>null);if(!r.ok||!x){status.innerHTML='<span class=bad>تعذر تحميل المؤشرات</span>';return}let cls=x.state==='healthy'?'ok':x.state==='degraded'?'warn':'bad';status.innerHTML='<b class="'+cls+'">'+e(x.state)+'</b> · أخطاء '+e(x.error_count)+' · تحذيرات '+e(x.warning_count);let s=x.summary||{};cards.innerHTML=[['حجم DB',kb(s.db_bytes)],['Connections',e(s.connections)+' / '+e(s.max_connections)],['ضغط الاتصالات',e(s.connection_pressure_pct)+'%'],['عدد الجداول',e(s.table_count)],['pg_stat_statements',s.query_stats_available?'مفعّل':'غير مفعّل']].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class=big>'+v[1]+'</div></div>').join('');signals.innerHTML=(x.signals||[]).length?(x.signals||[]).map(v=>'<div class="'+(v.severity==='error'?'bad':'warn')+'">• '+e(v.detail)+'</div>').join(''):'<span class=ok>✅ لا توجد إشارات أداء تستدعي تدخلًا.</span>';tables.innerHTML='<table><tr><th>الجدول</th><th>الحجم</th><th>Seq</th><th>Index</th><th>Live</th><th>Dead</th></tr>'+(x.tables||[]).map(v=>'<tr><td>'+e(v.table_name)+'</td><td>'+kb(v.table_bytes)+'</td><td>'+e(v.seq_scan)+'</td><td>'+e(v.idx_scan)+'</td><td>'+e(v.live_tuples)+'</td><td>'+e(v.dead_tuples)+'</td></tr>').join('')+'</table>';queries.innerHTML=(x.queries||[]).length?(x.queries||[]).map(v=>'<div class=card><b>'+e(v.calls)+' calls · avg '+Number(v.mean_exec_time_ms||0).toFixed(1)+'ms</b><pre>'+e(v.query)+'</pre></div>').join(''):'<span class=muted>لا توجد عينة استعلامات تطبيقية كافية منذ تفعيل الإحصاءات.</span>'}
load()
</script></main></html>'''


@app.get(
    "/admin/database-performance",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin)],
)
def database_performance_page():
    return PAGE
