from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .main import app
from .db import connect
from .security import require_admin

WA_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WA_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "").strip()
WA_RESULT_TEMPLATE = os.getenv("WHATSAPP_RESULT_TEMPLATE", "").strip()
WA_LOW_SCORE_TEMPLATE = os.getenv("WHATSAPP_LOW_SCORE_TEMPLATE", "").strip()
WA_WEEKLY_TEMPLATE = os.getenv("WHATSAPP_WEEKLY_TEMPLATE", "").strip()
WA_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "ar").strip() or "ar"
LOW_SCORE_THRESHOLD = float(os.getenv("LOW_SCORE_THRESHOLD", "50") or 50)

class GuardianCreate(BaseModel):
    student_id: int
    name: str
    whatsapp_phone: str
    relationship: str | None = None
    whatsapp_opt_in: bool = False

class GuardianPatch(BaseModel):
    name: str | None = None
    whatsapp_phone: str | None = None
    relationship: str | None = None
    whatsapp_opt_in: bool | None = None
    active: bool | None = None

def wa_configured() -> bool:
    return bool(WA_TOKEN and WA_PHONE_ID and WA_GRAPH_VERSION)

def normalize_phone(v: str) -> str:
    return "".join(ch for ch in v if ch.isdigit())

def template_for(kind: str) -> str:
    return {
        "test_result": WA_RESULT_TEMPLATE,
        "low_score_alert": WA_LOW_SCORE_TEMPLATE,
        "weekly_summary": WA_WEEKLY_TEMPLATE,
    }.get(kind, "")

@app.get("/api/whatsapp/status", dependencies=[Depends(require_admin)])
def whatsapp_status():
    return {
        "configured": wa_configured(),
        "phone_number_id_configured": bool(WA_PHONE_ID),
        "access_token_configured": bool(WA_TOKEN),
        "graph_version_configured": bool(WA_GRAPH_VERSION),
        "templates": {
            "test_result": bool(WA_RESULT_TEMPLATE),
            "low_score_alert": bool(WA_LOW_SCORE_TEMPLATE),
            "weekly_summary": bool(WA_WEEKLY_TEMPLATE),
        },
        "template_language": WA_TEMPLATE_LANG,
        "low_score_threshold": LOW_SCORE_THRESHOLD,
    }

@app.get("/api/students", dependencies=[Depends(require_admin)])
def list_students():
    with connect() as con:
        return list(con.execute("SELECT id,name,email,phone,external_code,created_at FROM students ORDER BY name,id").fetchall())

@app.get("/api/guardians", dependencies=[Depends(require_admin)])
def list_guardians(student_id: int | None = None):
    sql = """SELECT g.*,s.name student_name FROM guardians g
             JOIN students s ON s.id=g.student_id WHERE 1=1"""
    params = []
    if student_id is not None:
        sql += " AND g.student_id=%s"; params.append(student_id)
    sql += " ORDER BY s.name,g.id"
    with connect() as con:
        return list(con.execute(sql, params).fetchall())

@app.post("/api/guardians", dependencies=[Depends(require_admin)])
def create_guardian(p: GuardianCreate):
    phone = normalize_phone(p.whatsapp_phone)
    if len(phone) < 8:
        raise HTTPException(400, "رقم واتساب غير صالح")
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s", (p.student_id,)).fetchone():
            raise HTTPException(404, "Student not found")
        row = con.execute(
            """INSERT INTO guardians(student_id,name,whatsapp_phone,relationship,whatsapp_opt_in,opt_in_at)
               VALUES (%s,%s,%s,%s,%s,CASE WHEN %s THEN now() ELSE NULL END)
               ON CONFLICT(student_id,whatsapp_phone) DO UPDATE SET
                 name=excluded.name,relationship=excluded.relationship,
                 whatsapp_opt_in=excluded.whatsapp_opt_in,
                 opt_in_at=CASE WHEN excluded.whatsapp_opt_in THEN coalesce(guardians.opt_in_at,now()) ELSE NULL END,
                 active=TRUE
               RETURNING *""",
            (p.student_id,p.name.strip(),phone,p.relationship,p.whatsapp_opt_in,p.whatsapp_opt_in)
        ).fetchone()
        return row

