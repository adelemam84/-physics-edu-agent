from __future__ import annotations

import json
import secrets
import string
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import connect
from .main import app
from .security import require_admin
from .student_security import resolve_student_code

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INTEGRITY_EVENTS = {
    "tab_hidden",
    "fullscreen_exit",
    "copy",
    "paste",
    "context_menu",
    "window_blur",
}
DEFAULT_INTEGRITY_POLICY = {
    "mode": "log",
    "max_violations": 3,
    "track_tab_switch": True,
    "track_fullscreen_exit": True,
    "track_copy_paste": True,
    "track_context_menu": False,
    "track_window_blur": False,
}


class ExamSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available_from: datetime | None = None
    available_until: datetime | None = None
    access_code: str | None = Field(default=None, max_length=12)
    integrity_mode: Literal["off", "log", "warn", "auto_submit"] = "log"
    max_violations: int = Field(default=3, ge=1, le=50)
    track_tab_switch: bool = True
    track_fullscreen_exit: bool = True
    track_copy_paste: bool = True
    track_context_menu: bool = False
    track_window_blur: bool = False
    shuffle_questions: bool = False

    @model_validator(mode="after")
    def validate_window(self):
        if self.available_from and self.available_until and self.available_until <= self.available_from:
            raise ValueError("وقت إغلاق الاختبار يجب أن يكون بعد وقت الفتح")
        if self.access_code:
            code = normalize_access_code(self.access_code)
            if len(code) != 6 or any(ch not in CODE_ALPHABET for ch in code):
                raise ValueError("كود الاختبار يجب أن يكون 6 رموز من الحروف/الأرقام المدعومة")
            self.access_code = code
        return self


class IntegrityEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=2, max_length=40)
    detail: str | None = Field(default=None, max_length=500)


class ScoreOverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_score: Decimal = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)


def normalize_access_code(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())


def exam_delivery_state(row, now: datetime | None = None) -> str:
    if not row:
        return "missing"
    if not bool(row.get("published")) or row.get("lifecycle_status") != "published":
        return "unpublished"
    current = now
    if current is None:
        current = row.get("db_now")
    start = row.get("available_from")
    end = row.get("available_until")
    if current is not None and start is not None and current < start:
        return "scheduled"
    if current is not None and end is not None and current >= end:
        return "closed"
    return "open"


def ensure_exam_open(row) -> None:
    state = exam_delivery_state(row)
    if state == "scheduled":
        raise HTTPException(409, {"message": "الاختبار لم يفتح بعد", "available_from": row.get("available_from")})
    if state == "closed":
        raise HTTPException(409, {"message": "انتهت نافذة إتاحة الاختبار", "available_until": row.get("available_until")})
    if state != "open":
        raise HTTPException(404, "الاختبار غير متاح")




def ensure_attempt_question_order(con, attempt_id: int, quiz_id: int, shuffle: bool) -> list[int]:
    existing = list(con.execute(
        "SELECT question_id,position FROM attempt_question_order WHERE attempt_id=%s ORDER BY position",
        (attempt_id,),
    ).fetchall())
    if not existing:
        seed = f"{attempt_id}:{quiz_id}"
        con.execute(
            """INSERT INTO attempt_question_order(attempt_id,question_id,position)
              SELECT %s,qq.question_id,
                     row_number() OVER(
                       ORDER BY CASE WHEN %s
                         THEN md5(%s || ':' || qq.question_id::text)
                         ELSE lpad(qq.position::text,12,'0')
                       END
                     )
              FROM quiz_questions qq WHERE qq.quiz_id=%s
              ON CONFLICT (attempt_id,question_id) DO NOTHING""",
            (attempt_id, bool(shuffle), seed, quiz_id),
        )
        existing = list(con.execute(
            "SELECT question_id,position FROM attempt_question_order WHERE attempt_id=%s ORDER BY position",
            (attempt_id,),
        ).fetchall())
    return [int(r["question_id"]) for r in existing]


def _new_access_code(con) -> str:
    for _ in range(30):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if not con.execute("SELECT 1 FROM quizzes WHERE upper(access_code)=upper(%s)", (code,)).fetchone():
            return code
    raise HTTPException(503, "تعذر إنشاء كود فريد للاختبار، حاول مرة أخرى")


def _policy_from_payload(p: ExamSettingsIn) -> dict:
    return {
        "mode": p.integrity_mode,
        "max_violations": p.max_violations,
        "track_tab_switch": p.track_tab_switch,
        "track_fullscreen_exit": p.track_fullscreen_exit,
        "track_copy_paste": p.track_copy_paste,
        "track_context_menu": p.track_context_menu,
        "track_window_blur": p.track_window_blur,
    }


