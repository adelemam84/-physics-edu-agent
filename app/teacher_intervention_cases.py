from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .security import require_admin
from .teacher_intervention_queue import build_intervention_queue


InterventionStatus = Literal["open", "planned", "done", "dismissed"]
InterventionType = Literal[
    "baseline_assessment",
    "reengage_student",
    "adaptive_practice",
    "mistake_review",
    "monitor",
    "custom",
]


class InterventionCreate(BaseModel):
    student_id: int = Field(gt=0)
    intervention_type: InterventionType
    note: str | None = Field(default=None, max_length=3000)
    planned_for: datetime | None = None


class InterventionPatch(BaseModel):
    status: InterventionStatus | None = None
    note: str | None = Field(default=None, max_length=3000)
    outcome_note: str | None = Field(default=None, max_length=3000)
    planned_for: datetime | None = None


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"open", "planned", "done", "dismissed"},
    "planned": {"open", "planned", "done", "dismissed"},
    "done": {"done"},
    "dismissed": {"dismissed"},
}


def validate_transition(current: str, target: str) -> None:
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            409,
            {
                "message": "لا يمكن تنفيذ هذا الانتقال في حالة التدخل الحالية.",
                "current": current,
                "target": target,
            },
        )


def _schema() -> None:
    with connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS teacher_interventions(
              id bigserial PRIMARY KEY,
              student_id bigint NOT NULL REFERENCES students(id) ON DELETE CASCADE,
              intervention_type text NOT NULL,
              status text NOT NULL DEFAULT 'open',
              note text,
              planned_for timestamptz,
              pre_risk_score integer,
              pre_priority text,
              post_risk_score integer,
              post_priority text,
              outcome_note text,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              completed_at timestamptz,
              CONSTRAINT teacher_interventions_status_check
                CHECK(status IN ('open','planned','done','dismissed')),
              CONSTRAINT teacher_interventions_type_check
                CHECK(intervention_type IN (
                  'baseline_assessment','reengage_student','adaptive_practice',
                  'mistake_review','monitor','custom'
                )),
              CONSTRAINT teacher_interventions_pre_risk_check
                CHECK(pre_risk_score IS NULL OR (pre_risk_score>=0 AND pre_risk_score<=100)),
              CONSTRAINT teacher_interventions_post_risk_check
                CHECK(post_risk_score IS NULL OR (post_risk_score>=0 AND post_risk_score<=100))
            )"""
        )
        con.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_teacher_interventions_active_student
               ON teacher_interventions(student_id)
               WHERE status IN ('open','planned')"""
        )
        con.execute(
            """CREATE INDEX IF NOT EXISTS idx_teacher_interventions_status_updated
               ON teacher_interventions(status,updated_at DESC)"""
        )


def _risk_for_student(student_id: int) -> dict | None:
    data = build_intervention_queue(limit=300)
    return next((x for x in data["items"] if int(x["student_id"]) == int(student_id)), None)


def _case_rows(status: str | None = None, limit: int = 100) -> list[dict]:
    _schema()
    limit = min(max(int(limit), 1), 300)
    where = ""
    params: list[object] = []
    if status:
        if status not in {"open", "planned", "done", "dismissed"}:
            raise HTTPException(400, "Invalid status")
        where = "WHERE i.status=%s"
        params.append(status)
    params.append(limit)
    with connect() as con:
        rows = list(
            con.execute(
                f"""SELECT i.id,i.student_id,s.name student_name,i.intervention_type,i.status,
                      i.note,i.planned_for,i.pre_risk_score,i.pre_priority,
                      i.post_risk_score,i.post_priority,i.outcome_note,
                      i.created_at,i.updated_at,i.completed_at
                   FROM teacher_interventions i
                   JOIN students s ON s.id=i.student_id
                   {where}
                   ORDER BY CASE i.status WHEN 'open' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
                            i.updated_at DESC,i.id DESC
                   LIMIT %s""",
                params,
            ).fetchall()
        )
    return [dict(x) for x in rows]


@app.get("/api/admin/interventions", dependencies=[Depends(require_admin)])
def list_interventions(status: str | None = None, limit: int = 100):
    rows = _case_rows(status=status, limit=limit)
    return {
        "count": len(rows),
        "items": rows,
        "policy": {
            "risk_engine": "deterministic_rules",
            "teacher_decision_final": True,
            "automatic_messaging": False,
            "llm_intervention_decisions": False,
        },
    }