@app.patch("/api/guardians/{guardian_id}", dependencies=[Depends(require_admin)])
def patch_guardian(guardian_id: int, p: GuardianPatch):
    values = p.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, "No changes")
    if "whatsapp_phone" in values:
        values["whatsapp_phone"] = normalize_phone(values["whatsapp_phone"])
    if "whatsapp_opt_in" in values:
        values["opt_in_at"] = datetime.now(timezone.utc) if values["whatsapp_opt_in"] else None
    with connect() as con:
        row = con.execute(
            f"UPDATE guardians SET {', '.join(f'{k}=%s' for k in values)} WHERE id=%s RETURNING *",
            list(values.values()) + [guardian_id],
        ).fetchone()
        if not row:
            raise HTTPException(404, "Guardian not found")
        return row

def build_attempt_payload(con, attempt_id: int) -> dict:
    a = con.execute(
        """SELECT a.id,a.student_id,a.quiz_id,a.score,a.max_score,a.completed_at,a.submitted_at,
                  s.name student_name,q.title quiz_title
           FROM attempts a JOIN students s ON s.id=a.student_id
           LEFT JOIN quizzes q ON q.id=a.quiz_id
           WHERE a.id=%s""", (attempt_id,)
    ).fetchone()
    if not a:
        raise HTTPException(404, "Attempt not found")
    max_score = float(a["max_score"] or 0)
    score = float(a["score"] or 0)
    pct = round((score / max_score * 100), 1) if max_score else 0.0
    stats = con.execute(
        """SELECT count(*) total,
                  count(*) FILTER(WHERE is_correct=TRUE) correct,
                  count(*) FILTER(WHERE is_correct=FALSE) incorrect
           FROM attempt_answers WHERE attempt_id=%s""", (attempt_id,)
    ).fetchone()
    weak = list(con.execute(
        """SELECT l.title, count(*) wrong
           FROM attempt_answers aa
           JOIN questions q ON q.id=aa.question_id
           LEFT JOIN lessons l ON l.id=q.lesson_id
           WHERE aa.attempt_id=%s AND aa.is_correct=FALSE
           GROUP BY l.id,l.title ORDER BY wrong DESC,l.title NULLS LAST LIMIT 3""", (attempt_id,)
    ).fetchall())
    return {
        "attempt_id": attempt_id,
        "student_id": a["student_id"],
        "student_name": a["student_name"],
        "quiz_title": a["quiz_title"] or f"اختبار #{a['quiz_id']}",
        "score": score,
        "max_score": max_score,
        "percentage": pct,
        "correct": int(stats["correct"] or 0),
        "incorrect": int(stats["incorrect"] or 0),
        "total_answers": int(stats["total"] or 0),
        "weak_lessons": [x["title"] for x in weak if x["title"]],
        "completed_at": str(a["completed_at"] or a["submitted_at"] or ""),
    }

@app.post("/api/attempts/{attempt_id}/queue-parent-notifications", dependencies=[Depends(require_admin)])
def queue_attempt_notifications(attempt_id: int):
    with connect() as con:
        payload = build_attempt_payload(con, attempt_id)
        guardians = list(con.execute(
            """SELECT id FROM guardians
               WHERE student_id=%s AND active=TRUE AND whatsapp_opt_in=TRUE""",
            (payload["student_id"],)
        ).fetchall())
        created = []
        for g in guardians:
            for kind in (["test_result", "low_score_alert"] if payload["percentage"] < LOW_SCORE_THRESHOLD else ["test_result"]):
                row = con.execute(
                    """INSERT INTO parent_notifications(guardian_id,student_id,attempt_id,notification_type,template_name,payload,status)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb,'queued')
                       ON CONFLICT DO NOTHING RETURNING id,notification_type,status""",
                    (g["id"],payload["student_id"],attempt_id,kind,template_for(kind),__import__("json").dumps(payload,ensure_ascii=False))
                ).fetchone()
                if row: created.append(row)
        return {"queued": created, "guardian_count": len(guardians), "payload": payload}

