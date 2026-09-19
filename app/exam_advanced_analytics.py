from __future__ import annotations

from statistics import median

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin


def _ratio(value, baseline):
    if value is None or baseline in (None, 0):
        return None
    return round(float(value) / float(baseline), 2)


def build_exam_analytics(quiz_id: int):
    with connect() as con:
        quiz = con.execute(
            """SELECT id,title,published,lifecycle_status,duration_minutes
              FROM quizzes WHERE id=%s""",
            (quiz_id,),
        ).fetchone()
        if not quiz:
            raise HTTPException(404, "Quiz not found")

        attempts = list(con.execute(
            """SELECT a.id,a.student_id,s.name student_name,a.score,a.max_score,a.started_at,a.completed_at,
              round(100.0*a.score/nullif(a.max_score,0),1) percentage
              FROM attempts a JOIN students s ON s.id=a.student_id
              WHERE a.quiz_id=%s AND a.completed_at IS NOT NULL
              ORDER BY a.completed_at,a.id""",
            (quiz_id,),
        ).fetchall())

        questions = list(con.execute(
            """SELECT q.id,q.text_verbatim,q.difficulty,q.question_type,l.title lesson_title,
              count(aa.id) responses,
              count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
              round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) success_rate,
              round(avg(NULLIF(aa.time_spent_seconds,0)),1) average_time_seconds
              FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id
              LEFT JOIN lessons l ON l.id=q.lesson_id
              LEFT JOIN attempt_answers aa ON aa.question_id=q.id
              LEFT JOIN attempts a ON a.id=aa.attempt_id AND a.quiz_id=%s AND a.completed_at IS NOT NULL
              WHERE qq.quiz_id=%s
              GROUP BY q.id,q.text_verbatim,q.difficulty,q.question_type,l.title,qq.position
              ORDER BY qq.position""",
            (quiz_id, quiz_id),
        ).fetchall())

        lessons = list(con.execute(
            """SELECT l.id,l.title label,count(aa.id) responses,
              count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
              round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) success_rate,
              round(avg(NULLIF(aa.time_spent_seconds,0)),1) average_time_seconds
              FROM attempts a
              JOIN attempt_answers aa ON aa.attempt_id=a.id
              JOIN questions q ON q.id=aa.question_id
              LEFT JOIN lessons l ON l.id=q.lesson_id
              WHERE a.quiz_id=%s AND a.completed_at IS NOT NULL
              GROUP BY l.id,l.title ORDER BY success_rate ASC NULLS LAST""",
            (quiz_id,),
        ).fetchall())

        skills = list(con.execute(
            """SELECT sk.id,sk.name_ar label,count(aa.id) responses,
              count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
              round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) success_rate,
              round(avg(NULLIF(aa.time_spent_seconds,0)),1) average_time_seconds
              FROM attempts a
              JOIN attempt_answers aa ON aa.attempt_id=a.id
              JOIN question_skills qs ON qs.question_id=aa.question_id
              JOIN skills sk ON sk.id=qs.skill_id
              WHERE a.quiz_id=%s AND a.completed_at IS NOT NULL
              GROUP BY sk.id,sk.name_ar,sk.sort_order
              ORDER BY success_rate ASC NULLS LAST,sk.sort_order""",
            (quiz_id,),
        ).fetchall())

        integrity = con.execute(
            """SELECT count(e.id) events,count(DISTINCT e.attempt_id) attempts
              FROM exam_integrity_events e JOIN attempts a ON a.id=e.attempt_id
              WHERE a.quiz_id=%s""",
            (quiz_id,),
        ).fetchone()

    times = [float(q["average_time_seconds"]) for q in questions if q["average_time_seconds"] not in (None, 0)]
    median_time = median(times) if times else 0
    flags = []
    for row in questions:
        q = dict(row)
        responses = int(q.get("responses") or 0)
        success = float(q["success_rate"]) if q.get("success_rate") is not None else None
        avg_time = float(q["average_time_seconds"]) if q.get("average_time_seconds") is not None else None
        reasons = []
        if responses >= 5 and success is not None and success <= 20:
            reasons.append("very_low_success")
        if responses >= 5 and success is not None and success >= 95:
            reasons.append("very_high_success")
        if responses >= 5 and avg_time is not None and median_time and avg_time >= median_time * 2:
            reasons.append("time_outlier")
        if reasons:
            q["flags"] = reasons
            q["time_ratio_to_median"] = _ratio(avg_time, median_time)
            flags.append(q)

    scores = [float(a["percentage"]) for a in attempts if a["percentage"] is not None]
    trend = []
    by_student = {}
    for a in attempts:
        by_student.setdefault(int(a["student_id"]), []).append(dict(a))
    for student_id, rows in by_student.items():
        if len(rows) < 2:
            continue
        first = float(rows[0]["percentage"] or 0)
        latest = float(rows[-1]["percentage"] or 0)
        trend.append({
            "student_id": student_id,
            "student_name": rows[-1]["student_name"],
            "first_percentage": first,
            "latest_percentage": latest,
            "delta": round(latest - first, 1),
            "attempt_count": len(rows),
        })
    trend.sort(key=lambda x: x["delta"])

    return {
        "quiz": quiz,
        "summary": {
            "attempts": len(attempts),
            "students": len(by_student),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "median_question_time_seconds": round(median_time, 1) if median_time else 0,
            "flagged_questions": len(flags),
            "integrity_events": int(integrity["events"] or 0),
            "attempts_with_integrity_events": int(integrity["attempts"] or 0),
        },
        "questions": questions,
        "flagged_questions": flags,
        "lessons": lessons,
        "skills": skills,
        "student_trends": trend,
        "policy": {
            "analysis": "deterministic",
            "flags_are_review_signals_not_auto_rejections": True,
            "minimum_responses_for_balance_flag": 5,
        },
    }


