from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin


def _risk_profile(*, days_inactive: int | None, recent_average: float | None,
                  weak_lessons: int, repeated_error_questions: int,
                  completed_attempts: int) -> dict:
    if completed_attempts <= 0:
        return {
            "score": 35,
            "priority": "baseline",
            "reasons": ["لا توجد محاولة مكتملة تكفي لبناء خط أساس."],
            "next_action": "baseline_assessment",
        }

    score = 0
    reasons: list[str] = []

    if days_inactive is None or days_inactive >= 14:
        score += 30
        reasons.append("لا يوجد نشاط مكتمل منذ أسبوعين أو أكثر.")
    elif days_inactive >= 7:
        score += 20
        reasons.append("مر أسبوع أو أكثر منذ آخر نشاط مكتمل.")
    elif days_inactive >= 3:
        score += 8
        reasons.append("النشاط الأخير ليس حديثًا.")

    if recent_average is not None:
        if recent_average < 50:
            score += 30
            reasons.append(f"متوسط آخر المحاولات منخفض ({recent_average:.1f}%).")
        elif recent_average < 65:
            score += 20
            reasons.append(f"متوسط آخر المحاولات يحتاج دعمًا ({recent_average:.1f}%).")
        elif recent_average < 75:
            score += 10
            reasons.append(f"متوسط الأداء ما زال دون مستوى التثبيت ({recent_average:.1f}%).")

    if weak_lessons:
        score += min(24, weak_lessons * 8)
        reasons.append(f"يوجد {weak_lessons} درسًا بضعف مؤكد.")
    if repeated_error_questions:
        score += min(16, repeated_error_questions * 4)
        reasons.append(f"يوجد {repeated_error_questions} سؤالًا بخطأ متكرر.")

    score = min(100, score)
    priority = "high" if score >= 55 else "medium" if score >= 30 else "low"
    if days_inactive is None or days_inactive >= 7:
        next_action = "reengage_student"
    elif weak_lessons > 0:
        next_action = "adaptive_practice"
    elif repeated_error_questions > 0:
        next_action = "mistake_review"
    else:
        next_action = "monitor"

    if not reasons:
        reasons.append("لا توجد إشارة خطر قوية في البيانات الحالية.")
    return {"score": score, "priority": priority, "reasons": reasons, "next_action": next_action}


def build_intervention_queue(limit: int = 100) -> dict:
    limit = min(max(int(limit), 1), 300)
    with connect() as con:
        rows = list(con.execute(
            """WITH completed AS (
                 SELECT a.id,a.student_id,a.completed_at,
                        100.0*a.score/nullif(a.max_score,0) pct,
                        row_number() OVER(PARTITION BY a.student_id ORDER BY a.completed_at DESC,a.id DESC) rn
                 FROM attempts a WHERE a.completed_at IS NOT NULL
               ), student_perf AS (
                 SELECT s.id student_id,s.name student_name,
                        count(c.id) completed_attempts,max(c.completed_at) last_completed,
                        round(avg(c.pct) FILTER(WHERE c.rn<=5),1) recent_average
                 FROM students s LEFT JOIN completed c ON c.student_id=s.id
                 GROUP BY s.id,s.name
               ), weak AS (
                 SELECT student_id,count(*) weak_lessons FROM (
                   SELECT a.student_id,q.lesson_id
                   FROM attempts a JOIN attempt_answers aa ON aa.attempt_id=a.id
                   JOIN questions q ON q.id=aa.question_id
                   WHERE a.completed_at IS NOT NULL AND q.lesson_id IS NOT NULL
                   GROUP BY a.student_id,q.lesson_id
                   HAVING count(aa.id)>=2
                     AND 100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0)<60
                 ) x GROUP BY student_id
               ), repeated AS (
                 SELECT student_id,count(*) repeated_error_questions FROM (
                   SELECT a.student_id,aa.question_id
                   FROM attempts a JOIN attempt_answers aa ON aa.attempt_id=a.id
                   WHERE a.completed_at IS NOT NULL AND aa.is_correct=FALSE
                   GROUP BY a.student_id,aa.question_id HAVING count(*)>=2
                 ) x GROUP BY student_id
               )
               SELECT p.student_id,p.student_name,p.completed_attempts,p.last_completed,p.recent_average,
                      coalesce(w.weak_lessons,0) weak_lessons,
                      coalesce(r.repeated_error_questions,0) repeated_error_questions,
                      CASE WHEN p.last_completed IS NULL THEN NULL
                           ELSE greatest(0,current_date-p.last_completed::date) END days_inactive
               FROM student_perf p
               LEFT JOIN weak w ON w.student_id=p.student_id
               LEFT JOIN repeated r ON r.student_id=p.student_id
               ORDER BY p.student_id"""
        ).fetchall())

    items = []
    for raw in rows:
        row = dict(raw)
        profile = _risk_profile(
            days_inactive=int(row["days_inactive"]) if row["days_inactive"] is not None else None,
            recent_average=float(row["recent_average"]) if row["recent_average"] is not None else None,
            weak_lessons=int(row["weak_lessons"] or 0),
            repeated_error_questions=int(row["repeated_error_questions"] or 0),
            completed_attempts=int(row["completed_attempts"] or 0),
        )
        items.append({**row, **profile})

    rank = {"high": 0, "baseline": 1, "medium": 2, "low": 3}
    items.sort(key=lambda x: (rank.get(x["priority"], 9), -int(x["score"]), x["student_name"] or ""))
    summary = {
        "students": len(items),
        "high": sum(1 for x in items if x["priority"] == "high"),
        "baseline": sum(1 for x in items if x["priority"] == "baseline"),
        "medium": sum(1 for x in items if x["priority"] == "medium"),
        "low": sum(1 for x in items if x["priority"] == "low"),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "items": items[:limit],
        "policy": {
            "engine": "deterministic_rules",
            "llm_risk_classification": False,
            "no_automatic_messaging": True,
            "teacher_decision_remains_final": True,
        },
    }