@app.post("/api/parent-notifications/queue-weekly", dependencies=[Depends(require_admin)])
def queue_weekly_summaries():
    import json
    with connect() as con:
        week_key = con.execute("SELECT to_char(date_trunc('week',now()),'YYYY-MM-DD') week_key").fetchone()["week_key"]
        rows = list(con.execute(
            """SELECT s.id student_id,s.name student_name,g.id guardian_id,
                      count(a.id) tests_count,
                      round(avg(CASE WHEN a.max_score>0 THEN (a.score/a.max_score)*100 ELSE NULL END),1) average_percentage
               FROM guardians g JOIN students s ON s.id=g.student_id
               LEFT JOIN attempts a ON a.student_id=s.id
                 AND coalesce(a.completed_at,a.submitted_at)>=now()-interval '7 days'
               WHERE g.active=TRUE AND g.whatsapp_opt_in=TRUE
               GROUP BY s.id,s.name,g.id ORDER BY s.name"""
        ).fetchall())
        created=[]
        skipped_duplicates=0
        for r in rows:
            if con.execute(
                """SELECT 1 FROM parent_notifications
                   WHERE guardian_id=%s AND notification_type='weekly_summary'
                     AND payload->>'week_key'=%s LIMIT 1""",
                (r["guardian_id"],week_key)
            ).fetchone():
                skipped_duplicates += 1
                continue

            lesson_perf=list(con.execute(
                """SELECT l.title,
                          count(*) total,
                          count(*) FILTER(WHERE aa.is_correct=TRUE) correct,
                          count(*) FILTER(WHERE aa.is_correct=FALSE) incorrect,
                          round(100.0*count(*) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(*),0),1) percentage
                   FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
                   JOIN questions q ON q.id=aa.question_id LEFT JOIN lessons l ON l.id=q.lesson_id
                   WHERE a.student_id=%s
                     AND coalesce(a.completed_at,a.submitted_at)>=now()-interval '7 days'
                   GROUP BY l.id,l.title HAVING count(*)>0
                   ORDER BY percentage DESC NULLS LAST, total DESC""",
                (r["student_id"],)
            ).fetchall())
            strongest = lesson_perf[0] if lesson_perf else None
            weakest = lesson_perf[-1] if lesson_perf else None

            previous=con.execute(
                """SELECT round(avg(CASE WHEN max_score>0 THEN (score/max_score)*100 ELSE NULL END),1) average_percentage
                   FROM attempts WHERE student_id=%s
                     AND coalesce(completed_at,submitted_at)>=now()-interval '14 days'
                     AND coalesce(completed_at,submitted_at)<now()-interval '7 days'""",
                (r["student_id"],)
            ).fetchone()
            older=con.execute(
                """SELECT round(avg(CASE WHEN max_score>0 THEN (score/max_score)*100 ELSE NULL END),1) average_percentage
                   FROM attempts WHERE student_id=%s
                     AND coalesce(completed_at,submitted_at)>=now()-interval '21 days'
                     AND coalesce(completed_at,submitted_at)<now()-interval '14 days'""",
                (r["student_id"],)
            ).fetchone()

            current_avg=float(r["average_percentage"] or 0)
            previous_value=float(previous["average_percentage"]) if previous["average_percentage"] is not None else None
            older_value=float(older["average_percentage"]) if older["average_percentage"] is not None else None
            delta=round(current_avg-previous_value,1) if previous_value is not None else None
            trend="تحسن" if delta is not None and delta>=5 else ("تراجع" if delta is not None and delta<=-5 else "مستقر")
            continuous_decline=bool(
                previous_value is not None and older_value is not None
                and current_avg < previous_value < older_value
            )
            needs_attention=continuous_decline or current_avg < LOW_SCORE_THRESHOLD
            alert_text=(
                "تراجع مستمر خلال 3 أسابيع ويحتاج متابعة"
                if continuous_decline else
                ("متوسط الأسبوع أقل من الحد المحدد ويحتاج متابعة" if current_avg < LOW_SCORE_THRESHOLD else "لا يوجد تنبيه")
            )
            strongest_text=(f'{strongest["title"]} ({strongest["percentage"]}%)' if strongest and strongest["title"] else "لا توجد بيانات كافية")
            weakest_text=(f'{weakest["title"]} ({weakest["percentage"]}%)' if weakest and weakest["title"] else "لا توجد بيانات كافية")

            payload={
                "week_key":week_key,
                "student_name":r["student_name"],
                "student_id":r["student_id"],
                "tests_count":int(r["tests_count"] or 0),
                "average_percentage":current_avg,
                "previous_week_average":previous_value,
                "older_week_average":older_value,
                "trend_delta":delta,
                "trend_label":trend,
                "strongest_lesson":strongest["title"] if strongest else None,
                "strongest_lesson_percentage":float(strongest["percentage"]) if strongest and strongest["percentage"] is not None else None,
                "weakest_lesson":weakest["title"] if weakest else None,
                "weakest_lesson_percentage":float(weakest["percentage"]) if weakest and weakest["percentage"] is not None else None,
                "strongest_lesson_text":strongest_text,
                "weakest_lesson_text":weakest_text,
                "weak_lessons":[x["title"] for x in reversed(lesson_perf[-3:]) if x["title"]] if lesson_perf else [],
                "continuous_decline":continuous_decline,
                "needs_attention":needs_attention,
                "alert_text":alert_text
            }
            item=con.execute(
                """INSERT INTO parent_notifications(guardian_id,student_id,notification_type,template_name,payload,status)
                   VALUES (%s,%s,'weekly_summary',%s,%s::jsonb,'queued')
                   RETURNING id,notification_type,status""",
                (r["guardian_id"],r["student_id"],template_for("weekly_summary"),json.dumps(payload,ensure_ascii=False))
            ).fetchone()
            created.append(item)
        return {"queued_count":len(created),"skipped_duplicates":skipped_duplicates,"week_key":week_key,"queued":created}

