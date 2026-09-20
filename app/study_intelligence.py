from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .student_security import resolve_student_code


def _status(recent: float | None, previous: float | None, recent_n: int, previous_n: int) -> tuple[str, float | None]:
    delta = None if recent is None or previous is None else round(recent - previous, 1)
    if recent_n < 2:
        return "insufficient_data", delta
    if recent is not None and recent >= 80:
        if previous is not None and previous < 80:
            return "recovered", delta
        return "strong", delta
    if recent is not None and recent < 60:
        if previous is not None and delta is not None and delta <= -10:
            return "worsening", delta
        return "persistent_weakness", delta
    if recent is not None and 60 <= recent < 80:
        if previous is not None and delta is not None and delta >= 10:
            return "improving", delta
        if previous is not None and delta is not None and delta <= -10:
            return "worsening", delta
        return "developing", delta
    return "insufficient_data", delta


def _trend_rows(con, student_id: int, dimension: str):
    if dimension == "concept":
        join = "JOIN question_concepts qd ON qd.question_id=aa.question_id JOIN concepts d ON d.id=qd.concept_id"
        key = "d.id"
        title = "d.title"
        extra = "LEFT JOIN lessons l ON l.id=d.lesson_id"
        lesson_id = "min(l.id)"
        lesson_title = "min(l.title)"
    elif dimension == "skill":
        join = "JOIN question_skills qd ON qd.question_id=aa.question_id JOIN skills d ON d.id=qd.skill_id"
        key = "d.id"
        title = "d.name_ar"
        extra = "LEFT JOIN questions q0 ON q0.id=aa.question_id LEFT JOIN lessons l ON l.id=q0.lesson_id"
        lesson_id = "min(l.id)"
        lesson_title = "min(l.title)"
    else:
        raise ValueError("unsupported dimension")
    sql = f"""WITH ranked_attempts AS (
      SELECT a.id,
        row_number() OVER(ORDER BY a.completed_at DESC,a.id DESC) rn
      FROM attempts a
      WHERE a.student_id=%s AND a.completed_at IS NOT NULL
    )
    SELECT {key} item_id,{title} item_title,{lesson_id} lesson_id,{lesson_title} lesson_title,
      count(aa.id) FILTER(WHERE ra.rn<=5) recent_n,
      count(aa.id) FILTER(WHERE ra.rn<=5 AND aa.is_correct=TRUE) recent_ok,
      count(aa.id) FILTER(WHERE ra.rn BETWEEN 6 AND 10) previous_n,
      count(aa.id) FILTER(WHERE ra.rn BETWEEN 6 AND 10 AND aa.is_correct=TRUE) previous_ok,
      max(a.completed_at) FILTER(WHERE aa.is_correct=FALSE) last_wrong_at
    FROM ranked_attempts ra
    JOIN attempts a ON a.id=ra.id
    JOIN attempt_answers aa ON aa.attempt_id=a.id
    {join}
    {extra}
    WHERE ra.rn<=10
    GROUP BY {key},{title}
    HAVING count(aa.id)>0
    ORDER BY recent_n DESC,item_title"""
    rows = list(con.execute(sql, (student_id,)).fetchall())
    out = []
    for row in rows:
        x = dict(row)
        rn = int(x["recent_n"] or 0)
        ro = int(x["recent_ok"] or 0)
        pn = int(x["previous_n"] or 0)
        po = int(x["previous_ok"] or 0)
        recent = round(100.0 * ro / rn, 1) if rn else None
        previous = round(100.0 * po / pn, 1) if pn else None
        status, delta = _status(recent, previous, rn, pn)
        x.update({
            "recent_mastery": recent,
            "previous_mastery": previous,
            "delta": delta,
            "status": status,
            "dimension": dimension,
        })
        out.append(x)
    rank = {
        "worsening": 0,
        "persistent_weakness": 1,
        "developing": 2,
        "improving": 3,
        "recovered": 4,
        "strong": 5,
        "insufficient_data": 6,
    }
    return sorted(out, key=lambda x: (rank.get(x["status"], 9), x["recent_mastery"] if x["recent_mastery"] is not None else 999, -int(x["recent_n"] or 0)))


