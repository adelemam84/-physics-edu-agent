from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .student_security import resolve_student_code
from .study_intelligence import build_personal_study_queue, build_weakness_progression


def _student(con, student_code: str):
    code = (student_code or "").strip()
    if not code:
        raise HTTPException(400, "student_code is required")
    row = con.execute(
        "SELECT id,name FROM students WHERE external_code=%s",
        (code,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "كود الطالب غير صحيح")
    return row


def _mastery_rows(con, student_id: int):
    return list(
        con.execute(
            """SELECT l.id lesson_id,l.title lesson_title,l.sort_order,
              count(aa.id) responses,
              count(aa.id) FILTER(WHERE aa.is_correct=TRUE) correct,
              round(100.0*count(aa.id) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(aa.id),0),1) mastery
              FROM attempt_answers aa
              JOIN attempts a ON a.id=aa.attempt_id
              JOIN questions q ON q.id=aa.question_id
              LEFT JOIN lessons l ON l.id=q.lesson_id
              WHERE a.student_id=%s AND a.completed_at IS NOT NULL
              GROUP BY l.id,l.title,l.sort_order
              HAVING count(aa.id)>0
              ORDER BY mastery ASC NULLS FIRST,responses DESC,l.sort_order NULLS LAST,l.id""",
            (student_id,),
        ).fetchall()
    )


def _review_queue(con, student_id: int, limit: int = 12):
    return list(
        con.execute(
            """SELECT q.id question_id,q.text_verbatim,q.difficulty,q.question_type,
              q.source_page,l.id lesson_id,l.title lesson_title,d.filename source_filename,
              count(*) FILTER(WHERE aa.is_correct=FALSE) wrong_count,
              count(*) FILTER(WHERE aa.is_correct=TRUE) correct_count,
              max(a.completed_at) last_seen,
              max(a.completed_at) FILTER(WHERE aa.is_correct=FALSE) last_wrong
              FROM attempt_answers aa
              JOIN attempts a ON a.id=aa.attempt_id
              JOIN questions q ON q.id=aa.question_id
              JOIN documents d ON d.id=q.document_id
              LEFT JOIN lessons l ON l.id=q.lesson_id
              WHERE a.student_id=%s AND a.completed_at IS NOT NULL AND q.approved=TRUE
                AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open')
              GROUP BY q.id,q.text_verbatim,q.difficulty,q.question_type,q.source_page,l.id,l.title,d.filename
              HAVING count(*) FILTER(WHERE aa.is_correct=FALSE)>0
              ORDER BY
                (count(*) FILTER(WHERE aa.is_correct=FALSE)-count(*) FILTER(WHERE aa.is_correct=TRUE)) DESC,
                max(a.completed_at) FILTER(WHERE aa.is_correct=FALSE) DESC NULLS LAST
              LIMIT %s""",
            (student_id, min(max(limit, 1), 30)),
        ).fetchall()
    )


def _readiness(con, student_id: int):
    row = con.execute(
        """WITH recent AS (
          SELECT 100.0*a.score/nullif(a.max_score,0) pct,
                 row_number() OVER(ORDER BY coalesce(a.completed_at,a.submitted_at) DESC,a.id DESC) rn
          FROM attempts a WHERE a.student_id=%s AND a.max_score>0 AND a.completed_at IS NOT NULL
        ), agg AS (
          SELECT avg(pct) FILTER(WHERE rn<=5) recent_avg,
                 avg(pct) FILTER(WHERE rn BETWEEN 6 AND 10) previous_avg,
                 count(*) FILTER(WHERE rn<=5) recent_attempts FROM recent
        ) SELECT * FROM agg""",
        (student_id,),
    ).fetchone()
    mastery = _mastery_rows(con, student_id)
    weak = [r for r in mastery if r["mastery"] is not None and float(r["mastery"]) < 60]
    developing = [r for r in mastery if r["mastery"] is not None and 60 <= float(r["mastery"]) < 75]
    recent_avg = float(row["recent_avg"]) if row and row["recent_avg"] is not None else None
    previous_avg = float(row["previous_avg"]) if row and row["previous_avg"] is not None else None
    trend = None if recent_avg is None or previous_avg is None else round(recent_avg - previous_avg, 1)
    if recent_avg is None:
        level = "needs_baseline"
        score = 0
        message = "ابدأ اختبارًا تشخيصيًا معتمدًا لتكوين خط أساس دقيق."
    else:
        mastery_penalty = min(len(weak) * 5 + len(developing) * 2, 25)
        score = max(0, min(100, round(recent_avg - mastery_penalty + (min(trend or 0, 10) * 0.5))))
        if score >= 85 and not weak:
            level, message = "exam_ready", "الأداء الحالي قوي؛ حافظ على المراجعة المركزة ومحاكاة الامتحانات."
        elif score >= 70:
            level, message = "nearly_ready", "أنت قريب من الجاهزية؛ ركز على الدروس الأضعف ثم أعد القياس."
        else:
            level, message = "building", "الأولوية الآن لإغلاق فجوات الإتقان قبل زيادة كثافة الامتحانات."
    return {
        "score": score,
        "level": level,
        "message": message,
        "recent_average": round(recent_avg, 1) if recent_avg is not None else None,
        "trend": trend,
        "weak_lessons": len(weak),
        "developing_lessons": len(developing),
        "recent_attempts": int(row["recent_attempts"] or 0) if row else 0,
    }


def _study_plan(con, student_id: int):
    mastery = _mastery_rows(con, student_id)
    reviews = _review_queue(con, student_id, 10)
    weak = [r for r in mastery if r["mastery"] is None or float(r["mastery"]) < 70]
    tasks = []
    for idx, lesson in enumerate(weak[:3], start=1):
        tasks.append({
            "priority": idx,
            "type": "lesson_repair",
            "lesson_id": lesson["lesson_id"],
            "title": lesson["lesson_title"] or "درس غير مصنف",
            "reason": f"نسبة الإتقان الحالية {lesson['mastery'] or 0}% عبر {lesson['responses']} إجابة.",
            "action": "study_then_adaptive_practice",
        })
    if reviews:
        tasks.append({
            "priority": len(tasks) + 1,
            "type": "spaced_review",
            "title": "مراجعة الأخطاء المتكررة",
            "reason": f"لديك {len(reviews)} سؤالًا معتمدًا يستحق إعادة المراجعة.",
            "action": "review_queue",
        })
    if not tasks:
        tasks.append({
            "priority": 1,
            "type": "maintenance",
            "title": "تثبيت المستوى",
            "reason": "لا توجد فجوات قوية مؤكدة في البيانات الحالية.",
            "action": "published_quiz",
        })
    return tasks


def _mock_exam(con, student_id: int):
    row = con.execute(
        """SELECT q.id,q.title,q.duration_minutes,q.max_attempts,q.score_policy,q.published_at,
          (SELECT count(*) FROM attempts a WHERE a.student_id=%s AND a.quiz_id=q.id AND a.completed_at IS NOT NULL) attempts_used,
          (SELECT max(100.0*a.score/nullif(a.max_score,0)) FROM attempts a WHERE a.student_id=%s AND a.quiz_id=q.id AND a.completed_at IS NOT NULL) best_percentage
          FROM quizzes q
          LEFT JOIN curriculum_versions cv ON cv.id=q.curriculum_version_id
          WHERE q.published=TRUE AND q.lifecycle_status='published'
            AND q.owner_student_id IS NULL AND coalesce(cv.active,TRUE)=TRUE
          ORDER BY
            CASE WHEN (SELECT count(*) FROM attempts a WHERE a.student_id=%s AND a.quiz_id=q.id AND a.completed_at IS NOT NULL)=0 THEN 0 ELSE 1 END,
            q.quality_score DESC NULLS LAST,q.published_at DESC NULLS LAST,q.id DESC
          LIMIT 1""",
        (student_id, student_id, student_id),
    ).fetchone()
    if not row:
        return {"available": False, "reason": "لا يوجد اختبار منشور من المنهج الحالي متاح الآن."}
    return {"available": True, "quiz": row, "student_path": f"/student/quiz/{row['id']}"}


def _achievements(con, student_id: int):
    stats = con.execute(
        """SELECT count(*) FILTER(WHERE a.completed_at IS NOT NULL) completed_attempts,
          count(*) FILTER(WHERE a.completed_at IS NOT NULL AND a.max_score>0 AND 100.0*a.score/a.max_score>=80) high_scores,
          max(100.0*a.score/nullif(a.max_score,0)) best_score
          FROM attempts a WHERE a.student_id=%s""",
        (student_id,),
    ).fetchone()
    correct = con.execute(
        """SELECT count(*) correct_answers FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id
          WHERE a.student_id=%s AND aa.is_correct=TRUE""",
        (student_id,),
    ).fetchone()["correct_answers"]
    items = []
    if int(stats["completed_attempts"] or 0) >= 1:
        items.append({"code": "first_attempt", "title": "بداية قوية", "description": "أكملت أول اختبار."})
    if int(stats["completed_attempts"] or 0) >= 5:
        items.append({"code": "consistent_5", "title": "مستمر", "description": "أكملت 5 اختبارات أو أكثر."})
    if int(stats["high_scores"] or 0) >= 3:
        items.append({"code": "three_80", "title": "ثبات الأداء", "description": "حققت 80% أو أكثر في ثلاث محاولات."})
    if int(correct or 0) >= 50:
        items.append({"code": "fifty_correct", "title": "50 إجابة صحيحة", "description": "تجاوزت 50 إجابة صحيحة موثقة."})
    best = float(stats["best_score"]) if stats["best_score"] is not None else None
    if best is not None and best >= 95:
        items.append({"code": "elite_95", "title": "تميز", "description": "حققت 95% أو أكثر في اختبار معتمد."})
    return {"earned": items, "count": len(items), "best_score": round(best, 1) if best is not None else None}


def _source_tutor_context(con, student_id: int):
    mastery = _mastery_rows(con, student_id)
    target = mastery[0] if mastery else None
    if not target or not target["lesson_id"]:
        return {"available": False, "reason": "لا توجد بيانات كافية لتحديد درس مستهدف."}
    mapping = con.execute(
        """SELECT lsm.lesson_id,lsm.document_id,lsm.start_page,lsm.end_page,d.filename,d.kind
          FROM lesson_source_mappings lsm JOIN documents d ON d.id=lsm.document_id
          WHERE lsm.lesson_id=%s AND lsm.mapping_status='approved'
            AND d.kind IN ('lesson','explanation','textbook','notes')
          ORDER BY lsm.id DESC LIMIT 1""",
        (target["lesson_id"],),
    ).fetchone()
    if not mapping:
        return {
            "available": False,
            "lesson_id": target["lesson_id"],
            "lesson_title": target["lesson_title"],
            "reason": "الدرس المستهدف لا يملك بعد صفحات شرح PDF معتمدة؛ لن يتم اختراع شرح بديل.",
        }
    return {
        "available": True,
        "lesson_id": target["lesson_id"],
        "lesson_title": target["lesson_title"],
        "source": mapping,
        "rule": "المدرس الذكي يعرض/يشرح فقط من صفحات المصدر المعتمدة لهذا الدرس.",
    }


def build_learning_suite(student_code: str):
    with connect() as con:
        st = _student(con, student_code)
        readiness = _readiness(con, st["id"])
        plan = _study_plan(con, st["id"])
        review = _review_queue(con, st["id"], 12)
        mock = _mock_exam(con, st["id"])
        achievements = _achievements(con, st["id"])
        tutor = _source_tutor_context(con, st["id"])
        report = {
            "student": st,
            "readiness": readiness,
            "priority_plan": plan,
            "review_count": len(review),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        student_id = st["id"]
    weakness_progression = build_weakness_progression(student_id)
    dynamic_study_queue = build_personal_study_queue(student_id, 10, weakness_progression)
    return {
        "student": st,
        "source_grounded_tutor": tutor,
        "personal_study_plan": plan,
        "dynamic_study_queue": dynamic_study_queue,
        "weakness_progression": weakness_progression,
        "spaced_review": {"questions": review, "count": len(review)},
        "mock_exam": mock,
        "exam_readiness": readiness,
        "progress_report": report,
        "achievements": achievements,
        "integrity": {
            "questions": "approved_pdf_only",
            "scientific_explanations": "approved_explanatory_pdf_only",
            "generated_questions": False,
        },
    }


@app.get("/api/student/learning-suite")
def learning_suite_api(request: Request):
    return build_learning_suite(resolve_student_code(request))


@app.get("/api/student/review-queue")
def review_queue_api(request: Request, limit: int = 12):
    with connect() as con:
        st = _student(con, resolve_student_code(request))
        return {"student": st, "questions": _review_queue(con, st["id"], limit)}


@app.get("/api/student/exam-readiness")
def exam_readiness_api(request: Request):
    with connect() as con:
        st = _student(con, resolve_student_code(request))
        return {"student": st, "readiness": _readiness(con, st["id"]), "mock_exam": _mock_exam(con, st["id"])}


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز التعلم الذكي</title>
<style>body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1050px;margin:auto;padding:18px}.box{background:white;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:13px}.big{font-size:28px;font-weight:800}.muted{color:#667085}.good{color:#067647}.warn{color:#b54708}input,button{padding:11px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}button{cursor:pointer}.q{margin:8px 0;padding:10px;border-right:4px solid #98a2b3;background:#f8fafc;border-radius:8px}</style>
<main><div class="box"><a href="/student">العودة لبوابة الطالب</a><h1>مركز التعلم الذكي</h1><p class="muted">9 أدوات تعليمية متقدمة مع الحفاظ على المصدر PDF كمرجع علمي وحيد.</p><input id="code" autocomplete="one-time-code" placeholder="كود الطالب"><button onclick="load()">فتح الخطة</button><div id="msg" class="muted" aria-live="polite"></div></div><div id="out"></div>
<script>function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}async function ensureSession(){let s=await fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));if(s.authenticated)return true;let v=code.value.trim();if(!v){msg.textContent='أدخل كود الطالب أولًا';return false}let r=await fetch('/api/student/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_code:v})}),x=await r.json().catch(()=>null);if(!r.ok){msg.textContent=typeof x?.detail==='string'?x.detail:'تعذر تسجيل الدخول';return false}code.value='';return true}async function load(){msg.textContent='';if(!await ensureSession())return;let r=await fetch('/api/student/learning-suite',{cache:'no-store'});let x=await r.json();if(!r.ok){msg.textContent=x.detail||'تعذر تحميل البيانات';return}let rd=x.exam_readiness,t=x.source_grounded_tutor,m=x.mock_exam;out.innerHTML=`<div class="box"><h2>${e(x.student.name)}</h2><div class="grid"><div class="card"><div class="muted">جاهزية الامتحان</div><div class="big">${rd.score}%</div><div>${e(rd.message)}</div></div><div class="card"><div class="muted">قائمة المراجعة</div><div class="big">${x.spaced_review.count}</div></div><div class="card"><div class="muted">الإنجازات</div><div class="big">${x.achievements.count}</div></div></div></div><div class="box"><h2>1) المدرس الذكي المرتبط بالمصدر</h2><div class="card ${t.available?'good':'warn'}">${t.available?'الدرس: <b>'+e(t.lesson_title)+'</b><div class=muted>المصدر: '+e(t.source.filename)+' · الصفحات '+t.source.start_page+'–'+t.source.end_page+'</div>':e(t.reason)}</div></div><div class="box"><h2>2) خطة المذاكرة الشخصية</h2><p><button onclick="location.href='/student/study-queue'">فتح قائمة المذاكرة الديناميكية</button></p>${x.personal_study_plan.map(p=>'<div class=card><b>'+p.priority+'. '+e(p.title)+'</b><div class=muted>'+e(p.reason)+'</div></div>').join('')}</div><div class="box"><h2>3) المراجعة المتباعدة للأخطاء</h2>${x.spaced_review.questions.length?x.spaced_review.questions.map(q=>'<div class=q><b>'+e(q.lesson_title||'غير مصنف')+'</b> · '+e(q.text_verbatim)+'<div class=muted>تكرر الخطأ: '+q.wrong_count+' · المصدر: '+e(q.source_filename)+' ص'+e(q.source_page)+'</div></div>').join(''):'<p class=good>لا توجد أخطاء متكررة مؤكدة حاليًا.</p>'}</div><div class="box"><h2>4) محاكاة امتحان</h2>${m.available?'<div class=card><b>'+e(m.quiz.title)+'</b><div class=muted>'+(m.quiz.duration_minutes||'—')+' دقيقة · المحاولات السابقة: '+m.quiz.attempts_used+'</div><button onclick="location.href=\''+m.student_path+'\'">ابدأ المحاكاة</button></div>':'<p class=muted>'+e(m.reason)+'</p>'}</div><div class="box"><h2>5) مؤشر الجاهزية وتوقع الأداء</h2><div class=grid><div class=card>المتوسط الحديث<div class=big>${rd.recent_average??'—'}%</div></div><div class=card>الاتجاه<div class="big ${rd.trend!=null&&rd.trend>=0?'good':'warn'}">${rd.trend==null?'—':(rd.trend>0?'+':'')+rd.trend+'%'}</div></div><div class=card>دروس ضعيفة<div class=big>${rd.weak_lessons}</div></div></div></div><div class="box"><h2>6) تقرير المتابعة الذكي</h2><p>الخطة الحالية تحتوي على <b>${x.progress_report.priority_plan.length}</b> أولويات و <b>${x.progress_report.review_count}</b> عناصر مراجعة.</p><div class=muted>آخر تحديث: ${e(x.progress_report.generated_at)}</div></div><div class="box"><h2>7) تطور نقاط الضعف</h2><div class=grid><div class=card><div class=muted>يتراجع</div><div class="big warn">${x.weakness_progression.summary.worsening_items}</div></div><div class=card><div class=muted>مفاهيم تحتاج متابعة</div><div class=big>${x.weakness_progression.summary.concepts_needing_attention}</div></div><div class=card><div class=muted>مهارات تحتاج متابعة</div><div class=big>${x.weakness_progression.summary.skills_needing_attention}</div></div><div class=card><div class=muted>تم التعافي</div><div class="big good">${x.weakness_progression.summary.recovered_items}</div></div></div></div><div class="box"><h2>8) قائمة المذاكرة الديناميكية</h2><p>لديك <b>${x.dynamic_study_queue.summary.tasks}</b> مهام مرتبة حسب الأولوية.</p><button onclick="location.href='/student/study-queue'">فتح القائمة</button></div><div class="box"><h2>9) التحفيز والإنجازات</h2>${x.achievements.earned.length?x.achievements.earned.map(a=>'<div class=card><b>'+e(a.title)+'</b><div class=muted>'+e(a.description)+'</div></div>').join(''):'<p class=muted>أكمل أول اختبار لبدء سجل الإنجازات.</p>'}</div>`}window.addEventListener('DOMContentLoaded',async()=>{let s=await fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));if(s.authenticated)load()})</script></main></html>'''


@app.get("/student/learning-suite", response_class=HTMLResponse)
def learning_suite_page():
    return HTMLResponse(PAGE)