def template_components(kind: str, payload: dict) -> list:
    weak = "، ".join(payload.get("weak_lessons") or []) or "لا توجد"
    if kind == "low_score_alert":
        vals = [payload["student_name"], payload["quiz_title"], f'{payload["percentage"]}%']
    elif kind == "weekly_summary":
        delta = payload.get("trend_delta")
        comparison = (
            f'{payload.get("trend_label","مستقر")} ({delta:+.1f} نقطة)'
            if isinstance(delta,(int,float)) else "لا توجد مقارنة سابقة"
        )
        vals = [
            payload.get("student_name",""),
            str(payload.get("tests_count",0)),
            f'{payload.get("average_percentage",0)}%',
            comparison,
            payload.get("strongest_lesson_text") or "لا توجد بيانات كافية",
            payload.get("weakest_lesson_text") or "لا توجد بيانات كافية",
            payload.get("alert_text") or "لا يوجد تنبيه",
        ]
    else:
        vals = [
            payload["student_name"], payload["quiz_title"],
            f'{payload["score"]}/{payload["max_score"]}',
            f'{payload["percentage"]}%',
            str(payload["correct"]), str(payload["incorrect"]), weak,
        ]
    return [{"type":"body","parameters":[{"type":"text","text":str(v)} for v in vals]}]