def _quiz_settings(con, quiz_id: int):
    return con.execute(
        """SELECT id,title,published,lifecycle_status,access_code,available_from,available_until,
          integrity_policy,shuffle_questions,now() db_now
          FROM quizzes WHERE id=%s""",
        (quiz_id,),
    ).fetchone()


@app.get("/api/admin/exams/{quiz_id}/settings", dependencies=[Depends(require_admin)])
def read_exam_settings(quiz_id: int):
    with connect() as con:
        row = _quiz_settings(con, quiz_id)
        if not row:
            raise HTTPException(404, "Quiz not found")
        return {**row, "delivery_state": exam_delivery_state(row)}


@app.patch("/api/admin/exams/{quiz_id}/settings", dependencies=[Depends(require_admin)])
def update_exam_settings(quiz_id: int, payload: ExamSettingsIn):
    with connect() as con:
        old = _quiz_settings(con, quiz_id)
        if not old:
            raise HTTPException(404, "Quiz not found")
        code = payload.access_code or old.get("access_code") or _new_access_code(con)
        policy = _policy_from_payload(payload)
        row = con.execute(
            """UPDATE quizzes
              SET access_code=%s, available_from=%s, available_until=%s, integrity_policy=%s::jsonb,
                  shuffle_questions=%s
              WHERE id=%s
              RETURNING id,title,published,lifecycle_status,access_code,available_from,available_until,integrity_policy,shuffle_questions""",
            (code, payload.available_from, payload.available_until, json.dumps(policy), payload.shuffle_questions, quiz_id),
        ).fetchone()
        con.execute(
            """INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,details)
              VALUES(%s,'exam_settings_update',%s,%s,%s::jsonb)""",
            (
                quiz_id,
                old["lifecycle_status"],
                old["lifecycle_status"],
                json.dumps({
                    "available_from": payload.available_from.isoformat() if payload.available_from else None,
                    "available_until": payload.available_until.isoformat() if payload.available_until else None,
                    "integrity_policy": policy,
                    "access_code_rotated": code != old.get("access_code"),
                    "shuffle_questions": payload.shuffle_questions,
                }),
            ),
        )
        state_row = {**row, "db_now": con.execute("SELECT now() v").fetchone()["v"]}
        return {**row, "delivery_state": exam_delivery_state(state_row)}


@app.post("/api/admin/exams/{quiz_id}/rotate-code", dependencies=[Depends(require_admin)])
def rotate_exam_code(quiz_id: int):
    with connect() as con:
        old = _quiz_settings(con, quiz_id)
        if not old:
            raise HTTPException(404, "Quiz not found")
        code = _new_access_code(con)
        con.execute("UPDATE quizzes SET access_code=%s WHERE id=%s", (code, quiz_id))
        con.execute(
            """INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,details)
              VALUES(%s,'exam_access_code_rotate',%s,%s,'{"personal_platform":true}'::jsonb)""",
            (quiz_id, old["lifecycle_status"], old["lifecycle_status"]),
        )
        return {"quiz_id": quiz_id, "access_code": code}


