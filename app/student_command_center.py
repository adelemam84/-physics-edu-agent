from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .advanced_learning import _readiness, _review_queue
from .analytics import _learning_recommendations, _student_mastery
from .db import connect
from .student_security import resolve_student_code

router = APIRouter()


def _student_activity(con, student_id: int) -> dict:
    summary = con.execute(
        """SELECT
          count(*) FILTER(WHERE a.completed_at >= now()-interval '7 days') completed_7d,
          count(*) FILTER(WHERE a.completed_at >= now()-interval '14 days'
                            AND a.completed_at < now()-interval '7 days') completed_prev_7d,
          round(avg(100.0*a.score/nullif(a.max_score,0)) FILTER(
            WHERE a.completed_at >= now()-interval '7 days' AND a.max_score>0),1) avg_7d,
          round(avg(100.0*a.score/nullif(a.max_score,0)) FILTER(
            WHERE a.completed_at >= now()-interval '14 days'
              AND a.completed_at < now()-interval '7 days' AND a.max_score>0),1) avg_prev_7d,
          count(DISTINCT a.completed_at::date) FILTER(
            WHERE a.completed_at >= now()-interval '7 days') active_days_7d,
          max(a.completed_at) last_completed
          FROM attempts a WHERE a.student_id=%s AND a.completed_at IS NOT NULL""",
        (student_id,),
    ).fetchone()
    answers = con.execute(
        """SELECT count(*) responses,
          count(*) FILTER(WHERE aa.is_correct=TRUE) correct
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
          WHERE a.student_id=%s AND a.completed_at >= now()-interval '7 days'""",
        (student_id,),
    ).fetchone()
    days = [
        r["day"]
        for r in con.execute(
            """SELECT DISTINCT completed_at::date day FROM attempts
               WHERE student_id=%s AND completed_at IS NOT NULL
                 AND completed_at >= current_date-interval '45 days'
               ORDER BY day DESC""",
            (student_id,),
        ).fetchall()
    ]
    day_set = set(days)
    today = date.today()
    anchor = today if today in day_set else today - timedelta(days=1)
    streak = 0
    while anchor in day_set:
        streak += 1
        anchor -= timedelta(days=1)

    avg_7d = float(summary["avg_7d"]) if summary and summary["avg_7d"] is not None else None
    avg_prev = float(summary["avg_prev_7d"]) if summary and summary["avg_prev_7d"] is not None else None
    delta = round(avg_7d - avg_prev, 1) if avg_7d is not None and avg_prev is not None else None
    responses = int(answers["responses"] or 0) if answers else 0
    correct = int(answers["correct"] or 0) if answers else 0
    return {
        "completed_attempts_7d": int(summary["completed_7d"] or 0) if summary else 0,
        "completed_attempts_previous_7d": int(summary["completed_prev_7d"] or 0) if summary else 0,
        "average_7d": avg_7d,
        "average_previous_7d": avg_prev,
        "average_delta": delta,
        "active_days_7d": int(summary["active_days_7d"] or 0) if summary else 0,
        "current_streak_days": streak,
        "responses_7d": responses,
        "correct_7d": correct,
        "accuracy_7d": round(100.0 * correct / responses, 1) if responses else None,
        "last_completed": summary["last_completed"] if summary else None,
    }