def send_one(notification_id: int) -> dict:
    with connect() as con:
        n = con.execute(
            """SELECT n.*,g.whatsapp_phone,g.whatsapp_opt_in,g.active
               FROM parent_notifications n JOIN guardians g ON g.id=n.guardian_id
               WHERE n.id=%s FOR UPDATE""", (notification_id,)
        ).fetchone()
        if not n: raise HTTPException(404, "Notification not found")
        if n["status"] == "sent": return {"id":notification_id,"status":"sent","already_sent":True}
        if not n["active"] or not n["whatsapp_opt_in"]:
            con.execute("UPDATE parent_notifications SET status='skipped',error_message='guardian_not_opted_in' WHERE id=%s",(notification_id,))
            return {"id":notification_id,"status":"skipped"}
        template = n["template_name"] or template_for(n["notification_type"])
        if not wa_configured() or not template:
            raise HTTPException(503, "WhatsApp Cloud API أو اسم القالب غير مُعد في Environment Variables")
        payload = n["payload"] if isinstance(n["payload"],dict) else {}
        body = {
            "messaging_product":"whatsapp",
            "to":n["whatsapp_phone"],
            "type":"template",
            "template":{
                "name":template,
                "language":{"code":WA_TEMPLATE_LANG},
                "components":template_components(n["notification_type"],payload),
            },
        }
        con.execute("UPDATE parent_notifications SET status='sending',attempts_count=attempts_count+1,error_message=NULL WHERE id=%s",(notification_id,))
    url = f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{WA_PHONE_ID}/messages"
    try:
        with httpx.Client(timeout=20) as client:
            r = client.post(url, headers={"Authorization":f"Bearer {WA_TOKEN}","Content-Type":"application/json"}, json=body)
        data = r.json()
        if r.status_code >= 400:
            raise RuntimeError(str(data))
        mid = ((data.get("messages") or [{}])[0]).get("id")
        with connect() as con:
            con.execute("UPDATE parent_notifications SET status='sent',provider_message_id=%s,sent_at=now() WHERE id=%s",(mid,notification_id))
        return {"id":notification_id,"status":"sent","provider_message_id":mid}
    except Exception as e:
        with connect() as con:
            con.execute("UPDATE parent_notifications SET status='failed',error_message=%s,next_attempt_at=now()+interval '15 minutes' WHERE id=%s",(str(e)[:2000],notification_id))
        raise HTTPException(502, f"WhatsApp send failed: {e}")

@app.post("/api/parent-notifications/{notification_id}/send", dependencies=[Depends(require_admin)])
def send_notification(notification_id: int):
    return send_one(notification_id)

@app.post("/api/parent-notifications/dispatch", dependencies=[Depends(require_admin)])
def dispatch_notifications(limit: int = 20):
    limit = min(max(limit,1),100)
    with connect() as con:
        ids = [r["id"] for r in con.execute(
            """SELECT id FROM parent_notifications
               WHERE status IN ('queued','failed')
                 AND (next_attempt_at IS NULL OR next_attempt_at<=now())
                 AND attempts_count<5
               ORDER BY created_at LIMIT %s""",(limit,)
        ).fetchall()]
    results=[]
    for nid in ids:
        try: results.append(send_one(nid))
        except HTTPException as e: results.append({"id":nid,"status":"failed","detail":e.detail})
    return {"processed":len(results),"results":results}

@app.get("/api/parent-notifications", dependencies=[Depends(require_admin)])
def list_notifications(limit: int = 200):
    with connect() as con:
        return list(con.execute(
            """SELECT n.id,n.notification_type,n.status,n.attempts_count,n.created_at,n.sent_at,n.error_message,n.payload,
                      s.name student_name,g.name guardian_name,g.whatsapp_phone
               FROM parent_notifications n
               JOIN students s ON s.id=n.student_id JOIN guardians g ON g.id=n.guardian_id
               ORDER BY n.id DESC LIMIT %s""",(min(max(limit,1),1000),)
        ).fetchall())