def build_weakness_progression(student_id: int):
    with connect() as con:
        student = con.execute("SELECT id,name FROM students WHERE id=%s", (student_id,)).fetchone()
        if not student:
            raise HTTPException(404, "Student not found")
        concepts = _trend_rows(con, student_id, "concept")
        skills = _trend_rows(con, student_id, "skill")
        attempts = int(con.execute(
            "SELECT count(*) n FROM attempts WHERE student_id=%s AND completed_at IS NOT NULL",
            (student_id,),
        ).fetchone()["n"] or 0)
    focus_status = {"worsening", "persistent_weakness", "developing"}
    return {
        "student": student,
        "window": {"recent_attempts": min(attempts, 5), "previous_attempts": min(max(attempts - 5, 0), 5)},
        "concepts": concepts,
        "skills": skills,
        "summary": {
            "concepts_needing_attention": sum(1 for x in concepts if x["status"] in focus_status),
            "skills_needing_attention": sum(1 for x in skills if x["status"] in focus_status),
            "worsening_items": sum(1 for x in concepts + skills if x["status"] == "worsening"),
            "recovered_items": sum(1 for x in concepts + skills if x["status"] == "recovered"),
        },
        "policy": {
            "comparison": "latest_5_completed_attempts_vs_previous_5",
            "analysis": "deterministic",
            "minimum_recent_responses": 2,
            "no_ai_auto_classification": True,
        },
    }


def _lesson_source(con, lesson_id: int | None):
    if not lesson_id:
        return None
    return con.execute(
        """SELECT lsm.document_id,lsm.start_page,lsm.end_page,d.filename,d.source_kind
          FROM lesson_source_mappings lsm
          JOIN documents d ON d.id=lsm.document_id
          WHERE lsm.lesson_id=%s AND lsm.approved=TRUE
            AND d.source_kind IN ('lesson','explanation','textbook','notes')
          ORDER BY lsm.id DESC LIMIT 1""",
        (lesson_id,),
    ).fetchone()


def build_personal_study_queue(student_id: int, limit: int = 10):
    limit = max(1, min(limit, 20))
    progression = build_weakness_progression(student_id)
    candidates = []
    weights = {
        "worsening": 100,
        "persistent_weakness": 85,
        "developing": 65,
        "improving": 45,
        "insufficient_data": 30,
        "recovered": 10,
        "strong": 0,
    }
    for item in progression["concepts"] + progression["skills"]:
        status = item["status"]
        if status in {"strong", "recovered"}:
            continue
        recent = item["recent_mastery"]
        base = weights.get(status, 20)
        severity = 0 if recent is None else max(0, 80 - float(recent))
        evidence = min(int(item["recent_n"] or 0) * 2, 10)
        candidates.append({**item, "priority_score": round(base + severity + evidence, 1)})
    candidates.sort(key=lambda x: (-x["priority_score"], x["dimension"], x["item_title"]))

    with connect() as con:
        queue = []
        seen_lessons = set()
        for item in candidates:
            if len(queue) >= limit:
                break
            lesson_id = item.get("lesson_id")
            source = _lesson_source(con, lesson_id)
            action = "adaptive_practice"
            action_url = "/api/student/adaptive-practice/create?count=10"
            if lesson_id and lesson_id not in seen_lessons and source:
                task_type = "study_then_practice"
                seen_lessons.add(lesson_id)
            else:
                task_type = "practice"
            queue.append({
                "priority": len(queue) + 1,
                "priority_score": item["priority_score"],
                "type": task_type,
                "dimension": item["dimension"],
                "item_id": item["item_id"],
                "title": item["item_title"],
                "lesson_id": lesson_id,
                "lesson_title": item.get("lesson_title"),
                "status": item["status"],
                "recent_mastery": item["recent_mastery"],
                "previous_mastery": item["previous_mastery"],
                "delta": item["delta"],
                "recent_responses": int(item["recent_n"] or 0),
                "reason": (
                    "الأداء يتراجع في آخر المحاولات."
                    if item["status"] == "worsening"
                    else "نقطة ضعف متكررة لم تُغلق بعد."
                    if item["status"] == "persistent_weakness"
                    else "المستوى قيد التطور ويحتاج تثبيتًا."
                    if item["status"] == "developing"
                    else "هناك تحسن، ويُنصح بدورة تثبيت قصيرة."
                    if item["status"] == "improving"
                    else "نحتاج أدلة أداء إضافية."
                ),
                "source": dict(source) if source else None,
                "action": action,
                "action_url": action_url,
            })
    return {
        "student": progression["student"],
        "queue": queue,
        "summary": {
            "tasks": len(queue),
            "study_tasks_with_approved_source": sum(1 for x in queue if x["source"]),
            "worsening_first": True,
        },
        "progression_summary": progression["summary"],
        "policy": {
            "source_explanations": "approved_explanatory_pdf_only",
            "practice_questions": "approved_source_questions_only",
            "ranking": "deterministic_priority_score",
            "commercial_features": False,
        },
    }