@app.post("/api/admin/interventions", dependencies=[Depends(require_admin)])
def create_intervention(payload: InterventionCreate):
    _schema()
    risk = _risk_for_student(payload.student_id)
    if not risk:
        raise HTTPException(404, "الطالب غير موجود في قائمة المتابعة")
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s", (payload.student_id,)).fetchone():
            raise HTTPException(404, "الطالب غير موجود")
        active = con.execute(
            """SELECT id,status FROM teacher_interventions
               WHERE student_id=%s AND status IN ('open','planned') LIMIT 1""",
            (payload.student_id,),
        ).fetchone()
        if active:
            raise HTTPException(
                409,
                {
                    "message": "يوجد تدخل مفتوح بالفعل لهذا الطالب.",
                    "intervention_id": active["id"],
                    "status": active["status"],
                },
            )
        row = con.execute(
            """INSERT INTO teacher_interventions(
                 student_id,intervention_type,status,note,planned_for,
                 pre_risk_score,pre_priority
               ) VALUES(%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                payload.student_id,
                payload.intervention_type,
                "planned" if payload.planned_for else "open",
                payload.note,
                payload.planned_for,
                int(risk["score"]),
                str(risk["priority"]),
            ),
        ).fetchone()
    return {
        **dict(row),
        "risk_reasons_at_open": risk.get("reasons") or [],
        "automatic_message_sent": False,
    }


@app.patch("/api/admin/interventions/{intervention_id}", dependencies=[Depends(require_admin)])
def update_intervention(intervention_id: int, payload: InterventionPatch):
    _schema()
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, "No changes")
    with connect() as con:
        current = con.execute(
            "SELECT * FROM teacher_interventions WHERE id=%s", (intervention_id,)
        ).fetchone()
    if not current:
        raise HTTPException(404, "حالة التدخل غير موجودة")

    target = str(values.get("status") or current["status"])
    validate_transition(str(current["status"]), target)
    risk = _risk_for_student(int(current["student_id"])) if target == "done" else None

    setters: list[str] = ["updated_at=now()"]
    params: list[object] = []
    for key in ("status", "note", "outcome_note", "planned_for"):
        if key in values:
            setters.append(f"{key}=%s")
            params.append(values[key])
    if target == "done" and str(current["status"]) != "done":
        setters.extend(["completed_at=now()", "post_risk_score=%s", "post_priority=%s"])
        params.extend([
            int(risk["score"]) if risk else None,
            str(risk["priority"]) if risk else None,
        ])
    params.append(intervention_id)
    with connect() as con:
        row = con.execute(
            f"UPDATE teacher_interventions SET {', '.join(setters)} WHERE id=%s RETURNING *",
            params,
        ).fetchone()
    return dict(row)


@app.get("/api/admin/interventions/summary", dependencies=[Depends(require_admin)])
def intervention_summary():
    _schema()
    with connect() as con:
        row = con.execute(
            """SELECT count(*) total,
              count(*) FILTER(WHERE status='open') open,
              count(*) FILTER(WHERE status='planned') planned,
              count(*) FILTER(WHERE status='done') done,
              count(*) FILTER(WHERE status='dismissed') dismissed,
              count(*) FILTER(
                WHERE status='done' AND pre_risk_score IS NOT NULL AND post_risk_score IS NOT NULL
                  AND post_risk_score < pre_risk_score
              ) improved,
              round(avg(pre_risk_score-post_risk_score) FILTER(
                WHERE status='done' AND pre_risk_score IS NOT NULL AND post_risk_score IS NOT NULL
              ),1) average_risk_reduction
              FROM teacher_interventions"""
        ).fetchone()
    return dict(row or {})


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز تدخل المدرس</title><style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--brand:#2447a8;--bad:#b42318;--warn:#b54708;--good:#067647}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif}main{max-width:1250px;margin:auto;padding:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.card{border:1px solid var(--line);border-radius:13px;padding:12px}.big{font-size:26px;font-weight:800}.muted{color:var(--muted);font-size:13px}.bad{color:var(--bad)}.warn{color:var(--warn)}.good{color:var(--good)}button,select{padding:9px 11px;border:1px solid var(--line);border-radius:9px;font:inherit;background:white;cursor:pointer}button.primary{background:var(--brand);color:#fff;border-color:var(--brand)}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}a{color:#175cd3;text-decoration:none}.scroll{overflow:auto}@media(max-width:760px){main{padding:9px}.box{padding:12px;border-radius:14px}table{min-width:1000px}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/intervention-queue">قائمة المخاطر</a><h1>مركز تدخل المدرس</h1><p class=muted>سجّل التدخل البشري ونتيجته. المنصة تقيس إشارات الخطر فقط ولا ترسل رسالة أو تتخذ قرارًا بدل المدرس.</p><div id=msg class=muted aria-live=polite></div></div><div id=summary class=grid></div><div class="box scroll"><h2>حالات التدخل</h2><table><thead><tr><th>الطالب</th><th>الإجراء</th><th>الحالة</th><th>قبل</th><th>بعد</th><th>الملاحظة</th><th>الإجراء</th></tr></thead><tbody id=cases></tbody></table></div><div class="box scroll"><h2>طلاب يحتاجون قرار المدرس</h2><table><thead><tr><th>الطالب</th><th>الأولوية</th><th>السبب</th><th>الاقتراح</th><th></th></tr></thead><tbody id=queue></tbody></table></div><script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const labels={baseline_assessment:'قياس خط أساس',reengage_student:'إعادة إشراك',adaptive_practice:'تدريب علاجي',mistake_review:'مراجعة أخطاء',monitor:'متابعة',custom:'مخصص'};async function api(url,opt){let r=await fetch(url,opt),x=await r.json().catch(()=>null);if(!r.ok)throw new Error(typeof x?.detail==='string'?x.detail:(x?.detail?.message||'تعذر تنفيذ العملية'));return x}async function openCase(id,type){let note=prompt('ملاحظة المدرس عند فتح الحالة (اختياري):')||null;try{await api('/api/admin/interventions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_id:id,intervention_type:type,note})});msg.textContent='تم فتح حالة تدخل.';load()}catch(e){msg.textContent=e.message}}async function finish(id){let outcome=prompt('سجل نتيجة التدخل قبل الإغلاق:');if(outcome===null)return;try{await api('/api/admin/interventions/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'done',outcome_note:outcome})});msg.textContent='تم إغلاق التدخل وقياس الخطر الحالي.';load()}catch(e){msg.textContent=e.message}}async function dismiss(id){if(!confirm('إغلاق الحالة بدون تنفيذ؟'))return;try{await api('/api/admin/interventions/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'dismissed'})});load()}catch(e){msg.textContent=e.message}}async function load(){try{let [s,c,q]=await Promise.all([api('/api/admin/interventions/summary'),api('/api/admin/interventions?limit=100'),api('/api/admin/intervention-queue?limit=100')]);summary.innerHTML=[['مفتوحة',s.open||0],['مخططة',s.planned||0],['مكتملة',s.done||0],['تحسن بعد التدخل',s.improved||0],['متوسط خفض الخطر',s.average_risk_reduction==null?'—':s.average_risk_reduction]].map(v=>'<div class=card><div class=muted>'+esc(v[0])+'</div><div class=big>'+esc(v[1])+'</div></div>').join('');cases.innerHTML=(c.items||[]).map(v=>'<tr><td><b>'+esc(v.student_name)+'</b></td><td>'+esc(labels[v.intervention_type]||v.intervention_type)+'</td><td>'+esc(v.status)+'</td><td>'+esc(v.pre_risk_score??'—')+'</td><td>'+esc(v.post_risk_score??'—')+'</td><td>'+esc(v.outcome_note||v.note||'—')+'</td><td>'+(v.status==='open'||v.status==='planned'?'<button class=primary onclick="finish('+v.id+')">تم التنفيذ</button> <button onclick="dismiss('+v.id+')">إغلاق</button>':'—')+'</td></tr>').join('')||'<tr><td colspan=7 class=muted>لا توجد حالات تدخل مسجلة.</td></tr>';let active=new Set((c.items||[]).filter(v=>v.status==='open'||v.status==='planned').map(v=>Number(v.student_id)));queue.innerHTML=(q.items||[]).map(v=>'<tr><td><b>'+esc(v.student_name)+'</b></td><td class="'+(v.priority==='high'?'bad':'warn')+'">'+esc(v.priority)+' · '+v.score+'/100</td><td>'+v.reasons.map(esc).join('<br>')+'</td><td>'+esc(labels[v.next_action]||v.next_action)+'</td><td>'+(active.has(Number(v.student_id))?'<span class=good>حالة مفتوحة</span>':'<button onclick="openCase('+v.student_id+',\''+esc(v.next_action)+'\')">فتح تدخل</button>')+'</td></tr>').join('')}catch(e){msg.textContent=e.message}}
load();</script></main></html>'''


@app.get("/admin/interventions", response_class=HTMLResponse)
def intervention_cases_page():
    return PAGE