PARENTS = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>أولياء الأمور وواتساب</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:1200px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,select,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}.item{padding:10px;border-bottom:1px solid #eee}.ok{color:#067647}.bad{color:#b42318}.muted{color:#667085;font-size:13px}</style><main>
<h1>أولياء الأمور وإشعارات واتساب</h1><div class="box row"><input id=key type=password placeholder="ADMIN_API_KEY"><button onclick=saveKey()>حفظ المفتاح</button><a href="/admin">لوحة الإدارة</a><span id=msg></span></div>
<div class=box><h3>حالة WhatsApp Cloud API</h3><div id=wa></div></div>
<div class=box><h3>إضافة ولي أمر</h3><div class=row><select id=student></select><input id=gname placeholder="اسم ولي الأمر"><input id=phone placeholder="2010xxxxxxxx"><input id=relation placeholder="صلة القرابة"><label><input id=opt type=checkbox> موافق على رسائل واتساب</label><button onclick=addG()>حفظ</button></div></div>
<div class=box><h3>أولياء الأمور</h3><div id=gs></div></div>
<div class=box><h3>طابور الرسائل</h3><button onclick=weekly()>إنشاء التقارير الأسبوعية</button><button onclick=dispatch()>إرسال الرسائل الجاهزة</button><div id=ns></div></div>
<script>
key.value=localStorage.pk||'';function h(){return {'X-Admin-Key':localStorage.pk||''}}function saveKey(){localStorage.pk=key.value;load()}
async function jf(u,o={}){let r=await fetch(u,o),x=null;try{x=await r.json()}catch(e){}if(!r.ok)throw new Error(typeof x?.detail==='string'?x.detail:JSON.stringify(x?.detail||r.status));return x}
async function load(){try{let [s,g,n,w]=await Promise.all([jf('/api/students',{headers:h()}),jf('/api/guardians',{headers:h()}),jf('/api/parent-notifications',{headers:h()}),jf('/api/whatsapp/status',{headers:h()})]);student.innerHTML=s.map(x=>`<option value="${x.id}">${x.name}</option>`).join('');gs.innerHTML=g.length?g.map(x=>`<div class=item><b>${x.student_name}</b> — ${x.name} — ${x.whatsapp_phone} — ${x.whatsapp_opt_in?'✅ موافق':'⚠️ غير موافق'}</div>`).join(''):'لا يوجد أولياء أمور';ns.innerHTML=n.length?n.map(x=>{let p=x.payload||{},extra=x.notification_type==='weekly_summary'?'<div class=muted>متوسط '+(p.average_percentage??0)+'% · '+(p.trend_label||'—')+' · أقوى: '+(p.strongest_lesson_text||'—')+' · أضعف: '+(p.weakest_lesson_text||'—')+'</div>'+(p.needs_attention?'<div class=bad>⚠️ '+(p.alert_text||'يحتاج متابعة')+'</div>':''):'';return `<div class=item>#${x.id} · ${x.student_name} → ${x.guardian_name} · ${x.notification_type} · <b>${x.status}</b>${extra} ${x.error_message?'<div class=bad>'+x.error_message+'</div>':''}</div>`}).join(''):'لا توجد رسائل';wa.innerHTML=`<b class="${w.configured?'ok':'bad'}">${w.configured?'✅ إعداد الاتصال الأساسي مكتمل':'⚠️ إعداد الاتصال غير مكتمل'}</b><div class=muted>Graph version: ${w.graph_version_configured?'موجود':'غير موجود'} · Phone ID: ${w.phone_number_id_configured?'موجود':'غير موجود'} · Token: ${w.access_token_configured?'موجود':'غير موجود'}</div>`}catch(e){msg.textContent=e.message}}
async function addG(){try{await jf('/api/guardians',{method:'POST',headers:{...h(),'Content-Type':'application/json'},body:JSON.stringify({student_id:Number(student.value),name:gname.value,whatsapp_phone:phone.value,relationship:relation.value||null,whatsapp_opt_in:opt.checked})});msg.textContent='تم الحفظ';load()}catch(e){msg.textContent=e.message}}
async function weekly(){try{let x=await jf('/api/parent-notifications/queue-weekly',{method:'POST',headers:h()});msg.textContent='تم تجهيز '+x.queued_count+' تقرير أسبوعي';load()}catch(e){msg.textContent=e.message}}async function dispatch(){try{let x=await jf('/api/parent-notifications/dispatch',{method:'POST',headers:h()});msg.textContent='تمت معالجة '+x.processed+' رسالة';load()}catch(e){msg.textContent=e.message}}load();
</script></main></html>'''

@app.get("/admin/parents", response_class=HTMLResponse)
def parents_page():
    return PARENTS