@app.get("/api/admin/intervention-queue", dependencies=[Depends(require_admin)])
def intervention_queue(limit: int = 100, priority: str | None = None):
    data = build_intervention_queue(limit=300)
    limit = min(max(limit, 1), 300)
    if priority:
        if priority not in {"high", "baseline", "medium", "low"}:
            raise HTTPException(400, "Invalid priority")
        data["items"] = [x for x in data["items"] if x["priority"] == priority][:limit]
    else:
        data["items"] = data["items"][:limit]
    return data


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>قائمة تدخل المدرس</title><style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--high:#b42318;--medium:#b54708;--good:#067647}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif}main{max-width:1200px;margin:auto;padding:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.card{border:1px solid var(--line);border-radius:12px;padding:12px}.big{font-size:26px;font-weight:800}.muted{color:var(--muted);font-size:13px}.high{color:var(--high)}.baseline,.medium{color:var(--medium)}.low{color:var(--good)}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}select{padding:10px;border:1px solid var(--line);border-radius:9px}a{color:#175cd3;text-decoration:none}@media(max-width:760px){table{min-width:880px}.scroll{overflow:auto}main{padding:9px}.box{border-radius:14px;padding:12px}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/progress">متابعة التقدم</a><h1>قائمة تدخل المدرس</h1><p class=muted>ترتيب حتمي مبني على النشاط، متوسط الأداء، الدروس الضعيفة والأخطاء المتكررة. لا يستخدم نموذج ذكاء لتصنيف الطالب.</p><select id=priority onchange=load()><option value="">كل الأولويات</option><option value=high>عالية</option><option value=baseline>يحتاج خط أساس</option><option value=medium>متوسطة</option><option value=low>منخفضة</option></select><div id=msg class=muted></div></div><div id=out></div>
<script>function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}const actionLabel={baseline_assessment:'ابدأ بقياس خط أساس',reengage_student:'إعادة إشراك الطالب',adaptive_practice:'تدريب علاجي',mistake_review:'مراجعة الأخطاء',monitor:'متابعة فقط'};async function load(){let q=priority.value?'?priority='+encodeURIComponent(priority.value):'';let r=await fetch('/api/admin/intervention-queue'+q),x=await r.json().catch(()=>null);if(!r.ok){msg.textContent='تعذر تحميل القائمة';return}let s=x.summary;out.innerHTML=`<div class=box><div class=grid><div class=card><div class=muted>إجمالي الطلاب</div><div class=big>${s.students}</div></div><div class=card><div class=muted>أولوية عالية</div><div class="big high">${s.high}</div></div><div class=card><div class=muted>يحتاج خط أساس</div><div class="big baseline">${s.baseline}</div></div><div class=card><div class=muted>متوسطة</div><div class="big medium">${s.medium}</div></div></div></div><div class="box scroll"><table><tr><th>الطالب</th><th>الأولوية</th><th>آخر نشاط</th><th>متوسط حديث</th><th>دروس ضعيفة</th><th>أخطاء متكررة</th><th>الأسباب</th><th>الخطوة</th></tr>${x.items.map(v=>`<tr><td><b>${e(v.student_name)}</b><br><a href="/admin/students/${v.student_id}/knowledge-map">خريطة المعرفة</a></td><td class="${v.priority}"><b>${e(v.priority)}</b><br>${v.score}/100</td><td>${v.days_inactive==null?'—':v.days_inactive+' يوم'}</td><td>${v.recent_average==null?'—':v.recent_average+'%'}</td><td>${v.weak_lessons}</td><td>${v.repeated_error_questions}</td><td>${v.reasons.map(e).join('<br>')}</td><td>${e(actionLabel[v.next_action]||v.next_action)}</td></tr>`).join('')}</table></div>`}load()</script></main></html>'''


@app.get("/admin/intervention-queue", response_class=HTMLResponse)
def intervention_queue_page():
    return PAGE
