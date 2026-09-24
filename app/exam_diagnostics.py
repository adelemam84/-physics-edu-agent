from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .db import connect
from .security import require_admin
from .student_security import resolve_student_code

router = APIRouter()


def _attempt_diagnostic(con, attempt_id: int):
    attempt = con.execute(
        """SELECT a.id,a.student_id,a.quiz_id,a.score,a.max_score,a.started_at,a.completed_at,
          s.name student_name,qz.title quiz_title
          FROM attempts a
          JOIN students s ON s.id=a.student_id
          JOIN quizzes qz ON qz.id=a.quiz_id
          WHERE a.id=%s""",
        (attempt_id,),
    ).fetchone()
    if not attempt:
        raise HTTPException(404, "المحاولة غير موجودة")
    rows = list(con.execute(
        """SELECT min(aa.id) answer_row_id,aa.question_id,aa.answer_text,aa.is_correct,aa.points_awarded,aa.time_spent_seconds,
          q.text_verbatim,q.accepted_answer,q.solution_verbatim,q.difficulty,q.question_type,
          coalesce(q.source_page,q.page) source_page,d.filename source_filename,
          l.id lesson_id,l.title lesson_title,
          string_agg(DISTINCT c.title,'، ') concepts,
          string_agg(DISTINCT sk.name_ar,'، ') skills
          FROM attempt_answers aa
          JOIN questions q ON q.id=aa.question_id
          LEFT JOIN documents d ON d.id=q.document_id
          LEFT JOIN lessons l ON l.id=q.lesson_id
          LEFT JOIN question_concepts qc ON qc.question_id=q.id
          LEFT JOIN concepts c ON c.id=qc.concept_id
          LEFT JOIN question_skills qs ON qs.question_id=q.id
          LEFT JOIN skills sk ON sk.id=qs.skill_id
          WHERE aa.attempt_id=%s
          GROUP BY aa.question_id,aa.answer_text,aa.is_correct,aa.points_awarded,aa.time_spent_seconds,
            q.text_verbatim,q.accepted_answer,q.solution_verbatim,q.difficulty,q.question_type,
            q.source_page,q.page,d.filename,l.id,l.title
          ORDER BY answer_row_id""",
        (attempt_id,),
    ).fetchall())
    lessons = list(con.execute(
        """SELECT coalesce(l.title,'غير مصنف') label,count(*) responses,
          count(*) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(*) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(*),0),1) mastery
          FROM attempt_answers aa
          JOIN questions q ON q.id=aa.question_id
          LEFT JOIN lessons l ON l.id=q.lesson_id
          WHERE aa.attempt_id=%s
          GROUP BY l.id,l.title ORDER BY mastery ASC NULLS LAST,responses DESC""",
        (attempt_id,),
    ).fetchall())
    concepts = list(con.execute(
        """SELECT c.title label,count(*) responses,
          count(*) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(*) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(*),0),1) mastery
          FROM attempt_answers aa
          JOIN question_concepts qc ON qc.question_id=aa.question_id
          JOIN concepts c ON c.id=qc.concept_id
          WHERE aa.attempt_id=%s
          GROUP BY c.id,c.title ORDER BY mastery ASC NULLS LAST,responses DESC""",
        (attempt_id,),
    ).fetchall())
    skills = list(con.execute(
        """SELECT sk.name_ar label,count(*) responses,
          count(*) FILTER(WHERE aa.is_correct=TRUE) correct,
          round(100.0*count(*) FILTER(WHERE aa.is_correct=TRUE)/nullif(count(*),0),1) mastery
          FROM attempt_answers aa
          JOIN question_skills qs ON qs.question_id=aa.question_id
          JOIN skills sk ON sk.id=qs.skill_id
          WHERE aa.attempt_id=%s
          GROUP BY sk.id,sk.name_ar ORDER BY mastery ASC NULLS LAST,responses DESC""",
        (attempt_id,),
    ).fetchall())
    slow = sorted(
        [dict(r) for r in rows],
        key=lambda x: int(x.get("time_spent_seconds") or 0),
        reverse=True,
    )[:5]
    weak_questions = [dict(r) for r in rows if r["is_correct"] is False]
    pct = round(float(attempt["score"] or 0) / float(attempt["max_score"] or 1) * 100, 1) if attempt["max_score"] else 0.0
    return {
        "attempt": {**attempt, "percentage": pct},
        "summary": {
            "questions": len(rows),
            "correct": sum(1 for r in rows if r["is_correct"] is True),
            "incorrect": sum(1 for r in rows if r["is_correct"] is False),
            "total_time_seconds": sum(int(r["time_spent_seconds"] or 0) for r in rows),
            "average_time_seconds": round(sum(int(r["time_spent_seconds"] or 0) for r in rows) / len(rows), 1) if rows else 0,
        },
        "lessons": lessons,
        "concepts": concepts,
        "skills": skills,
        "weak_questions": weak_questions,
        "slow_questions": slow,
        "questions": rows,
        "policy": {
            "diagnosis_source": "deterministic_attempt_data",
            "content_source": "approved_pdf_only",
            "ai_auto_grading_override": False,
        },
    }