@app.get("/api/student/exams/resolve/{access_code}")
def resolve_exam_code(access_code: str, request: Request):
    student_code = resolve_student_code(request)
    code = normalize_access_code(access_code)
    if len(code) != 6:
        raise HTTPException(404, "كود الاختبار غير صحيح")
    with connect() as con:
        student = con.execute("SELECT id FROM students WHERE external_code=%s", (student_code,)).fetchone()
        if not student:
            raise HTTPException(404, "كود الطالب غير صحيح")
        row = con.execute(
            """SELECT id,title,published,lifecycle_status,access_code,available_from,available_until,
              integrity_policy,shuffle_questions,now() db_now
              FROM quizzes
              WHERE upper(access_code)=upper(%s)
                AND (owner_student_id IS NULL OR owner_student_id=%s)""",
            (code, student["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "كود الاختبار غير صحيح")
        ensure_exam_open(row)
        return {
            "quiz_id": row["id"],
            "title": row["title"],
            "student_path": f"/student/quiz/{row['id']}",
            "delivery_state": "open",
        }


@app.post("/api/student/attempts/{attempt_id}/integrity-event")
def record_integrity_event(attempt_id: int, payload: IntegrityEventIn, request: Request):
    code = resolve_student_code(request)
    event_type = payload.event_type.strip().lower()
    if event_type not in INTEGRITY_EVENTS:
        raise HTTPException(400, "نوع حدث النزاهة غير مدعوم")
    with connect() as con:
        row = con.execute(
            """SELECT a.id,a.completed_at,s.external_code,q.integrity_policy
              FROM attempts a
              JOIN students s ON s.id=a.student_id
              JOIN quizzes q ON q.id=a.quiz_id
              WHERE a.id=%s""",
            (attempt_id,),
        ).fetchone()
        if not row or row["external_code"] != code:
            raise HTTPException(404, "المحاولة غير موجودة")
        if row["completed_at"] is not None:
            raise HTTPException(409, "تم تسليم هذه المحاولة بالفعل")
        policy = dict(row.get("integrity_policy") or DEFAULT_INTEGRITY_POLICY)
        mode = str(policy.get("mode") or "log")
        if mode == "off":
            return {"recorded": False, "mode": "off", "violations": 0, "action": "none"}
        con.execute(
            """INSERT INTO exam_integrity_events(attempt_id,event_type,detail)
              VALUES(%s,%s,%s)""",
            (attempt_id, event_type, payload.detail),
        )
        count = int(con.execute(
            "SELECT count(*) n FROM exam_integrity_events WHERE attempt_id=%s",
            (attempt_id,),
        ).fetchone()["n"])
        threshold = max(1, int(policy.get("max_violations") or 3))
        action = "none"
        if mode == "warn":
            action = "warn"
        elif mode == "auto_submit" and count >= threshold:
            action = "auto_submit"
        return {
            "recorded": True,
            "mode": mode,
            "violations": count,
            "threshold": threshold,
            "action": action,
        }




@app.patch("/api/admin/attempts/{attempt_id}/score", dependencies=[Depends(require_admin)])
def override_attempt_score(attempt_id: int, payload: ScoreOverrideIn):
    with connect() as con:
        row = con.execute(
            """SELECT a.id,a.score,a.max_score,a.completed_at,a.quiz_id,s.name student_name,q.title quiz_title
              FROM attempts a
              JOIN students s ON s.id=a.student_id
              JOIN quizzes q ON q.id=a.quiz_id
              WHERE a.id=%s""",
            (attempt_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "المحاولة غير موجودة")
        if row["completed_at"] is None:
            raise HTTPException(409, "لا يمكن تعديل درجة محاولة لم يتم تسليمها")
        if payload.new_score > Decimal(str(row["max_score"] or 0)):
            raise HTTPException(400, "الدرجة الجديدة لا يمكن أن تتجاوز الدرجة النهائية")
        previous = Decimal(str(row["score"] or 0))
        reason = payload.reason.strip()
        con.execute(
            """INSERT INTO attempt_score_overrides(attempt_id,previous_score,new_score,reason,actor)
              VALUES(%s,%s,%s,%s,'admin')""",
            (attempt_id, previous, payload.new_score, reason),
        )
        con.execute(
            "UPDATE attempts SET score=%s WHERE id=%s",
            (payload.new_score, attempt_id),
        )
        max_score = Decimal(str(row["max_score"] or 0))
        percentage = round(float(payload.new_score / max_score * 100), 2) if max_score else 0.0
        return {
            "attempt_id": attempt_id,
            "quiz_id": row["quiz_id"],
            "student_name": row["student_name"],
            "quiz_title": row["quiz_title"],
            "previous_score": float(previous),
            "new_score": float(payload.new_score),
            "max_score": float(max_score),
            "percentage": percentage,
            "reason": reason,
        }


@app.get("/api/admin/attempts/{attempt_id}/score-history", dependencies=[Depends(require_admin)])
def attempt_score_history(attempt_id: int):
    with connect() as con:
        if not con.execute("SELECT 1 FROM attempts WHERE id=%s", (attempt_id,)).fetchone():
            raise HTTPException(404, "المحاولة غير موجودة")
        rows = list(con.execute(
            """SELECT id,previous_score,new_score,reason,actor,created_at
              FROM attempt_score_overrides
              WHERE attempt_id=%s
              ORDER BY created_at DESC,id DESC""",
            (attempt_id,),
        ).fetchall())
        return {"attempt_id": attempt_id, "history": rows}


@app.get("/api/admin/exams/{quiz_id}/integrity", dependencies=[Depends(require_admin)])
def exam_integrity_summary(quiz_id: int):
    with connect() as con:
        if not con.execute("SELECT 1 FROM quizzes WHERE id=%s", (quiz_id,)).fetchone():
            raise HTTPException(404, "Quiz not found")
        totals = con.execute(
            """SELECT count(e.id) events,count(DISTINCT e.attempt_id) attempts
              FROM exam_integrity_events e
              JOIN attempts a ON a.id=e.attempt_id
              WHERE a.quiz_id=%s""",
            (quiz_id,),
        ).fetchone()
        by_type = list(con.execute(
            """SELECT e.event_type,count(*) n
              FROM exam_integrity_events e
              JOIN attempts a ON a.id=e.attempt_id
              WHERE a.quiz_id=%s
              GROUP BY e.event_type ORDER BY n DESC,e.event_type""",
            (quiz_id,),
        ).fetchall())
        attempts = list(con.execute(
            """SELECT a.id attempt_id,s.name student_name,count(e.id) violations,max(e.created_at) last_event
              FROM attempts a JOIN students s ON s.id=a.student_id
              LEFT JOIN exam_integrity_events e ON e.attempt_id=a.id
              WHERE a.quiz_id=%s
              GROUP BY a.id,s.name
              HAVING count(e.id)>0
              ORDER BY violations DESC,last_event DESC LIMIT 100""",
            (quiz_id,),
        ).fetchall())
        return {
            "quiz_id": quiz_id,
            "events": int(totals["events"] or 0),
            "attempts_with_events": int(totals["attempts"] or 0),
            "by_type": {r["event_type"]: int(r["n"]) for r in by_type},
            "attempts": attempts,
        }


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>إعدادات تشغيل الامتحان</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:980px;margin:auto;padding:16px}
.box{background:#fff;border:1px solid #e4e7ec;border-radius:16px;padding:16px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
label{display:block;font-size:13px;color:#667085;margin-bottom:5px}input,select,button{width:100%;padding:10px;border:1px solid #cbd2df;border-radius:10px;font:inherit}
button{cursor:pointer;background:#fff}.primary{background:#2447a8;color:#fff;border-color:#2447a8}.code{font-size:28px;font-weight:900;letter-spacing:4px}.muted{color:#667085}.ok{color:#067647}.bad{color:#b42318}
.check{display:flex;gap:8px;align-items:center}.check input{width:auto}</style><main>
<div class=box><a href="/admin/quizzes">دورة حياة الاختبارات</a> · <a href="/admin/quiz-builder">منشئ الاختبارات</a></div>
<div class=box><h1>إعدادات تشغيل الامتحان</h1><p class=muted>منصة شخصية: لا توجد خطط مدفوعة أو أرصدة أو قيود تجارية.</p>
<label>رقم الاختبار</label><input id=qid type=number min=1 placeholder="مثال: 12"><button onclick=loadExam()>تحميل</button></div>
<div id=panel style="display:none">
<div class=box><h2>الدخول والجدولة</h2><div class=grid>
<div><label>كود الدخول</label><div id=code class=code>------</div><button onclick=rotateCode()>إنشاء / تغيير الكود</button></div>
<div><label>فتح الاختبار</label><input id=from type=datetime-local></div>
<div><label>غلق الاختبار</label><input id=until type=datetime-local></div>
</div><p>الحالة: <b id=state></b></p></div>
<div class=box><h2>سياسة النزاهة</h2><div class=grid>
<div><label>التصرف</label><select id=mode><option value=off>إيقاف التتبع</option><option value=log>تسجيل فقط</option><option value=warn>تسجيل + تحذير</option><option value=auto_submit>تسليم تلقائي بعد الحد</option></select></div>
<div><label>حد المخالفات</label><input id=maxv type=number min=1 max=50 value=3></div></div>
<p class=check><input id=tab type=checkbox checked>تسجيل الانتقال لتبويب/تطبيق آخر</p>
<p class=check><input id=fs type=checkbox checked>تسجيل الخروج من ملء الشاشة</p>
<p class=check><input id=cp type=checkbox checked>تسجيل النسخ واللصق</p>
<p class=check><input id=ctx type=checkbox>تسجيل القائمة السياقية</p>
<p class=check><input id=blurTrack type=checkbox>تسجيل فقدان تركيز النافذة</p>
<p class=check><input id=shuffle type=checkbox>ترتيب مختلف للأسئلة لكل محاولة</p>
<button class=primary onclick=save()>حفظ الإعدادات</button><p id=msg class=muted></p></div>
<div class=box><h2>ملخص النزاهة</h2><button onclick=loadIntegrity()>تحديث الملخص</button><div id=integrity class=muted></div></div>
</div>
<script>
const blurTrack=document.getElementById('blurTrack');let id=null;function isoLocal(v){if(!v)return '';let d=new Date(v),p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes())}
async function loadExam(){id=Number(qid.value);if(!id)return;let r=await fetch('/api/admin/exams/'+id+'/settings'),x=await r.json().catch(()=>null);if(!r.ok){alert(x?.detail||'تعذر التحميل');return}panel.style.display='block';code.textContent=x.access_code||'------';from.value=isoLocal(x.available_from);until.value=isoLocal(x.available_until);state.textContent=x.delivery_state;let p=x.integrity_policy||{};mode.value=p.mode||'log';maxv.value=p.max_violations||3;tab.checked=p.track_tab_switch!==false;fs.checked=p.track_fullscreen_exit!==false;cp.checked=p.track_copy_paste!==false;ctx.checked=!!p.track_context_menu;blurTrack.checked=!!p.track_window_blur;shuffle.checked=!!x.shuffle_questions;loadIntegrity()}
async function rotateCode(){let r=await fetch('/api/admin/exams/'+id+'/rotate-code',{method:'POST'}),x=await r.json().catch(()=>null);if(r.ok)code.textContent=x.access_code;else alert(x?.detail||'تعذر إنشاء الكود')}
async function save(){let body={available_from:from.value?new Date(from.value).toISOString():null,available_until:until.value?new Date(until.value).toISOString():null,access_code:code.textContent==='------'?null:code.textContent,integrity_mode:mode.value,max_violations:Number(maxv.value||3),track_tab_switch:tab.checked,track_fullscreen_exit:fs.checked,track_copy_paste:cp.checked,track_context_menu:ctx.checked,track_window_blur:blurTrack.checked,shuffle_questions:shuffle.checked};let r=await fetch('/api/admin/exams/'+id+'/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),x=await r.json().catch(()=>null);msg.textContent=r.ok?'تم الحفظ':(x?.detail?.[0]?.msg||x?.detail||'تعذر الحفظ');if(r.ok){code.textContent=x.access_code;state.textContent=x.delivery_state}}
async function loadIntegrity(){let r=await fetch('/api/admin/exams/'+id+'/integrity'),x=await r.json().catch(()=>null);if(!r.ok){integrity.textContent='تعذر تحميل الملخص';return}integrity.innerHTML='<p><b>'+x.events+'</b> حدثًا في <b>'+x.attempts_with_events+'</b> محاولة</p><pre>'+JSON.stringify(x.by_type,null,2)+'</pre>'}
</script></main></html>'''


@app.get("/admin/exam-engine", response_class=HTMLResponse)
def exam_engine_page():
    return PAGE


STUDENT_CODE_PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>دخول الامتحان بالكود</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:620px;margin:auto;padding:24px}
.box{background:#fff;border:1px solid #e4e7ec;border-radius:18px;padding:20px;box-shadow:0 3px 14px #1018280a}
input,button{width:100%;padding:13px;border:1px solid #cbd2df;border-radius:11px;font:inherit;margin-top:10px}
input{text-transform:uppercase;letter-spacing:4px;text-align:center;font-size:24px;font-weight:800}
button{background:#2447a8;color:#fff;border-color:#2447a8;font-weight:800;cursor:pointer}.muted{color:#667085}.bad{color:#b42318}a{color:#2447a8;text-decoration:none}
</style><main><div class=box><a href="/student">← بوابة الطالب</a><h1>دخول الامتحان بالكود</h1>
<p class=muted>أدخل كود الامتحان المكوّن من 6 رموز. يجب أن تكون مسجلًا بكود الطالب أولًا.</p>
<input id=code maxlength=6 autocomplete=one-time-code placeholder="ABC234">
<button onclick=go()>فتح الامتحان</button><p id=msg class=muted aria-live=polite></p></div>
<script>
function err(x){return typeof x?.detail==='string'?x.detail:(x?.detail?.message||'تعذر فتح الامتحان')}
async function go(){let v=code.value.trim().toUpperCase();if(v.length!==6){msg.className='bad';msg.textContent='أدخل كودًا صحيحًا من 6 رموز';return}
let r=await fetch('/api/student/exams/resolve/'+encodeURIComponent(v),{cache:'no-store'}),x=await r.json().catch(()=>null);
if(!r.ok){msg.className='bad';msg.textContent=err(x);return}location.href=x.student_path}
code.addEventListener('keydown',e=>{if(e.key==='Enter')go()})
</script></main></html>'''


@app.get("/student/exam-code", response_class=HTMLResponse)
def student_exam_code_page():
    return STUDENT_CODE_PAGE