def _evidence_confidence(readiness: dict, mastery: dict, activity: dict) -> dict:
    attempts = int(readiness.get("recent_attempts") or 0)
    responses = int(activity.get("responses_7d") or 0)
    covered_lessons = sum(1 for x in mastery.get("lessons", []) if int(x.get("responses") or 0) >= 2)
    points = min(attempts, 5) + min(responses // 5, 5) + min(covered_lessons, 5)
    level = "high" if points >= 11 else "medium" if points >= 6 else "low"
    if level == "high":
        message = "القراءة الحالية مدعومة ببيانات أداء كافية نسبيًا."
    elif level == "medium":
        message = "المؤشرات مفيدة، لكن مزيدًا من الاختبارات القصيرة سيزيد دقتها."
    else:
        message = "البيانات الحالية محدودة؛ اعتبر الجاهزية تقديرًا أوليًا حتى تتوفر محاولات أكثر."
    return {
        "level": level,
        "score": min(100, round(points / 15 * 100)),
        "recent_attempts": attempts,
        "responses_7d": responses,
        "covered_lessons": covered_lessons,
        "message": message,
    }


def _today_mission(learning: dict, reviews: list[dict], readiness: dict) -> dict:
    recommendations = learning.get("recommendations") or []
    first = recommendations[0] if recommendations else None
    if first and first.get("action") == "study_next" and first.get("lesson_id"):
        return {
            "kind": "study_lesson",
            "title": first.get("title") or "ابدأ الدرس التالي",
            "reason": first.get("reason") or "الدرس التالي هو أفضل خطوة الآن.",
            "primary_action": {"type": "navigate", "label": "ابدأ الدرس", "path": f"/student/lesson/{first['lesson_id']}"},
            "target": "درس واحد ثم اختبار تمهيدي",
        }
    if first and first.get("action") == "adaptive_practice":
        return {
            "kind": "adaptive_practice",
            "title": first.get("title") or "تدريب علاجي مركز",
            "reason": first.get("reason") or "التدريب التكيفي هو أعلى أولوية الآن.",
            "primary_action": {"type": "adaptive_practice", "label": "ابدأ تدريبًا مناسبًا", "count": 10},
            "target": "10 أسئلة معتمدة من نقاط الضعف",
        }
    if reviews:
        return {
            "kind": "review_mistakes",
            "title": "راجع أخطاءك المتكررة",
            "reason": f"لديك {len(reviews)} سؤالًا معتمدًا يحتاج مراجعة متباعدة.",
            "primary_action": {"type": "navigate", "label": "افتح مركز التعلم", "path": "/student/learning-suite"},
            "target": f"راجع أول {min(6, len(reviews))} أسئلة ثم أعد التدريب",
        }
    if readiness.get("level") == "needs_baseline":
        return {
            "kind": "baseline",
            "title": "كوّن خط أساس لمستواك",
            "reason": "لا توجد محاولات كافية لقياس الجاهزية بدقة.",
            "primary_action": {"type": "navigate", "label": "اختر اختبارًا منشورًا", "path": "/student#quizzes"},
            "target": "اختبار قصير واحد مكتمل",
        }
    return {
        "kind": "maintenance",
        "title": "ثبّت مستواك الحالي",
        "reason": "لا توجد فجوة ذات أولوية أعلى في البيانات الحالية.",
        "primary_action": {"type": "navigate", "label": "افتح الاختبارات", "path": "/student#quizzes"},
        "target": "اختبار قصير أو مراجعة مركزة",
    }


def build_student_command_center(student_id: int) -> dict:
    with connect() as con:
        student = con.execute("SELECT id,name FROM students WHERE id=%s", (student_id,)).fetchone()
        if not student:
            raise HTTPException(404, "الطالب غير موجود")
        activity = _student_activity(con, student_id)
        readiness = _readiness(con, student_id)
        mastery = _student_mastery(con, student_id)
        learning = _learning_recommendations(con, student_id)
        reviews = _review_queue(con, student_id, 12)
    confidence = _evidence_confidence(readiness, mastery, activity)
    mission = _today_mission(learning, reviews, readiness)
    weak = mastery.get("summary") or {}
    return {
        "student": dict(student),
        "today_mission": mission,
        "activity": activity,
        "readiness": readiness,
        "evidence_confidence": confidence,
        "focus": {
            "weak_lessons": int(weak.get("weak_lessons") or 0),
            "weak_concepts": int(weak.get("weak_concepts") or 0),
            "weak_skills": int(weak.get("weak_skills") or 0),
            "review_questions": len(reviews),
            "priority_concepts": mastery.get("priority", {}).get("concepts", [])[:3],
            "priority_skills": mastery.get("priority", {}).get("skills", [])[:2],
        },
        "recommendations": (learning.get("recommendations") or [])[:4],
        "integrity": {
            "decision_engine": "deterministic_student_performance_rules",
            "questions": "approved_source_questions_only",
            "llm_decision_making": False,
            "readiness_is_estimate_not_grade": True,
        },
    }


@router.get("/api/student/command-center")
def student_command_center_api(request: Request):
    code = resolve_student_code(request)
    with connect() as con:
        student = con.execute("SELECT id FROM students WHERE external_code=%s", (code,)).fetchone()
    if not student:
        raise HTTPException(404, "كود الطالب غير صحيح")
    return build_student_command_center(student["id"])


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز قيادة التعلم</title>
<style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--brand:#2447a8;--soft:#eef3ff;--good:#067647;--warn:#b54708}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text)}main{max-width:1050px;margin:auto;padding:16px 16px 90px}.box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}.hero{background:linear-gradient(135deg,#fff,#eef3ff)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.card{border:1px solid var(--line);border-radius:13px;padding:13px}.big{font-size:27px;font-weight:800}.muted{color:var(--muted);font-size:13px}.good{color:var(--good)}.warn{color:var(--warn)}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.pill{display:inline-block;padding:5px 9px;border-radius:999px;background:var(--soft);color:var(--brand);font-size:12px;font-weight:700}button,a.action{padding:10px 12px;border:1px solid var(--line);border-radius:10px;font:inherit;cursor:pointer;text-decoration:none}button.primary,a.primary{background:var(--brand);color:#fff;border-color:var(--brand)}a{color:var(--brand);text-decoration:none}.mission{border-right:5px solid var(--brand)}button:focus-visible,a:focus-visible{outline:3px solid #84adff;outline-offset:2px}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}@media(max-width:600px){main{padding:10px 10px 80px}.box{border-radius:14px;padding:13px}.grid{grid-template-columns:1fr 1fr}.big{font-size:22px}}@media(max-width:390px){.grid{grid-template-columns:1fr}}
</style><main>
<div class="box hero"><div class="row"><a href="/student">← بوابة الطالب</a><a href="/student/learning-suite">مركز التعلم الذكي</a></div><h1>مركز قيادة التعلم</h1><p class="muted">خطوة واحدة واضحة لليوم، مع قراءة للتقدم وجودة الأدلة التي يعتمد عليها القياس.</p><div id="msg" class="muted" aria-live="polite"></div></div><div id="out"></div>
<script>
const msg=document.getElementById('msg'),out=document.getElementById('out');
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function adaptive(count){msg.textContent='جارٍ تجهيز التدريب...';let r=await fetch('/api/student/adaptive-practice/create?count='+(count||10),{method:'POST'}),x=await r.json().catch(()=>null);if(!r.ok){msg.textContent=typeof x?.detail==='string'?x.detail:(x?.detail?.message||'تعذر إنشاء التدريب');return}location.href=x.student_path}
function action(a){if(!a)return '';if(a.type==='adaptive_practice')return '<button class="primary" onclick="adaptive('+Number(a.count||10)+')">'+e(a.label)+'</button>';return '<a class="action primary" href="'+e(a.path||'/student')+'">'+e(a.label||'ابدأ')+'</a>'}
async function load(){let s=await fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));if(!s.authenticated){location.href='/student';return}let r=await fetch('/api/student/command-center',{cache:'no-store'}),x=await r.json().catch(()=>null);if(!r.ok){msg.textContent=typeof x?.detail==='string'?x.detail:'تعذر تحميل مركز التعلم';return}let a=x.activity,c=x.evidence_confidence,f=x.focus,m=x.today_mission,rd=x.readiness;out.innerHTML=`<div class="box mission"><span class=pill>مهمة اليوم</span><h2>${e(m.title)}</h2><p>${e(m.reason)}</p><p class=muted>الهدف: ${e(m.target)}</p><div class=row>${action(m.primary_action)}</div></div><div class=box><h2>نبض آخر 7 أيام</h2><div class=grid><div class=card><div class=muted>أيام النشاط</div><div class=big>${a.active_days_7d}</div></div><div class=card><div class=muted>السلسلة الحالية</div><div class=big>${a.current_streak_days}</div></div><div class=card><div class=muted>متوسط الأداء</div><div class=big>${a.average_7d==null?'—':a.average_7d+'%'}</div></div><div class=card><div class=muted>دقة الإجابات</div><div class=big>${a.accuracy_7d==null?'—':a.accuracy_7d+'%'}</div></div></div>${a.average_delta==null?'':`<p class="${a.average_delta>=0?'good':'warn'}">التغير عن الأسبوع السابق: ${a.average_delta>0?'+':''}${a.average_delta}%</p>`}</div><div class=box><h2>الجاهزية وجودة القياس</h2><div class=grid><div class=card><div class=muted>مؤشر الجاهزية</div><div class=big>${rd.score}%</div><div class=muted>${e(rd.message)}</div></div><div class=card><div class=muted>ثقة الأدلة</div><div class=big>${c.score}%</div><div class="${c.level==='high'?'good':c.level==='low'?'warn':''}">${e(c.level)}</div></div></div><p class=muted>${e(c.message)}</p></div><div class=box><h2>أماكن التركيز</h2><div class=grid><div class=card><div class=muted>دروس ضعيفة</div><div class=big>${f.weak_lessons}</div></div><div class=card><div class=muted>مفاهيم ضعيفة</div><div class=big>${f.weak_concepts}</div></div><div class=card><div class=muted>مهارات ضعيفة</div><div class=big>${f.weak_skills}</div></div><div class=card><div class=muted>أسئلة للمراجعة</div><div class=big>${f.review_questions}</div></div></div>${f.priority_concepts.length?'<h3>أعلى المفاهيم أولوية</h3>'+f.priority_concepts.map(v=>'<div class=card><b>'+e(v.title)+'</b><div class=muted>'+e(v.lesson_title||'')+' · إتقان '+e(v.mastery)+'% من '+e(v.responses)+' إجابات</div></div>').join(''):''}</div><div class=box><h2>بعد مهمة اليوم</h2>${x.recommendations.map((v,i)=>'<div class=card><b>'+(i+1)+'. '+e(v.title)+'</b><div class=muted>'+e(v.reason)+'</div></div>').join('')}</div>`}
load();
</script></main></html>'''


@router.get("/student/command-center", response_class=HTMLResponse)
def student_command_center_page():
    return PAGE