@router.get("/api/student/attempts/{attempt_id}/diagnostic")
def student_attempt_diagnostic(attempt_id: int, request: Request):
    code = resolve_student_code(request)
    with connect() as con:
        owner = con.execute(
            """SELECT s.external_code FROM attempts a JOIN students s ON s.id=a.student_id
               WHERE a.id=%s AND a.completed_at IS NOT NULL""",
            (attempt_id,),
        ).fetchone()
        if not owner or owner["external_code"] != code:
            raise HTTPException(404, "المحاولة غير موجودة")
        return _attempt_diagnostic(con, attempt_id)


@router.get("/api/admin/attempts/{attempt_id}/diagnostic", dependencies=[Depends(require_admin)])
def admin_attempt_diagnostic(attempt_id: int):
    with connect() as con:
        return _attempt_diagnostic(con, attempt_id)


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>التحليل التشخيصي للنتيجة</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:980px;margin:auto;padding:16px}
.box{background:#fff;border:1px solid #e4e7ec;border-radius:16px;padding:16px;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.big{font-size:26px;font-weight:800}.muted{color:#667085}.bad{color:#b42318}.ok{color:#067647}.warn{color:#b54708}
.q{border:1px solid #e4e7ec;border-radius:12px;padding:12px;margin:8px 0}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:560px}td,th{padding:8px;border-bottom:1px solid #eee;text-align:right}a{color:#175cd3;text-decoration:none}button{padding:10px 12px;border:1px solid #ccd2dd;border-radius:9px;background:#2447a8;color:#fff;cursor:pointer}button:disabled{opacity:.6;cursor:wait}a:focus-visible,button:focus-visible{outline:3px solid #84adff;outline-offset:2px}@media(max-width:600px){main{padding:10px}.box{padding:13px;border-radius:13px}.grid{grid-template-columns:1fr 1fr}}@media(max-width:390px){.grid{grid-template-columns:1fr}}
</style><main><div class=box><a href="/student">← بوابة الطالب</a> · <a href="/student/command-center">مهمة اليوم</a> · <a href="/student/study-queue">قائمة المذاكرة</a></div><div id=content class=box role=status aria-live=polite>جارٍ تحميل التحليل...</div>
<script>
const id=Number(location.pathname.split('/').pop()),content=document.getElementById('content');function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function sec(v){v=Number(v||0);return v<60?v+' ث':Math.floor(v/60)+' د '+(v%60)+' ث'}
function rows(title,a){return '<div class=box><h2>'+title+'</h2><div class=table-wrap><table><tr><th>البند</th><th>الإجابات</th><th>الإتقان</th></tr>'+a.map(x=>'<tr><td>'+e(x.label)+'</td><td>'+x.responses+'</td><td class="'+(Number(x.mastery)<60?'bad':Number(x.mastery)<80?'warn':'ok')+'">'+(x.mastery??'—')+'%</td></tr>').join('')+'</table></div></div>'}
async function load(){let s=await fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));if(!s.authenticated){location.href='/student';return}let r=await fetch('/api/student/attempts/'+id+'/diagnostic',{cache:'no-store'}),x=await r.json().catch(()=>null);if(!r.ok){content.textContent=typeof x?.detail==='string'?x.detail:'تعذر تحميل التحليل';return}
let a=x.attempt,s=x.summary;content.outerHTML='<div class=box><h1>'+e(a.quiz_title)+'</h1><div class=muted>'+e(a.student_name)+'</div><div class=grid><div class=card><div class=muted>النتيجة</div><div class=big>'+a.percentage+'%</div></div><div class=card><div class=muted>صحيح</div><div class="big ok">'+s.correct+'</div></div><div class=card><div class=muted>خطأ</div><div class="big bad">'+s.incorrect+'</div></div><div class=card><div class=muted>متوسط زمن السؤال</div><div class=big>'+sec(s.average_time_seconds)+'</div></div></div></div>'+rows('حسب الدرس',x.lessons)+rows('حسب المفهوم',x.concepts)+rows('حسب المهارة',x.skills)+'<div class=box><h2>تدريب نقاط الضعف</h2><p class=muted>ينشئ تدريبًا جديدًا من نقاط ضعف هذه المحاولة فقط، باستخدام أسئلة أخرى معتمدة من المصدر.</p><button id=weakBtn onclick="weaknessPractice()">إنشاء تدريب نقاط الضعف</button><span id=weakMsg class=muted role=status aria-live=polite></span></div><div class=box><h2>الأخطاء التي تحتاج مراجعة</h2>'+(x.weak_questions.length?x.weak_questions.map(q=>'<div class=q><b>'+e(q.lesson_title||'غير مصنف')+'</b><p>'+e(q.text_verbatim)+'</p><div class=bad>إجابتك: '+e(q.answer_text||'بدون إجابة')+'</div><div class=ok>الإجابة المعتمدة: '+e(q.accepted_answer||'—')+'</div><div class=muted>المصدر: '+e(q.source_filename||'—')+' · صفحة '+e(q.source_page||'—')+' · الزمن '+sec(q.time_spent_seconds)+'</div>'+(q.solution_verbatim?'<div class=muted>الحل من المصدر: '+e(q.solution_verbatim)+'</div>':'')+'</div>').join(''):'<p class=ok>لا توجد أخطاء في هذه المحاولة.</p>')+'</div><div class=box><h2>الأسئلة التي استغرقت وقتًا أطول</h2>'+x.slow_questions.map(q=>'<div class=q><b>'+sec(q.time_spent_seconds)+'</b> · '+e(q.lesson_title||'غير مصنف')+'<div>'+e(q.text_verbatim)+'</div></div>').join('')+'</div>'}
async function weaknessPractice(){let weakMsg=document.getElementById('weakMsg'),weakBtn=document.getElementById('weakBtn');weakBtn.disabled=true;weakMsg.textContent=' جارٍ إنشاء التدريب...';let r=await fetch('/api/student/attempts/'+id+'/weakness-practice/create?count=10',{method:'POST'}),x=await r.json().catch(()=>null);if(!r.ok){weakBtn.disabled=false;weakMsg.textContent=' '+(typeof x?.detail==='string'?x.detail:(x?.detail?.message||'تعذر إنشاء التدريب'));return}location.href=x.student_path}
load()
</script></main></html>'''


@router.get("/student/results/{attempt_id}", response_class=HTMLResponse)
def student_result_diagnostic_page(attempt_id: int):
    return PAGE