@app.get("/api/student/weakness-progression")
def student_weakness_progression(request: Request):
    code = resolve_student_code(request)
    with connect() as con:
        student = con.execute("SELECT id FROM students WHERE external_code=%s", (code,)).fetchone()
    if not student:
        raise HTTPException(404, "كود الطالب غير صحيح")
    return build_weakness_progression(student["id"])


@app.get("/api/admin/students/{student_id}/weakness-progression", dependencies=[Depends(require_admin)])
def admin_weakness_progression(student_id: int):
    return build_weakness_progression(student_id)


@app.get("/api/student/study-queue")
def student_study_queue(request: Request, limit: int = 10):
    code = resolve_student_code(request)
    with connect() as con:
        student = con.execute("SELECT id FROM students WHERE external_code=%s", (code,)).fetchone()
    if not student:
        raise HTTPException(404, "كود الطالب غير صحيح")
    return build_personal_study_queue(student["id"], limit)


@app.get("/api/admin/students/{student_id}/study-queue", dependencies=[Depends(require_admin)])
def admin_study_queue(student_id: int, limit: int = 10):
    return build_personal_study_queue(student_id, limit)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>قائمة المذاكرة الشخصية</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1000px;margin:auto;padding:16px}.box{background:#fff;border:1px solid #e4e7ec;border-radius:16px;padding:16px;margin:12px 0}.task{border:1px solid #e4e7ec;border-radius:13px;padding:13px;margin:9px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.big{font-size:25px;font-weight:800}.bad{color:#b42318}.warn{color:#b54708}.ok{color:#067647}.muted{color:#667085}button{padding:9px 12px;border:1px solid #ccd2dd;border-radius:9px;background:#2447a8;color:white;cursor:pointer}a{color:#175cd3;text-decoration:none}</style><main>
<div class=box><a href="/student">← بوابة الطالب</a><h1>قائمة المذاكرة الشخصية</h1><p class=muted>الأولوية مبنية على آخر 5 محاولات مقارنة بالـ5 السابقة، وليس على تقدير AI.</p></div><div id=content class=box>جارٍ تحميل الخطة...</div>
<script>function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}async function runTask(url,btn){btn.disabled=true;let r=await fetch(url,{method:'POST'}),x=await r.json().catch(()=>null);if(r.ok&&x.student_path){location.href=x.student_path;return}btn.disabled=false;alert(typeof x?.detail==='string'?x.detail:(x?.detail?.message||'تعذر إنشاء التدريب'))}async function load(){let r=await fetch('/api/student/study-queue',{cache:'no-store'}),x=await r.json().catch(()=>null);if(!r.ok){content.textContent=typeof x?.detail==='string'?x.detail:'تعذر تحميل الخطة';return}let s=x.progression_summary;content.outerHTML='<div class=box><div class=grid><div class=card><div class=muted>المهام</div><div class=big>'+x.summary.tasks+'</div></div><div class=card><div class=muted>عناصر تتراجع</div><div class="big bad">'+s.worsening_items+'</div></div><div class=card><div class=muted>تم التعافي</div><div class="big ok">'+s.recovered_items+'</div></div><div class=card><div class=muted>بمصدر شرح معتمد</div><div class=big>'+x.summary.study_tasks_with_approved_source+'</div></div></div></div><div class=box><h2>الأولوية الحالية</h2>'+ (x.queue.length?x.queue.map(t=>'<div class=task><b>'+t.priority+'. '+e(t.title)+'</b> <span class="'+(t.status==='worsening'||t.status==='persistent_weakness'?'bad':'warn')+'">('+e(t.status)+')</span><div class=muted>'+e(t.reason)+' · الإتقان الحديث '+e(t.recent_mastery??'—')+'%'+(t.delta==null?'':' · التغير '+(t.delta>0?'+':'')+t.delta+'%')+'</div>'+(t.source?'<div class=muted>المصدر: '+e(t.source.filename)+' · الصفحات '+e(t.source.start_page)+'–'+e(t.source.end_page)+'</div>':'<div class=muted>لا توجد صفحات شرح معتمدة لهذا العنصر؛ لن يتم اختراع شرح بديل.</div>')+'<button onclick="runTask(\''+t.action_url+'\',this)">ابدأ التدريب</button></div>').join(''):'<p class=ok>لا توجد نقاط ضعف مؤكدة تحتاج خطة علاجية حاليًا.</p>')+'</div>'}load()</script></main></html>'''


@app.get("/student/study-queue", response_class=HTMLResponse)
def student_study_queue_page():
    return PAGE