@app.get("/api/admin/exams/{quiz_id}/advanced-analytics", dependencies=[Depends(require_admin)])
def exam_advanced_analytics(quiz_id: int):
    return build_exam_analytics(quiz_id)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>تحليلات الامتحان المتقدمة</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:16px}.box{background:#fff;border:1px solid #e4e7ec;border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.big{font-size:26px;font-weight:800}.muted{color:#667085}.bad{color:#b42318}.warn{color:#b54708}.ok{color:#067647}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:850px}td,th{padding:8px;border-bottom:1px solid #eee;text-align:right;vertical-align:top}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}a{color:#175cd3;text-decoration:none}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/exam-engine">تشغيل الامتحانات</a><h1>تحليلات الامتحان المتقدمة</h1><div><input id=qid type=number min=1 placeholder="رقم الاختبار"><button onclick=load()>تحميل</button></div></div><div id=content></div>
<script>function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}function sec(v){v=Number(v||0);return v?Math.round(v)+' ث':'—'}async function load(){let id=Number(qid.value);if(!id)return;let r=await fetch('/api/admin/exams/'+id+'/advanced-analytics'),x=await r.json().catch(()=>null);if(!r.ok){content.innerHTML='<div class=box>تعذر تحميل التحليل</div>';return}let s=x.summary;content.innerHTML='<div class=box><h2>'+e(x.quiz.title)+'</h2><div class=grid>'+[['المحاولات',s.attempts],['الطلاب',s.students],['متوسط النتيجة',(s.average_score??'—')+'%'],['وسيط زمن السؤال',sec(s.median_question_time_seconds)],['أسئلة تحتاج مراجعة',s.flagged_questions],['أحداث نزاهة',s.integrity_events]].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class=big>'+v[1]+'</div></div>').join('')+'</div></div>'+table('حسب الدرس',x.lessons)+table('حسب المهارة',x.skills)+'<div class="box scroll"><h2>إشارات مراجعة توازن الأسئلة</h2><p class=muted>هذه إشارات للمراجعة فقط وليست حذفًا أو حكمًا تلقائيًا على السؤال.</p><table><tr><th>السؤال</th><th>النجاح</th><th>الزمن</th><th>الإشارات</th></tr>'+x.flagged_questions.map(q=>'<tr><td>#'+q.id+' '+e(q.text_verbatim)+'</td><td>'+e(q.success_rate??'—')+'%</td><td>'+sec(q.average_time_seconds)+'</td><td>'+q.flags.map(e).join('، ')+'</td></tr>').join('')+'</table></div><div class="box scroll"><h2>التغير بين محاولات الطلاب</h2><table><tr><th>الطالب</th><th>الأولى</th><th>الأخيرة</th><th>التغير</th><th>المحاولات</th></tr>'+x.student_trends.map(v=>'<tr><td>'+e(v.student_name)+'</td><td>'+v.first_percentage+'%</td><td>'+v.latest_percentage+'%</td><td class="'+(v.delta<0?'bad':'ok')+'">'+(v.delta>0?'+':'')+v.delta+'%</td><td>'+v.attempt_count+'</td></tr>').join('')+'</table></div>'}function table(title,a){return '<div class="box scroll"><h2>'+title+'</h2><table><tr><th>البند</th><th>الإجابات</th><th>النجاح</th><th>متوسط الزمن</th></tr>'+a.map(v=>'<tr><td>'+e(v.label||'—')+'</td><td>'+v.responses+'</td><td>'+e(v.success_rate??'—')+'%</td><td>'+sec(v.average_time_seconds)+'</td></tr>').join('')+'</table></div>'}</script></main></html>'''


@app.get("/admin/exam-analytics", response_class=HTMLResponse)
def exam_analytics_page():
    return PAGE
